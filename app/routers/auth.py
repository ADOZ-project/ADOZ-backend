from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Notification, User
from ..schemas import FcmTokenIn, LoginIn, NotificationOut, TokenOut, UserCreate, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "이미 가입된 이메일입니다")
    user = User(name=body.name.strip(), email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return user


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.put("/me/fcm-token", status_code=204)
def set_fcm_token(body: FcmTokenIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.fcm_token = body.token
    db.add(user)
    db.commit()


@router.get("/me/notifications", response_model=list[NotificationOut])
def my_notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(100)
    if unread_only:
        q = q.where(Notification.is_read.is_(False))
    return db.scalars(q).all()


@router.post("/me/notifications/read", status_code=204)
def mark_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))):
        n.is_read = True
    db.commit()
