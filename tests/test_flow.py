import io
from datetime import date, timedelta

from app.database import SessionLocal
from app.services.notifications import run_daily_reminders

MEETING = """국다인: 이번 발표 주제는 ADOZ로 가요. 백엔드 API 설계는 내일까지 제가 끝낼게요.
박하준: 저는 발표 자료 초안을 금요일까지 만들게요.
이한결: 다인이가 DB 설계도 맡기로 했던 것 같아요. 저는 경쟁 서비스 조사 정리할게요.
박하준: 다들 좋아요?
"""


def _signup(c, name, email):
    assert c.post("/auth/register", json={"name": name, "email": email, "password": "password123"}).status_code == 201
    tok = c.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_full_flow(client):
    c = client
    a, b, d = _signup(c, "국다인", "a@x.com"), _signup(c, "박하준", "b@x.com"), _signup(c, "이한결", "c@x.com")

    # 팀 생성/참여
    team = c.post("/teams", json={"name": "소프트웨어챌린지"}, headers=a).json()
    for h in (b, d):
        assert c.post("/teams/join", json={"invite_code": team["invite_code"]}, headers=h).status_code == 200
    tid = team["id"]
    assert c.get(f"/teams/{tid}", headers=b).json()["members"][0]["role"] == "leader"

    # 외부인 접근 차단
    outsider = _signup(c, "외부인", "z@x.com")
    assert c.get(f"/teams/{tid}", headers=outsider).status_code == 403

    # 회의록 → 초안
    r = c.post(f"/teams/{tid}/meetings", json={"title": "1차 회의", "raw_text": MEETING}, headers=a)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["utterance_count"] == 4 and m["ai_source"] == "rule"
    tasks = {t["title"][:8]: t for t in m["tasks"]}
    assert len(m["tasks"]) >= 4
    assert all(t["status"] == "DRAFT" for t in m["tasks"])
    by_assignee = {t["assignee_name"] for t in m["tasks"]}
    assert {"국다인", "박하준", "이한결"} <= by_assignee

    # 확정
    assert c.post(f"/meetings/{m['id']}/confirm", headers=a).status_code == 200
    mine = c.get("/me/tasks", headers=a).json()
    assert mine and all(t["status"] == "TODO" for t in mine)
    assert any(n["kind"] == "assigned" for n in c.get("/me/notifications", headers=a).json())

    # 할 일 완료 → 칭찬 알림
    t0 = mine[0]
    assert c.patch(f"/tasks/{t0['id']}", json={"status": "DONE"}, headers=b).status_code == 403  # 남의 할 일
    assert c.patch(f"/tasks/{t0['id']}", json={"status": "DONE"}, headers=a).json()["status"] == "DONE"
    assert any(n["kind"] == "praise" for n in c.get("/me/notifications", headers=a).json())

    # 업로드(cp949 txt) 글자 수 집계
    up = c.post(f"/tasks/{t0['id']}/uploads", files={"file": ("a.txt", io.BytesIO("가나다 라마바".encode("cp949")))},
                headers=a)
    assert up.status_code == 201 and up.json()["char_count"] == 6
    assert c.post(f"/tasks/{t0['id']}/uploads", files={"file": ("a.hwp", io.BytesIO(b"x"))}, headers=a).status_code == 415

    # 기여도
    scores = c.get(f"/teams/{tid}/contributions", headers=a).json()
    assert abs(sum(s["total"] for s in scores) - 100) < 0.01
    assert scores[0]["name"] == "국다인"
    assert len(c.get(f"/teams/{tid}/contributions/history", headers=a).json()) >= 3

    # 마감 알림 (모레 이후 시점으로 가정 → overdue)
    with SessionLocal() as db:
        n = run_daily_reminders(db, today=date.today() + timedelta(days=30))
        assert n >= 1
        assert run_daily_reminders(db, today=date.today() + timedelta(days=30)) == 0  # 중복 방지

    # PDF
    pdf = c.post(f"/teams/{tid}/report", headers=b)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 2000


def test_confirm_requires_assignee(client):
    c = client
    a = _signup(c, "국다인", "a@x.com")
    tid = c.post("/teams", json={"name": "t"}, headers=a).json()["id"]
    m = c.post(f"/teams/{tid}/meetings", json={"raw_text": "국다인: 김철수가 자료조사 맡기로 했어요."}, headers=a).json()
    # 팀에 없는 사람 → 미배정 초안 → 확정 거부
    if any(t["assignee_id"] is None for t in m["tasks"]):
        assert c.post(f"/meetings/{m['id']}/confirm", headers=a).status_code == 409
