"""다차원 기여도 계산: 발언 비중 + 할 일(마감 준수) + 업로드 글자 수"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DONE, DRAFT, ContributionSnapshot, Meeting, Task, TeamMember, Upload, User, Utterance
from ..timeutil import to_kst_date, today_kst


@dataclass
class MemberScore:
    user_id: int
    name: str
    speech_chars: int = 0
    speech_share: float = 0.0
    task_points: float = 0.0
    task_share: float = 0.0
    upload_chars: int = 0
    upload_share: float = 0.0
    tasks_assigned: int = 0
    tasks_done: int = 0
    on_time_rate: float | None = None  # 마감이 도래했거나 완료된 할 일 중 기한 내 완료 비율
    total: float = 0.0  # 0~100
    persona: str = ""


def _share(values: dict[int, float]) -> dict[int, float]:
    tot = sum(values.values())
    return {k: (v / tot if tot else 0.0) for k, v in values.items()}


def compute_scores(db: Session, team_id: int) -> list[MemberScore]:
    rows = db.execute(
        select(User.id, User.name).join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id).order_by(User.id)
    ).all()
    scores = {uid: MemberScore(uid, name) for uid, name in rows}
    if not scores:
        return []

    # 1) 발언량
    for uid, chars in db.execute(
        select(Utterance.user_id, func.sum(Utterance.char_count))
        .join(Meeting, Meeting.id == Utterance.meeting_id)
        .where(Meeting.team_id == team_id, Utterance.user_id.is_not(None))
        .group_by(Utterance.user_id)
    ):
        if uid in scores:
            scores[uid].speech_chars = int(chars or 0)

    # 2) 할 일: 난이도 가중치. 기한 내 완료 = 1.0배, 지각 완료 = 0.5배
    today = today_kst()
    on_time_cnt = {uid: 0 for uid in scores}
    evaluated = {uid: 0 for uid in scores}
    tasks = db.scalars(select(Task).where(Task.team_id == team_id, Task.status != DRAFT, Task.assignee_id.is_not(None)))
    for t in tasks:
        s = scores.get(t.assignee_id)
        if not s:
            continue
        s.tasks_assigned += 1
        if t.status == DONE:
            s.tasks_done += 1
            late = bool(t.due_date and t.completed_at and to_kst_date(t.completed_at) > t.due_date)
            s.task_points += t.difficulty * (0.5 if late else 1.0)
            evaluated[t.assignee_id] += 1
            on_time_cnt[t.assignee_id] += 0 if late else 1
        elif t.due_date and t.due_date < today:  # 기한이 지났는데 미완료 → 준수율에 반영
            evaluated[t.assignee_id] += 1
    for uid, s in scores.items():
        s.on_time_rate = on_time_cnt[uid] / evaluated[uid] if evaluated[uid] else None

    # 3) 업로드 글자 수
    for uid, chars in db.execute(
        select(Upload.user_id, func.sum(Upload.char_count)).where(Upload.team_id == team_id).group_by(Upload.user_id)
    ):
        if uid in scores:
            scores[uid].upload_chars = int(chars or 0)

    sp = _share({u: s.speech_chars for u, s in scores.items()})
    tk = _share({u: s.task_points for u, s in scores.items()})
    up = _share({u: s.upload_chars for u, s in scores.items()})

    # 데이터가 없는 항목은 가중치에서 제외하고 나머지를 재정규화
    weights = {"speech": settings.score_w_speech, "task": settings.score_w_task, "upload": settings.score_w_upload}
    has = {"speech": any(sp.values()), "task": any(tk.values()), "upload": any(up.values())}
    wsum = sum(w for k, w in weights.items() if has[k]) or 1.0
    for uid, s in scores.items():
        s.speech_share, s.task_share, s.upload_share = sp[uid], tk[uid], up[uid]
        s.total = 100 * (
            (weights["speech"] * sp[uid] if has["speech"] else 0)
            + (weights["task"] * tk[uid] if has["task"] else 0)
            + (weights["upload"] * up[uid] if has["upload"] else 0)
        ) / wsum
        s.persona = persona_for(s)
    return list(scores.values())


def persona_for(s: MemberScore) -> str:
    """수치 기반 규칙으로 작업 성향 라벨 결정 (일관성 확보)"""
    dims = {"speech": s.speech_share, "task": s.task_share, "upload": s.upload_share}
    if not any(dims.values()):
        return "탐색 중인 새싹형"
    if s.on_time_rate == 1.0 and s.tasks_done >= 2:
        return "칼마감 지킴이형"
    label = {"speech": "아이디어 뱅크형", "task": "든든한 실행가형", "upload": "꼼꼼한 문서 장인형"}
    return label[max(dims, key=dims.get)]


def record_snapshot(db: Session, team_id: int) -> None:
    """리포트 타임라인용 스냅샷 저장 (회의 등록/할 일 완료/업로드 시 호출)"""
    for s in compute_scores(db, team_id):
        db.add(ContributionSnapshot(team_id=team_id, user_id=s.user_id, speech=s.speech_share * 100,
                                    task=s.task_share * 100, upload=s.upload_share * 100, total=s.total))
    db.commit()
