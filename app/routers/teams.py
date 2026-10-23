import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_member
from ..models import DONE, Task, Team, TeamMember, User
from ..schemas import JoinIn, LeaderIn, MemberOut, TeamCreate, TeamOut, TeamUpdate
from ..services.contribution import record_snapshot

router = APIRouter(tags=["teams"])
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 문자(0,O,1,I) 제외


def _team_out(team: Team) -> TeamOut:
    return TeamOut(id=team.id, name=team.name, invite_code=team.invite_code, deadline=team.deadline,
                   members=[MemberOut(user_id=m.user_id, name=m.user.name, role=m.role) for m in team.members])


@router.post("/teams", response_model=TeamOut, status_code=201)
def create_team(body: TeamCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for _ in range(10):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not db.scalar(select(Team.id).where(Team.invite_code == code)):
            break
    team = Team(name=body.name.strip(), deadline=body.deadline, invite_code=code)
    team.members.append(TeamMember(user_id=user.id, role="leader"))
    db.add(team)
    db.commit()
    return _team_out(team)


@router.post("/teams/join", response_model=TeamOut)
def join_team(body: JoinIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.scalar(select(Team).where(Team.invite_code == body.invite_code.strip().upper()))
    if not team:
        raise HTTPException(404, "초대 코드가 올바르지 않습니다")
    if any(m.user_id == user.id for m in team.members):
        raise HTTPException(409, "이미 참여한 팀입니다")
    team.members.append(TeamMember(user_id=user.id, role="member"))
    db.commit()
    return _team_out(team)


@router.get("/teams", response_model=list[TeamOut])
def my_teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    teams = db.scalars(select(Team).join(TeamMember).where(TeamMember.user_id == user.id)).all()
    return [_team_out(t) for t in teams]


@router.get("/teams/{team_id}", response_model=TeamOut)
def get_team(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, team_id, user)
    return _team_out(db.get(Team, team_id))


def _require_leader(db: Session, team_id: int, user: User) -> TeamMember:
    member = require_member(db, team_id, user)
    if member.role != "leader":
        raise HTTPException(403, "팀장만 할 수 있습니다")
    return member


@router.patch("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, body: TeamUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """팀 이름·마감일 수정 (팀장)"""
    _require_leader(db, team_id, user)
    team = db.get(Team, team_id)
    if body.name is not None:
        team.name = body.name.strip()
    if body.deadline is not None:
        team.deadline = body.deadline
    if body.clear_deadline:
        team.deadline = None
    db.commit()
    return _team_out(team)


@router.post("/teams/{team_id}/leader", response_model=TeamOut)
def transfer_leader(team_id: int, body: LeaderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """팀장 위임"""
    me = _require_leader(db, team_id, user)
    target = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == body.user_id))
    if not target:
        raise HTTPException(422, "팀원이 아닌 사용자입니다")
    me.role, target.role = "member", "leader"
    db.commit()
    return _team_out(db.get(Team, team_id))


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
def remove_member(team_id: int, user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """팀 나가기(본인) 또는 내보내기(팀장). 끝나지 않은 할 일은 미배정으로 돌려 팀장이 다시 배정"""
    me = require_member(db, team_id, user)
    if user_id != user.id and me.role != "leader":
        raise HTTPException(403, "다른 팀원을 내보내는 것은 팀장만 가능합니다")
    target = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    if not target:
        raise HTTPException(404, "팀원이 아닙니다")
    others = db.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team_id, TeamMember.user_id != user_id))
    if target.role == "leader" and others:
        raise HTTPException(409, "팀장은 다른 팀원에게 팀장을 위임한 뒤 나갈 수 있습니다")
    for t in db.scalars(select(Task).where(Task.team_id == team_id, Task.assignee_id == user_id, Task.status != DONE)):
        t.assignee_id = None
    db.delete(target)
    db.commit()
    record_snapshot(db, team_id)
