import io
from datetime import date, timedelta

MEETING = """국다인: 자료조사는 내가 금요일까지 할게요.
박하준: 발표 자료는 제가 만들게요.
"""


def _signup(c, name, email):
    assert c.post("/auth/register", json={"name": name, "email": email, "password": "password123"}).status_code == 201
    tok = c.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _team(c):
    a, b = _signup(c, "국다인", "a@x.com"), _signup(c, "박하준", "b@x.com")
    team = c.post("/teams", json={"name": "팀"}, headers=a).json()
    c.post("/teams/join", json={"invite_code": team["invite_code"]}, headers=b)
    ids = {m["name"]: m["user_id"] for m in c.get(f"/teams/{team['id']}", headers=a).json()["members"]}
    return team["id"], a, b, ids


def test_create_task(client):
    c = client
    tid, a, b, ids = _team(c)

    # 확정 전 회의록 → 초안으로 추가
    m = c.post(f"/teams/{tid}/meetings", json={"raw_text": MEETING}, headers=a).json()
    r = c.post(f"/teams/{tid}/tasks", json={"title": "AI가 놓친 일", "meeting_id": m["id"]}, headers=b)
    assert r.status_code == 201 and r.json()["status"] == "DRAFT"

    # 회의 밖 할 일: 팀원은 본인에게만, 팀장은 누구에게나 배정
    assert c.post(f"/teams/{tid}/tasks", json={"title": "x", "assignee_id": ids["국다인"]}, headers=b).status_code == 403
    assert c.post(f"/teams/{tid}/tasks", json={"title": "x"}, headers=b).status_code == 422  # 담당자 필수
    r = c.post(f"/teams/{tid}/tasks", json={"title": "디자인 수정", "assignee_id": ids["박하준"],
                                             "due_date": (date.today() + timedelta(days=3)).isoformat()}, headers=a)
    assert r.status_code == 201 and r.json()["status"] == "TODO" and r.json()["assignee_name"] == "박하준"
    assert any(n["kind"] == "assigned" for n in c.get("/me/notifications", headers=b).json())

    # 단건 조회
    assert c.get(f"/tasks/{r.json()['id']}", headers=a).json()["title"] == "디자인 수정"
    outsider = _signup(c, "외부인", "z@x.com")
    assert c.get(f"/tasks/{r.json()['id']}", headers=outsider).status_code == 403


def test_approval_flow(client):
    c = client
    tid, a, b, ids = _team(c)
    t = c.post(f"/teams/{tid}/tasks", json={"title": "보고서", "assignee_id": ids["박하준"], "difficulty": 3},
               headers=a).json()

    # 제출 → 승인 대기, 기여도엔 아직 미반영
    r = c.patch(f"/tasks/{t['id']}", json={"status": "DONE"}, headers=b).json()
    assert r["status"] == "REVIEW" and r["completed_at"]
    assert any(n["kind"] == "review" for n in c.get("/me/notifications", headers=a).json())
    score = {s["name"]: s for s in c.get(f"/teams/{tid}/contributions", headers=a).json()}
    assert score["박하준"]["tasks_done"] == 0
    # 스스로 DONE으로 넘기거나 본인 승인 불가
    assert c.patch(f"/tasks/{t['id']}", json={"status": "DONE"}, headers=b).json()["status"] == "REVIEW"
    assert c.post(f"/tasks/{t['id']}/approve", headers=b).status_code == 403

    # 반려 → DOING, 사유가 알림에 포함
    r = c.post(f"/tasks/{t['id']}/reject", json={"reason": "출처 보완"}, headers=a).json()
    assert r["status"] == "DOING" and r["completed_at"] is None
    assert any("출처 보완" in n["message"] for n in c.get("/me/notifications", headers=b).json())
    assert c.post(f"/tasks/{t['id']}/approve", headers=a).status_code == 409  # 승인 대기 아님

    # 재제출 → 승인 → 기여도 반영
    c.patch(f"/tasks/{t['id']}", json={"status": "DONE"}, headers=b)
    assert c.post(f"/tasks/{t['id']}/approve", headers=a).json()["status"] == "DONE"
    score = {s["name"]: s for s in c.get(f"/teams/{tid}/contributions", headers=a).json()}
    assert score["박하준"]["tasks_done"] == 1 and score["박하준"]["task_share"] == 1.0


def test_solo_team_completes_without_approval(client):
    c = client
    a = _signup(c, "국다인", "a@x.com")
    tid = c.post("/teams", json={"name": "혼자"}, headers=a).json()["id"]
    me = c.get("/me", headers=a).json()["id"]
    t = c.post(f"/teams/{tid}/tasks", json={"title": "x", "assignee_id": me}, headers=a).json()
    assert c.patch(f"/tasks/{t['id']}", json={"status": "DONE"}, headers=a).json()["status"] == "DONE"


