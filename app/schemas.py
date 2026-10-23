from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    name: str
    email: EmailStr


class FcmTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=512)


# ---- team
class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    deadline: date | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    deadline: date | None = None
    clear_deadline: bool = False


class LeaderIn(BaseModel):
    user_id: int


class JoinIn(BaseModel):
    invite_code: str


class MemberOut(BaseModel):
    user_id: int
    name: str
    role: str


class TeamOut(BaseModel):
    id: int
    name: str
    invite_code: str
    deadline: date | None
    members: list[MemberOut] = []


# ---- task
class TaskOut(ORM):
    id: int
    team_id: int
    meeting_id: int | None
    assignee_id: int | None
    assignee_name: str | None
    assignee_name_raw: str | None
    title: str
    due_date: date | None
    difficulty: int
    status: str
    completed_at: datetime | None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    assignee_id: int | None = None
    due_date: date | None = None
    difficulty: int = Field(default=2, ge=1, le=3)
    meeting_id: int | None = None  # 확정 전 회의록이면 그 회의의 초안(DRAFT)으로 추가


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    due_date: date | None = None
    difficulty: int | None = Field(default=None, ge=1, le=3)
    assignee_id: int | None = None
    status: str | None = None
    clear_due_date: bool = False  # due_date를 null로 비우고 싶을 때


class UploadOut(ORM):
    id: int
    task_id: int
    user_id: int
    filename: str
    char_count: int
    created_at: datetime


# ---- meeting
class MeetingCreate(BaseModel):
    title: str = Field(default="팀 회의", max_length=200)
    raw_text: str = Field(min_length=10, max_length=60000)
    meeting_date: date | None = None


class MeetingBrief(ORM):
    id: int
    title: str
    meeting_date: date
    confirmed: bool
    ai_source: str


class MeetingOut(MeetingBrief):
    team_id: int
    summary: str
    utterance_count: int
    tasks: list[TaskOut]


# ---- contribution / notification
class ScoreOut(BaseModel):
    user_id: int
    name: str
    total: float
    speech_share: float
    task_share: float
    upload_share: float
    speech_chars: int
    upload_chars: int
    tasks_assigned: int
    tasks_done: int
    on_time_rate: float | None
    persona: str


class NotificationOut(ORM):
    id: int
    task_id: int | None
    kind: str
    message: str
    is_read: bool
    created_at: datetime
