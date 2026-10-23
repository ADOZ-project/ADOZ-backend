"""시연용 데모 데이터 생성: 팀 + 팀원 4명 + 회의록 4개(AI 분석) + 할 일 진행 + 업로드 + 기여도 타임라인

실행(프로젝트 루트, 서버는 끈 상태에서): python scripts/seed_demo.py --reset
  --reset : DB의 모든 테이블을 비우고 새로 만듦 (기존 데이터 삭제)
회의록은 실제 API로 올려서 .env의 AI 설정(Groq/OpenAI)으로 분석되고, 키가 없으면 규칙 기반 폴백으로 동작.
"""
import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone

os.environ["SCHEDULER_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DOING, DONE, ContributionSnapshot, Task, Upload, User  # noqa: E402
from app.services.contribution import record_snapshot  # noqa: E402
from app.services.notifications import notify  # noqa: E402
from app.timeutil import KST, today_kst, utcnow  # noqa: E402

PASSWORD = "adoz1234!"
TEAM_NAME = "ADOZ 캡스톤팀"
# (이름, 이메일, 성향) - 성향에 따라 완료 시점/업로드 분량이 달라져 기여도 차이가 드러남
MEMBERS = [
    ("국다인", "dain@adoz.kr", "mixed"),   # 팀장, 발언 많음
    ("이하준", "hajun@adoz.kr", "early"),  # 미리미리 끝내고 문서도 많이 씀
    ("박서연", "seoyeon@adoz.kr", "ontime"),
    ("최민재", "minjae@adoz.kr", "late"),  # 자주 늦음
]
UPLOAD_CHARS = {"early": 2200, "ontime": 1500, "mixed": 900, "late": 400}

# (가장 최근 화요일로부터 몇 주 전, 제목, 회의록)
# 회의는 항상 화요일 → '이번 주 목요일' 같은 상대 기한이 실행 요일과 상관없이 미래 날짜로 환산됨
MEETINGS = [
    (3, "1차 주제 선정 회의", """국다인: 오늘은 주제부터 확정하자. 캠퍼스 분실물 찾기 앱 어때? 학생들이 실제로 불편해하는 부분이라 설득력이 있을 것 같아.
이하준: 좋아. 그럼 나는 경쟁 앱 조사를 금요일까지 정리할게.
박서연: 나는 사용자 인터뷰 질문지 만들게. 다음 주 월요일까지.
최민재: 디자인은 내가 할게. 와이어프레임은 다음 주 수요일까지 낼게.
국다인: 좋아, 나는 발표 자료 틀을 이번 주 일요일까지 잡아둘게. 다음 회의는 다음 주에 하자."""),
    (2, "2차 역할 재조정", """이하준: 경쟁 앱 조사 끝났어. 공유 폴더에 올렸어. 기존 앱들은 분실물 등록 절차가 복잡하다는 게 공통 문제였어.
국다인: 고마워. 서연아 인터뷰는 어떻게 됐어?
박서연: 3명 했고 2명 더 남았어. 이번 주 목요일까지 마무리할게.
국다인: 민재 와이어프레임은 조금 늦어지고 있지? 하준이가 프론트 맡기로 하자.
이하준: 응 내가 맡을게. 로그인 화면부터 다음 주 월요일까지 해볼게.
최민재: 와이어프레임은 내일까지 마무리하고, 디자인 시스템 색상표는 금요일까지 공유할게.
국다인: 나는 중간발표 일정 확인하고 내일까지 공지할게."""),
    (1, "3차 중간 점검", """[회의 메모 - 서기 박서연]
- 참석: 다인, 하준, 서연, 민재
- 중간발표는 다음 주 화요일. 다인이 발표 대본 작성, 이번 주 토요일까지.
- 하준: 로그인 화면 완료. 분실물 등록 화면은 이번 주 금요일까지 진행
- 서연: 인터뷰 결과 분석 보고서 내일까지 정리
- 민재: 아이콘 세트 추가 제작 (기한 미정)
- 서버 배포는 아직 담당 미정 → 다음 회의에서 결정"""),
    (0, "4차 중간발표 피드백 회의", """최민재: 어제 축제 갔어?
국다인: 갔지. 아 근데 중간발표 피드백 정리해야 돼. 교수님이 데이터 근거가 부족하다고 하셨잖아.
박서연: 내가 설문 다시 돌릴게. 다음 주 수요일까지 결과 정리해서 공유할게.
이하준: 그럼 나는 분실물 검색 기능을 다음 주 월요일까지 붙여볼게.
이하준: 서버는 민재가 해줄 수 있어?
최민재: 음... 생각해볼게.
국다인: 그럼 서버는 일단 보류하고, 나는 피드백 문서를 모레까지 정리할게."""),
]


def _at(d: date, hour: int) -> datetime:
    """KST 날짜+시각 → UTC aware datetime"""
    return datetime.combine(d, time(hour), tzinfo=KST).astimezone(timezone.utc)


def _stamp_snapshots(db, team_id: int, after_id: int, when: datetime) -> int:
    """after_id 이후 생긴 스냅샷의 시각을 시뮬레이션 시각으로 맞추고, 마지막 id 반환"""
    for s in db.scalars(select(ContributionSnapshot).where(ContributionSnapshot.id > after_id)):
        s.calculated_at = when
    db.commit()
    return db.scalar(select(func.max(ContributionSnapshot.id))) or after_id


def _plan_completion(task: Task, meeting_day: date, style: str, n: int) -> datetime | None:
    """성향별 완료 시각. 아직 오지 않은 시각이면 None(미완료)"""
    if task.due_date:
        offset = {"early": -1, "ontime": 0, "late": 2, "mixed": 0 if n % 2 == 0 else 1}[style]
        day = max(task.due_date + timedelta(days=offset), meeting_day)  # 회의 당일 마감이면 당일 저녁 완료
    else:
        day = meeting_day + timedelta(days={"early": 2, "ontime": 3, "mixed": 4, "late": 6}[style])
    when = _at(day, 21 if style == "late" or day == meeting_day else 15)
    return when if when < utcnow() - timedelta(hours=1) else None


def _upload_text(task: Task, chars: int) -> bytes:
    body = (f"{task.title} 결과 정리. 회의에서 합의한 내용을 바탕으로 자료를 조사하고 핵심 근거와 다음 단계를 정리했다. ")
    text = f"# {task.title}\n\n" + body * (chars // len(body) + 1)
    return text[:chars].encode("utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="모든 테이블을 비우고 새로 생성")
    args = ap.parse_args()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        has_data = db.scalar(select(func.count(User.id)))
    if has_data and not args.reset:
        sys.exit(f"DB({settings.database_url})에 이미 데이터가 있습니다. 비우고 새로 만들려면 --reset 을 붙이세요.")
    if args.reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

    today = today_kst()
    styles = {email: style for _, email, style in MEMBERS}
    with TestClient(app) as c, SessionLocal() as db:
        tokens, uid_style = {}, {}
        for name, email, style in MEMBERS:
            uid = c.post("/auth/register", json={"name": name, "email": email, "password": PASSWORD}).json()["id"]
            tokens[uid] = c.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
            uid_style[uid] = styles[email]
        h = lambda uid: {"Authorization": f"Bearer {tokens[uid]}"}  # noqa: E731
        leader = next(iter(tokens))
        team = c.post("/teams", json={"name": TEAM_NAME, "deadline": (today + timedelta(days=14)).isoformat()},
                      headers=h(leader)).json()
        for uid in list(tokens)[1:]:
            c.post("/teams/join", json={"invite_code": team["invite_code"]}, headers=h(uid))
        tid = team["id"]

        last_snap, done_count = 0, {uid: 0 for uid in tokens}
        pending: list[tuple[datetime, int]] = []  # (완료 시각, task_id)

        def run_completions(until: datetime) -> None:
            nonlocal last_snap
            pending.sort()
            while pending and pending[0][0] < until:
                when, task_id = pending.pop(0)
                task = db.get(Task, task_id)
                task.status, task.completed_at = DONE, when
                db.commit()
                if task.due_date is None or when.astimezone(KST).date() <= task.due_date:
                    notify(db, task.assignee_id, "praise", task)
                    db.commit()
                r = c.post(f"/tasks/{task.id}/uploads", headers=h(task.assignee_id),
                           files={"file": (f"{task.title[:30]}.md", _upload_text(task, UPLOAD_CHARS[uid_style[task.assignee_id]]))})
                r.raise_for_status()
                db.get(Upload, r.json()["id"]).created_at = when
                db.commit()
                last_snap = _stamp_snapshots(db, tid, last_snap, when)

        last_tue = today - timedelta(days=(today.weekday() - 1) % 7 or 7)  # 오늘 이전의 가장 최근 화요일
        for weeks_ago, title, raw in MEETINGS:
            mday = last_tue - timedelta(weeks=weeks_ago)
            run_completions(_at(mday, 10))
            r = c.post(f"/teams/{tid}/meetings", json={"title": title, "raw_text": raw, "meeting_date": mday.isoformat()},
                       headers=h(leader))
            r.raise_for_status()
            m = r.json()
            for t in m["tasks"]:  # AI가 담당자를 못 정한 초안은 시연에서 혼란스러우니 제거
                if t["assignee_id"] is None:
                    c.delete(f"/tasks/{t['id']}", headers=h(leader))
            c.post(f"/meetings/{m['id']}/confirm", headers=h(leader)).raise_for_status()
            last_snap = _stamp_snapshots(db, tid, last_snap, _at(mday, 11))
            print(f"[{mday}] {title}: ai_source={m['ai_source']}, 할 일 {sum(1 for t in m['tasks'] if t['assignee_id'])}건")

            for t in db.scalars(select(Task).where(Task.meeting_id == m["id"])):
                when = _plan_completion(t, mday, uid_style[t.assignee_id], done_count[t.assignee_id])
                done_count[t.assignee_id] += 1
                if when:
                    pending.append((when, t.id))
                elif weeks_ago <= 1:
                    t.status = DOING
            db.commit()

        run_completions(utcnow())
        record_snapshot(db, tid)

        print(f"\n팀: {TEAM_NAME} (team_id={tid}, 초대 코드 {team['invite_code']})")
        for s in sorted(c.get(f"/teams/{tid}/contributions", headers=h(leader)).json(), key=lambda s: -s["total"]):
            print(f"  {s['name']}: 기여도 {s['total']:.1f}%  ({s.get('persona', '')})")
        print(f"\n로그인: {', '.join(e for _, e, _ in MEMBERS)} / 비밀번호 {PASSWORD}")


if __name__ == "__main__":
    main()
