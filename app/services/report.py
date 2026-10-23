"""원클릭 공정 기여도 리포트 PDF 생성 (reportlab)"""
import os
from io import BytesIO

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DONE, DRAFT, ContributionSnapshot, Meeting, Task, Team
from ..timeutil import KST, to_kst_date, today_kst
from . import ai
from .contribution import compute_scores

_FONT: str | None = None


def _font() -> str:
    """fonts/NanumGothic(또는 FONT_PATH)를 임베딩. 파일이 없을 때만 내장 CID 폰트로 폴백(뷰어에 한글 폰트 필요)"""
    global _FONT
    if _FONT:
        return _FONT
    path = settings.font_path or os.path.join(os.path.dirname(__file__), "..", "..", "fonts", "NanumGothic-Regular.ttf")
    if os.path.exists(path):
        pdfmetrics.registerFont(TTFont("KR", path))  # 서브셋으로 PDF에 임베딩 → 어떤 뷰어에서도 한글 표시
        _FONT = "KR"
    else:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        _FONT = "HYSMyeongJo-Medium"
    return _FONT


def _p(text: str, size=10, bold_color=None, leading=None) -> Paragraph:
    st = ParagraphStyle("p", fontName=_font(), fontSize=size, leading=leading or size * 1.5, wordWrap="CJK",
                        textColor=bold_color or colors.black)
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), st)


def _bar_chart(scores) -> Drawing:
    d = Drawing(480, 210)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 40, 40, 410, 140
    bc.data = [[round(s.speech_share * 100, 1) for s in scores],
               [round(s.task_share * 100, 1) for s in scores],
               [round(s.upload_share * 100, 1) for s in scores],
               [round(s.total, 1) for s in scores]]
    bc.categoryAxis.categoryNames = [s.name for s in scores]
    bc.categoryAxis.labels.fontName = _font()
    bc.valueAxis.valueMin, bc.valueAxis.valueMax, bc.valueAxis.valueStep = 0, 100, 20
    bc.valueAxis.labels.fontName = _font()
    for i, c in enumerate(["#9BB7E0", "#F2B880", "#9ED3A5", "#3F5FA8"]):
        bc.bars[i].fillColor = colors.HexColor(c)
    d.add(bc)
    legend = ["발언 비중", "할 일 수행", "자료 작성", "종합"]
    for i, (txt, c) in enumerate(zip(legend, ["#9BB7E0", "#F2B880", "#9ED3A5", "#3F5FA8"])):
        x = 60 + i * 100
        from reportlab.graphics.shapes import Rect

        d.add(Rect(x, 195, 8, 8, fillColor=colors.HexColor(c), strokeColor=None))
        d.add(String(x + 12, 195, txt, fontName=_font(), fontSize=8))
    return d


def build_report(db: Session, team_id: int) -> bytes:
    team = db.get(Team, team_id)
    scores = sorted(compute_scores(db, team_id), key=lambda s: -s.total)
    comments = ai.generate_comments(team.name, scores)
    meetings = db.scalars(select(Meeting).where(Meeting.team_id == team_id).order_by(Meeting.meeting_date)).all()
    tasks = db.scalars(select(Task).where(Task.team_id == team_id, Task.status != DRAFT)).all()
    names = {s.user_id: s.name for s in scores}
    snaps = db.scalars(
        select(ContributionSnapshot).where(ContributionSnapshot.team_id == team_id).order_by(ContributionSnapshot.calculated_at)
    ).all()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{team.name} 기여도 리포트")
    story = [
        _p("ADOZ 팀플 공정 기여도 리포트", 18, colors.HexColor("#3F5FA8")),
        Spacer(1, 3 * mm),
        _p(f"팀명: {team.name}   |   생성일: {today_kst().isoformat()}   |   팀원 {len(scores)}명", 10),
        Spacer(1, 6 * mm),
        _p("1. 팀원별 종합 기여도", 13),
        Spacer(1, 2 * mm),
    ]

    head = ["이름", "종합(%)", "발언(%)", "할 일(%)", "자료(%)", "마감준수", "성향"]
    rows = [[_p(h, 9) for h in head]]
    for s in scores:
        rate = "-" if s.on_time_rate is None else f"{s.on_time_rate * 100:.0f}%"
        rows.append([_p(x, 9) for x in [s.name, f"{s.total:.1f}", f"{s.speech_share * 100:.1f}",
                                          f"{s.task_share * 100:.1f}", f"{s.upload_share * 100:.1f}", rate,
                                          s.persona]])
    t = Table(rows, colWidths=[22 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 52 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF8")),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B8C8")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 5 * mm), _bar_chart(scores), Spacer(1, 4 * mm)]

    story += [_p("2. 역할별 달성률 및 AI 코멘트", 13), Spacer(1, 2 * mm)]
    for s in scores:
        story.append(_p(f"<{s.name}> 완료 {s.tasks_done}/{s.tasks_assigned}건 · {comments.get(s.user_id, '')}", 10))
        story.append(Spacer(1, 1.5 * mm))

    story += [Spacer(1, 3 * mm), _p("3. 회의록 요약", 13), Spacer(1, 2 * mm)]
    for m in meetings:
        story.append(_p(f"[{m.meeting_date.isoformat()}] {m.title}", 10, colors.HexColor("#3F5FA8")))
        story.append(_p(m.summary or "(요약 없음)", 9.5))
        story.append(Spacer(1, 2 * mm))
    if not meetings:
        story.append(_p("등록된 회의록이 없습니다.", 10))

    story += [Spacer(1, 3 * mm), _p("4. 주요 작업 기록 타임라인", 13), Spacer(1, 2 * mm)]
    events = []
    for tk in tasks:
        who = names.get(tk.assignee_id, "미배정")
        if tk.status == DONE and tk.completed_at:
            d = to_kst_date(tk.completed_at)
            late = tk.due_date and d > tk.due_date
            events.append((d, f"{who} - '{tk.title[:60]}' 완료" + (" (기한 초과)" if late else " (기한 내)")))
        elif tk.due_date:
            events.append((tk.due_date, f"{who} - '{tk.title[:60]}' 마감 예정/진행 중 ({tk.status})"))
    for d, txt in sorted(events, key=lambda e: e[0]):
        story.append(_p(f"{d.isoformat()}  {txt}", 9))
    if not events:
        story.append(_p("기록된 작업이 없습니다.", 10))

    if snaps:
        story += [Spacer(1, 4 * mm), _p("5. 기여도 변화 이력", 13), Spacer(1, 2 * mm)]
        by_time: dict = {}
        for sn in snaps:
            key = sn.calculated_at.replace(tzinfo=None).replace(microsecond=0)
            by_time.setdefault(key, {})[sn.user_id] = sn.total
        keys = sorted(by_time)
        if len(keys) > 8:  # 너무 길면 균등 샘플링
            keys = [keys[round(i * (len(keys) - 1) / 7)] for i in range(8)]
        for k in keys:
            vals = ", ".join(f"{names.get(u, u)} {v:.0f}%" for u, v in by_time[k].items())
            story.append(_p(f"{k.strftime('%Y-%m-%d %H:%M')} (UTC)  {vals}", 8.5))

    story += [Spacer(1, 6 * mm),
              _p("※ 본 리포트는 활동 로그(회의 발언량, 할 일 수행·마감 준수, 업로드 자료 분량)를 기반으로 자동 생성되었으며, "
                 "정성적 기여(아이디어 품질 등)는 반영되지 않을 수 있습니다.", 8, colors.grey)]
    doc.build(story)
    return buf.getvalue()
