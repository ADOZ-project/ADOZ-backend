import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_member
from ..models import Team, TeamMember, User
from ..schemas import JoinIn, MemberOut, TeamCreate, TeamOut

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
