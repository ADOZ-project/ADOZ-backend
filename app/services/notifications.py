"""마스코트 알림: 템플릿 멘트 + 매일 마감 체크 + 푸시(FCM 연동 지점)"""
import logging
import random
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DOING, TODO, Notification, Task, User
from ..timeutil import today_kst

log = logging.getLogger("adoz.push")

MSG = {
    "assigned": ["새 할 일이 도착했어요. 마스코트가 응원합니다!"],
    "praise": [
        "좋아요, 이 정도면 A+의 냄새가 납니다.",
        "마감 전에 끝내다니… 팀의 에이스 등장입니다.",
        "깔끔합니다. 교수님의 미소가 벌써 보여요.",
    ],
    "due_soon": [
        "지금 안 하면 발표 전날 밤샘 확정입니다.",
        "마감이 내일입니다. 오늘의 나, 힘내라!",
    ],
    "due_today": [
        "오늘이 마감입니다. 마스코트가 지켜보고 있어요.",
        "D-day입니다. 지금 시작하면 아직 늦지 않았어요!",
    ],
    "overdue": [
        "팀원이 아니라 전설의 미루기 장인입니까?",
        "마감이 지났어요. 팀원들이 기다리고 있습니다.",
    ],
}


def send_push(user: User, title: str, body: str) -> None:
    """TODO: firebase_admin.messaging 으로 교체. 현재는 로그만 남김."""
    if user.fcm_token:
        log.info("PUSH → user=%s title=%s body=%s", user.id, title, body)


def notify(db: Session, user_id: int, kind: str, task: Task | None, dedupe_key: str | None = None) -> bool:
    if dedupe_key and db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return False
    text = random.choice(MSG[kind])
    message = f"[{task.title[:40]}] {text}" if task else text
    db.add(Notification(user_id=user_id, task_id=task.id if task else None, kind=kind, message=message,
                        dedupe_key=dedupe_key))
    user = db.get(User, user_id)
    if user:
        send_push(user, "ADOZ", message)
    return True


def run_daily_reminders(db: Session, today: date | None = None) -> int:
    today = today or today_kst()
    sent = 0
    tasks = db.scalars(
        select(Task).where(Task.status.in_([TODO, DOING]), Task.due_date.is_not(None), Task.assignee_id.is_not(None))
    )
    for t in tasks:
        delta = (t.due_date - today).days
        kind = {1: "due_soon", 0: "due_today"}.get(delta, "overdue" if delta < 0 else None)
        if kind and notify(db, t.assignee_id, kind, t, f"{t.id}:{kind}:{today.isoformat()}"):
            sent += 1
    db.commit()
    return sent
