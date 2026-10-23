# ADOZ 백엔드 (FastAPI)

팀플 회의록 → AI 할 일 배정 → 기여도 측정 → PDF 리포트

## 실행
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # GEMINI_API_KEY 입력 (없으면 규칙 기반 폴백으로 동작)
uvicorn app.main:app --reload
```
- API 문서(Swagger): http://localhost:8000/docs  ← 프론트 팀원에게 이 주소 공유
- 테스트: `python -m pytest -q`

## 핵심 흐름
1. `POST /auth/register`, `POST /auth/login` → Bearer 토큰
2. `POST /teams` → 초대 코드 / 팀원은 `POST /teams/join`
3. `POST /teams/{id}/meetings` : 회의록(`이름: 내용` 줄 형식) → 요약 + 할 일 **초안**(DRAFT)
4. 초안 수정 `PATCH /tasks/{id}` → `POST /meetings/{id}/confirm` 으로 확정·배정·알림
5. `GET /me/tasks`, `PATCH /tasks/{id}` (status: TODO/DOING/DONE), `POST /tasks/{id}/uploads`
6. `GET /teams/{id}/contributions` (+ `/history`)
7. `POST /teams/{id}/report` → PDF

## 구조
```
app/
  main.py            앱/스케줄러(매일 REMINDER_HOUR시 마감 알림)
  models.py          DB 모델        schemas.py  요청/응답
  routers/           auth, teams, meetings, tasks, reports(기여도·PDF)
  services/
    ai.py            Gemini 분석(JSON 스키마 강제) + 규칙 기반 폴백 + 코멘트
    parser.py        화자 분리 / 이름 매칭 / '금요일까지' 같은 기한 파싱
    contribution.py  기여도 계산 (발언 0.3 / 할 일 0.4 / 업로드 0.3, 가중치는 .env로 조정)
    notifications.py 마스코트 멘트 + 푸시 연동 지점(send_push)
    report.py        PDF 생성 (NanumGothic 임베딩)
```

## 기여도 계산 방식
- 발언: 팀 내 발언 글자 수 비율 / 업로드: 업로드 문서 글자 수 비율
- 할 일: 난이도(1~3) 가중치 × (기한 내 완료 1.0 / 지각 0.5)의 팀 내 비율
- 데이터가 없는 항목은 가중치에서 제외 후 재정규화, 총합은 항상 100%

## 남은 작업 (TODO)
- FCM 실제 연동 (`services/notifications.send_push`)
- 음성 → 텍스트(Whisper): 회의 녹음 업로드 엔드포인트
- 운영 DB(PostgreSQL) + Alembic 마이그레이션, CORS 도메인 제한, SECRET_KEY 교체
- 업로드 파일 형식 확장(hwp 등)
