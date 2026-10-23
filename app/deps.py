from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Task, TeamMember, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(401, "로그인이 필요합니다")
    uid = decode_token(cred.credentials)
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "유효하지 않은 토큰입니다")
    return user


def require_member(db: Session, team_id: int, user: User) -> TeamMember:
    m = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id))
    if not m:
        raise HTTPException(403, "해당 팀의 멤버가 아닙니다")
    return m


def get_task_for_member(db: Session, task_id: int, user: User) -> tuple[Task, TeamMember]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "할 일을 찾을 수 없습니다")
    return task, require_member(db, task.team_id, user)
