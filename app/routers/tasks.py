import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_task_for_member, require_member
from ..models import DONE, DRAFT, TASK_STATUSES, Task, TeamMember, Upload, User
from ..schemas import TaskOut, TaskUpdate, UploadOut
from ..services import files, parser
from ..services.contribution import record_snapshot
from ..services.notifications import notify
from ..timeutil import to_kst_date, utcnow

router = APIRouter(tags=["tasks"])
MAX_UPLOAD = 10 * 1024 * 1024


@router.get("/me/tasks", response_model=list[TaskOut])
def my_tasks(status: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Task).where(Task.assignee_id == user.id, Task.status != DRAFT).order_by(Task.due_date.is_(None), Task.due_date)
    if status:
        q = q.where(Task.status == status.upper())
    return db.scalars(q).all()


@router.get("/teams/{team_id}/tasks", response_model=list[TaskOut])
def team_tasks(team_id: int, include_draft: bool = False, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    require_member(db, team_id, user)
    q = select(Task).where(Task.team_id == team_id).order_by(Task.due_date.is_(None), Task.due_date)
    if not include_draft:
        q = q.where(Task.status != DRAFT)
    return db.scalars(q).all()


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task, member = get_task_for_member(db, task_id, user)
    is_owner = task.assignee_id == user.id
    is_leader = member.role == "leader"
    editing_fields = any(v is not None for v in (body.title, body.due_date, body.difficulty, body.assignee_id)) or body.clear_due_date

    if task.status == DRAFT:
        pass  # 초안은 팀원 누구나 수정 가능
    else:
        if editing_fields and not is_leader:
            raise HTTPException(403, "확정된 할 일의 내용 변경은 팀장만 가능합니다")
        if body.status is not None and not (is_owner or is_leader):
            raise HTTPException(403, "담당자 또는 팀장만 상태를 변경할 수 있습니다")

    if body.title is not None:
        task.title = body.title.strip()
    if body.due_date is not None:
        task.due_date = body.due_date
    if body.clear_due_date:
        task.due_date = None
    if body.difficulty is not None:
        task.difficulty = body.difficulty
    if body.assignee_id is not None:
        if not db.scalar(select(TeamMember.id).where(TeamMember.team_id == task.team_id, TeamMember.user_id == body.assignee_id)):
            raise HTTPException(422, "팀원이 아닌 사용자입니다")
        task.assignee_id = body.assignee_id

    newly_done = False
    if body.status is not None:
        st = body.status.upper()
        if st not in TASK_STATUSES or st == DRAFT:
            raise HTTPException(422, f"status는 {', '.join(s for s in TASK_STATUSES if s != DRAFT)} 중 하나여야 합니다")
        if task.status == DRAFT:
            raise HTTPException(409, "초안은 회의록 확정 후 상태를 변경할 수 있습니다")
        if st == DONE and task.status != DONE:
            task.completed_at, newly_done = utcnow(), True
        elif st != DONE:
            task.completed_at = None
        task.status = st

    db.add(task)
    db.flush()
    if newly_done:
        on_time = not task.due_date or to_kst_date(task.completed_at) <= task.due_date
        if on_time and task.assignee_id:
            notify(db, task.assignee_id, "praise", task)
    db.commit()
    if newly_done:
        record_snapshot(db, task.team_id)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task, member = get_task_for_member(db, task_id, user)
    if task.status != DRAFT and member.role != "leader":
        raise HTTPException(403, "확정된 할 일은 팀장만 삭제할 수 있습니다")
    if db.scalar(select(Upload.id).where(Upload.task_id == task.id)):
        raise HTTPException(409, "업로드된 자료가 있는 할 일은 삭제할 수 없습니다")
    db.delete(task)
    db.commit()


@router.post("/tasks/{task_id}/uploads", response_model=UploadOut, status_code=201)
async def upload_file(task_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    task, _ = get_task_for_member(db, task_id, user)
    if task.status == DRAFT:
        raise HTTPException(409, "확정되지 않은 할 일에는 업로드할 수 없습니다")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "파일은 10MB 이하여야 합니다")
    text = files.extract_text(file.filename or "file", data)

    os.makedirs(os.path.join(settings.storage_dir, "uploads"), exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1][:10]
    path = os.path.join(settings.storage_dir, "uploads", f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    up = Upload(task_id=task.id, team_id=task.team_id, user_id=user.id, filename=(file.filename or "file")[:255],
                path=path, char_count=parser.count_chars(text))
    db.add(up)
    db.commit()
    record_snapshot(db, task.team_id)
    return up


@router.get("/tasks/{task_id}/uploads", response_model=list[UploadOut])
def list_uploads(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task, _ = get_task_for_member(db, task_id, user)
    return db.scalars(select(Upload).where(Upload.task_id == task.id)).all()
