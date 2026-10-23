"""회의록 텍스트 파싱: 화자 분리, 팀원 이름 매칭, 한국어 기한 표현 → 날짜"""
import re
from datetime import date, timedelta

_LINE_RE = re.compile(r"^\s*\[?([^:：\]\n]{1,20}?)\]?\s*[:：]\s*(.+)$")
_WEEKDAYS = "월화수목금토일"
_HONORIFIC = re.compile(r"(님|씨)$")


def count_chars(text: str) -> int:
    """공백 제외 글자 수"""
    return len(re.sub(r"\s+", "", text))


def parse_utterances(raw: str) -> list[tuple[str, str]]:
    """'이름: 내용' 형식 줄을 (화자, 내용) 리스트로. 화자 없는 줄은 직전 발언에 이어붙임."""
    out: list[list[str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        # "12:30" 같은 시간 표기는 화자로 보지 않음
        if m and not m.group(1).strip().isdigit():
            out.append([m.group(1).strip(), m.group(2).strip()])
        elif out:
            out[-1][1] += " " + line.strip()
    return [(s, c) for s, c in out]


def name_aliases(full: str) -> set[str]:
    """'국다인' -> {'국다인', '다인'}"""
    full = full.strip()
    aliases = {full}
    if len(full) == 3:
        aliases.add(full[1:])
    return aliases


def match_member(name: str | None, members: dict[int, str]) -> int | None:
    """이름 문자열을 팀원 user_id로 매칭. 모호하면(여러 명) None."""
    if not name:
        return None
    n = _HONORIFIC.sub("", name.strip())
    if not n:
        return None
    for uid, full in members.items():
        if n in name_aliases(full):
            return uid
    fuzzy = [uid for uid, full in members.items() if len(n) >= 2 and (n in full or full in n)]
    return fuzzy[0] if len(fuzzy) == 1 else None


def parse_due_date(text: str, base: date) -> date | None:
    """'10월 30일', '10/30', '내일', '모레', '금요일', '다음 주 수요일' 등"""
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text) or re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            cand = date(base.year, mo, d)
        except ValueError:
            return None
        return cand if cand >= base - timedelta(days=30) else date(base.year + 1, mo, d)
    if "모레" in text:
        return base + timedelta(days=2)
    if "내일" in text:
        return base + timedelta(days=1)
    if "오늘" in text:
        return base
    m = re.search(r"(다음\s*주|이번\s*주)?\s*([월화수목금토일])요일", text)
    if m:
        idx = _WEEKDAYS.index(m.group(2))
        monday = base - timedelta(days=base.weekday())
        if m.group(1) and m.group(1).startswith("다음"):
            return monday + timedelta(days=7 + idx)
        if m.group(1):  # 이번 주
            return monday + timedelta(days=idx)
        ahead = (idx - base.weekday()) % 7 or 7
        return base + timedelta(days=ahead)
    return None
