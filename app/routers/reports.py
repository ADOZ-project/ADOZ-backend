from datetime import timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_member
from ..models import ContributionSnapshot, Team, User
from ..schemas import ScoreOut
from ..services.contribution import compute_scores
from ..services.report import build_report

router = APIRouter(tags=["contributions"])


@router.get("/teams/{team_id}/contributions", response_model=list[ScoreOut])
def contributions(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_member(db, team_id, user)
    return sorted(compute_scores(db, team_id), key=lambda s: -s.total)


@router.get("/teams/{team_id}/contributions/history")
def contribution_history(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """차트용 시계열: [{at(UTC, ISO 8601), user_id, total, speech, task, upload}]"""
    require_member(db, team_id, user)
    snaps = db.scalars(select(ContributionSnapshot).where(ContributionSnapshot.team_id == team_id)
                       .order_by(ContributionSnapshot.calculated_at)).all()
    return [{"at": (s.calculated_at if s.calculated_at.tzinfo else s.calculated_at.replace(tzinfo=timezone.utc)).isoformat(), "user_id": s.user_id, "total": round(s.total, 1),
             "speech": round(s.speech, 1), "task": round(s.task, 1), "upload": round(s.upload, 1)} for s in snaps]


@router.post("/teams/{team_id}/report")
def create_report(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """원클릭 기여도 리포트 PDF"""
    require_member(db, team_id, user)
    pdf = build_report(db, team_id)
    fname = quote(f"{db.get(Team, team_id).name}_기여도리포트.pdf")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})
