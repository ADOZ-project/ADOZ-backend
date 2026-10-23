from datetime import date

from app.services.parser import match_member, parse_due_date, parse_utterances

BASE = date(2026, 10, 21)  # 수요일


def test_parse_utterances():
    raw = "하준: 안녕하세요\n이어지는 말\n12:30 점심\n제우: 네"
    assert parse_utterances(raw) == [("하준", "안녕하세요 이어지는 말 12:30 점심"), ("제우", "네")]


def test_due_dates():
    assert parse_due_date("10월 30일까지", BASE) == date(2026, 10, 30)
    assert parse_due_date("금요일까지", BASE) == date(2026, 10, 23)
    assert parse_due_date("수요일까지", BASE) == date(2026, 10, 28)  # 오늘이 수요일이면 다음 주
    assert parse_due_date("다음 주 수요일", BASE) == date(2026, 10, 28)
    assert parse_due_date("이번 주 금요일", BASE) == date(2026, 10, 23)
    assert parse_due_date("내일", BASE) == date(2026, 10, 22)
    assert parse_due_date("언젠가", BASE) is None


def test_match_member():
    m = {1: "국다인", 2: "박하준", 3: "이제우"}
    assert match_member("다인", m) == 1
    assert match_member("하준님", m) == 2
    assert match_member("제우", m) == 3
    assert match_member("김철수", m) is None
