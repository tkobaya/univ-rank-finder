from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import DB_PATH


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.utcnow()


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class University(Base):
    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ror_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    acronyms: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    country: Mapped[str | None] = mapped_column(String(255), index=True)
    country_code: Mapped[str | None] = mapped_column(String(16), index=True)
    region: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(512))
    wikipedia_url: Mapped[str | None] = mapped_column(String(512))
    types: Mapped[list] = mapped_column(JSON, default=list)
    ror_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    rankings: Mapped[list["Ranking"]] = relationship(back_populates="university")


class Ranking(Base):
    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(8), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    rank: Mapped[int | None] = mapped_column(Integer, index=True)
    rank_display: Mapped[str] = mapped_column(String(32))
    score: Mapped[str | None] = mapped_column(String(32))
    org_name: Mapped[str] = mapped_column(String(512), index=True)
    country: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(512))
    region: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    match_status: Mapped[str] = mapped_column(String(16), default="unmatched", index=True)
    university_id: Mapped[int | None] = mapped_column(
        ForeignKey("universities.id"), index=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    university: Mapped[University | None] = relationship(back_populates="rankings")


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("name", "version", "year", name="uq_source_version_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(8), index=True)  # ror / qs / the
    version: Mapped[str] = mapped_column(String(64))  # e.g. v2.11-2026-08-03, QS2027, THE2026
    year: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[str | None] = mapped_column(String(32))  # データが基準とする日付/公開日
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(String(512))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