def test_upload_download(client):
    c = client
    tid, a, b, ids = _team(c)
    t = c.post(f"/teams/{tid}/tasks", json={"title": "x", "assignee_id": ids["박하준"]}, headers=a).json()
    up = c.post(f"/tasks/{t['id']}/uploads", files={"file": ("조사.txt", io.BytesIO("가나다".encode()))}, headers=b).json()
    r = c.get(f"/uploads/{up['id']}/file", headers=a)
    assert r.status_code == 200 and r.content == "가나다".encode()
    assert "filename*=utf-8''" in r.headers["content-disposition"].lower()
    outsider = _signup(c, "외부인", "z@x.com")
    assert c.get(f"/uploads/{up['id']}/file", headers=outsider).status_code == 403


def test_delete_meeting(client):
    c = client
    tid, a, b, ids = _team(c)
    m1 = c.post(f"/teams/{tid}/meetings", json={"raw_text": MEETING}, headers=a).json()
    c.post(f"/meetings/{m1['id']}/confirm", headers=a)
    m2 = c.post(f"/teams/{tid}/meetings", json={"raw_text": MEETING}, headers=a).json()
    assert c.delete(f"/meetings/{m2['id']}", headers=b).status_code == 403  # 작성자/팀장 아님

    confirmed = len(c.get(f"/teams/{tid}/tasks", headers=a).json())
    assert confirmed > 0
    assert c.delete(f"/meetings/{m2['id']}", headers=a).status_code == 204  # 초안만 있던 회의 → 초안도 삭제
    assert c.delete(f"/meetings/{m1['id']}", headers=a).status_code == 204  # 확정된 할 일은 유지
    tasks = c.get(f"/teams/{tid}/tasks", headers=a).json()
    assert len(tasks) == confirmed and all(t["meeting_id"] is None for t in tasks)
    assert len(c.get(f"/teams/{tid}/tasks", params={"include_draft": True}, headers=a).json()) == confirmed
    assert c.get(f"/teams/{tid}/meetings", headers=a).json() == []
    # 발언이 사라졌으므로 발언 기여도도 0
    assert all(s["speech_chars"] == 0 for s in c.get(f"/teams/{tid}/contributions", headers=a).json())


def test_team_management(client):
    c = client
    tid, a, b, ids = _team(c)
    d = _signup(c, "이한결", "d@x.com")
    c.post("/teams/join", json={"invite_code": c.get(f"/teams/{tid}", headers=a).json()["invite_code"]}, headers=d)
    ids["이한결"] = c.get("/me", headers=d).json()["id"]

    # 팀 정보 수정은 팀장만
    assert c.patch(f"/teams/{tid}", json={"name": "새이름"}, headers=b).status_code == 403
    r = c.patch(f"/teams/{tid}", json={"name": "새이름", "deadline": "2026-12-01"}, headers=a).json()
    assert r["name"] == "새이름" and r["deadline"] == "2026-12-01"
    assert c.patch(f"/teams/{tid}", json={"clear_deadline": True}, headers=a).json()["deadline"] is None

    # 팀장은 위임 전에는 못 나감
    assert c.delete(f"/teams/{tid}/members/{ids['국다인']}", headers=a).status_code == 409
    roles = {m["name"]: m["role"] for m in c.post(f"/teams/{tid}/leader", json={"user_id": ids["박하준"]}, headers=a).json()["members"]}
    assert roles == {"국다인": "member", "박하준": "leader", "이한결": "member"}

    # 내보내기는 팀장만, 나가면 끝나지 않은 할 일은 미배정으로
    t = c.post(f"/teams/{tid}/tasks", json={"title": "x", "assignee_id": ids["이한결"]}, headers=b).json()
    assert c.delete(f"/teams/{tid}/members/{ids['이한결']}", headers=a).status_code == 403
    assert c.delete(f"/teams/{tid}/members/{ids['이한결']}", headers=b).status_code == 204
    assert c.get(f"/tasks/{t['id']}", headers=b).json()["assignee_id"] is None
    assert c.get(f"/teams/{tid}", headers=d).status_code == 403
    # 본인 나가기
    assert c.delete(f"/teams/{tid}/members/{ids['국다인']}", headers=a).status_code == 204
    assert [m["name"] for m in c.get(f"/teams/{tid}", headers=b).json()["members"]] == ["박하준"]
