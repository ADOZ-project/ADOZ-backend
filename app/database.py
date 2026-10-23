from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

if settings.database_url.startswith("sqlite"):  # 테스트·간단 실행용
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:  # MySQL: 오래 쉬면 서버가 연결을 끊으므로(wait_timeout) 사용 전 확인 + 주기적 재연결
    engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
