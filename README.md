# ADOZ 백엔드 (FastAPI)

팀플 회의록 → AI 할 일 배정 → 기여도 측정 → PDF 리포트

## 실행
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # DATABASE_URL, OPENAI_API_KEY 입력 (AI 키가 없으면 규칙 기반 폴백으로 동작)
uvicorn app.main:app --reload
```
- DB는 MySQL 8. 처음 한 번 MySQL Workbench 등에서 생성 (테이블은 서버 시작 시 자동 생성)
  ```sql
  CREATE DATABASE adoz CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
  CREATE USER 'adoz'@'localhost' IDENTIFIED BY '비밀번호';
  GRANT ALL PRIVILEGES ON adoz.* TO 'adoz'@'localhost';
  ```
- API 문서(Swagger): http://localhost:8000/docs  ← 프론트 팀원에게 이 주소 공유
- 테스트: `python -m pytest -q`

## 시연용 데모 데이터
```bash
python scripts/seed_demo.py --reset   # 서버를 끈 상태에서 실행. --reset은 기존 DB 데이터를 모두 지움
```
- 팀 1개, 팀원 4명, 최근 4주간 회의록 4개(실제 AI 분석), 할 일 진행/완료, 업로드, 기여도 타임라인 생성
- 로그인: `dain@adoz.kr`(팀장), `hajun@adoz.kr`, `seoyeon@adoz.kr`, `minjae@adoz.kr` / 비밀번호 `adoz1234!`

## 핵심 흐름
1. `POST /auth/register`, `POST /auth/login` → Bearer 토큰
2. `POST /teams` → 초대 코드 / 팀원은 `POST /teams/join`
3. `POST /teams/{id}/meetings` : 회의록(`이름: 내용` 줄 형식) → 요약 + 할 일 **초안**(DRAFT)
4. 초안 수정 `PATCH /tasks/{id}` (AI가 놓친 일은 `POST /teams/{id}/tasks` + `meeting_id`로 초안 추가)
   → `POST /meetings/{id}/confirm` 으로 확정·배정·알림
5. `GET /me/tasks`, `PATCH /tasks/{id}` (status: TODO/DOING/DONE), `POST /tasks/{id}/uploads`
6. **완료 승인**: 담당자가 DONE으로 바꾸면 `REVIEW`(승인 대기) → 다른 팀원이 `POST /tasks/{id}/approve` 해야 DONE·기여도 반영
   (`POST /tasks/{id}/reject` + `{"reason"}` 은 DOING으로 되돌림). 마감 준수는 제출 시각 기준, 1인 팀은 바로 DONE
7. `GET /teams/{id}/contributions` (+ `/history`, 시각은 UTC)
8. `POST /teams/{id}/report` → PDF

## 그 밖의 API
- 할 일: `POST /teams/{id}/tasks`(회의 밖 할 일 추가, 팀원은 본인에게만·팀장은 누구에게나), `GET /tasks/{id}`, `DELETE /tasks/{id}`
- 자료: `GET /tasks/{id}/uploads`, `GET /uploads/{id}/file`(원본 다운로드)
- 회의록: `DELETE /meetings/{id}`(작성자·팀장, 초안은 함께 삭제되고 확정된 할 일은 유지)
- 팀: `PATCH /teams/{id}`(이름·마감일, 팀장), `POST /teams/{id}/leader`(팀장 위임),
  `DELETE /teams/{id}/members/{user_id}`(나가기·내보내기, 끝나지 않은 할 일은 미배정으로)

## 구조
```
app/
  main.py            앱/스케줄러(매일 REMINDER_HOUR시 마감 알림)
  models.py          DB 모델        schemas.py  요청/응답
  routers/           auth, teams, meetings, tasks, reports(기여도·PDF)
  services/
    ai.py            OpenAI 분석(JSON 스키마 강제) + 규칙 기반 폴백 + 코멘트
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
- Alembic 마이그레이션(현재는 create_all로 테이블 자동 생성), CORS 도메인 제한, SECRET_KEY 교체
- 업로드 파일 형식 확장(hwp 등)
