from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_member
from ..models import DRAFT, TODO, Meeting, Task, TeamMember, User, Utterance
from ..schemas import MeetingBrief, MeetingCreate, MeetingOut
from ..services import ai, parser
from ..services.contribution import record_snapshot
from ..services.notifications import notify
from ..timeutil import today_kst

router = APIRouter(tags=["meetings"])


def _meeting_out(m: Meeting) -> MeetingOut:
    return MeetingOut(id=m.id, team_id=m.team_id, title=m.title, meeting_date=m.meeting_date, confirmed=m.confirmed,
                      ai_source=m.ai_source, summary=m.summary, utterance_count=len(m.utterances),
                      tasks=list(m.tasks))


@router.post("/teams/{team_id}/meetings", response_model=MeetingOut, status_code=201)
def create_meeting(team_id: int, body: MeetingCreate, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """회의록 텍스트 → 화자별 발언 저장 + AI 요약/할 일 추출(초안). 확정은 /meetings/{id}/confirm"""
    require_member(db, team_id, user)
    members = {u.id: u.name for u in db.scalars(
        select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team_id))}
    mdate = body.meeting_date or today_kst()

    meeting = Meeting(team_id=team_id, created_by=user.id, title=body.title.strip() or "팀 회의",
                      raw_text=body.raw_text, meeting_date=mdate)
    for speaker, content in parser.parse_utterances(body.raw_text):
        meeting.utterances.append(Utterance(speaker_name=speaker, content=content,
                                            user_id=parser.match_member(speaker, members),
                                            char_count=parser.count_chars(content)))
    analysis = ai.analyze_meeting(body.raw_text, list(members.values()), mdate)
    meeting.summary, meeting.ai_source = analysis.summary, analysis.source
    db.add(meeting)
    db.flush()

    for it in analysis.action_items:
        uid = parser.match_member(it.assignee, members)
        db.add(Task(team_id=team_id, meeting_id=meeting.id, assignee_id=uid, assignee_name_raw=it.assignee,
                    title=it.task[:300], due_date=it.due_date, difficulty=min(3, max(1, it.difficulty)),
                    status=DRAFT))
    db.commit()
    record_snapshot(db, team_id)
    db.refresh(meeting)
    return _meeting_out(meeting)


@router.get("/teams/{team_id}/meetings", response_model=list[MeetingBrief])
def list_meetings(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, team_id, user)
    return db.scalars(select(Meeting).where(Meeting.team_id == team_id).order_by(Meeting.id.desc())).all()


@router.get("/meetings/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "회의록을 찾을 수 없습니다")
    require_member(db, m.team_id, user)
    return _meeting_out(m)


@router.post("/meetings/{meeting_id}/confirm", response_model=MeetingOut)
def confirm_meeting(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """초안 할 일을 확정하여 각 담당자 대시보드에 배정하고 알림을 보냄. (담당자 미정 초안은 먼저 PATCH로 지정)"""
    m = db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "회의록을 찾을 수 없습니다")
    require_member(db, m.team_id, user)
    drafts = [t for t in m.tasks if t.status == DRAFT]
    unassigned = [t.id for t in drafts if t.assignee_id is None]
    if unassigned:
        raise HTTPException(409, {"message": "담당자가 정해지지 않은 할 일이 있습니다", "task_ids": unassigned})
    for t in drafts:
        t.status = TODO
        notify(db, t.assignee_id, "assigned", t)
    m.confirmed = True
    db.commit()
    return _meeting_out(m)
