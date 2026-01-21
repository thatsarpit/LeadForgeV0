import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="client")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    emails = relationship("UserEmail", back_populates="user", cascade="all, delete-orphan")
    slots = relationship("UserSlot", back_populates="user", cascade="all, delete-orphan")


class UserEmail(Base):
    __tablename__ = "user_emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="emails")


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assignments = relationship("UserSlot", back_populates="slot", cascade="all, delete-orphan")
    demo_codes = relationship("DemoCode", back_populates="slot", cascade="all, delete-orphan")


class UserSlot(Base):
    __tablename__ = "user_slots"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    slot_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("slots.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="slots")
    slot = relationship("Slot", back_populates="assignments")


class DemoCode(Base):
    __tablename__ = "demo_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    slot_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("slots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    slot = relationship("Slot", back_populates="demo_codes")


class Lead(Base):
    """
    Lead model - migrated from SQLite to Postgres.
    Stores captured leads from IndiaMart with full activity tracking.
    """
    __tablename__ = "leads"

    lead_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    slot_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("slots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    clicked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Store full lead data as JSONB for flexibility
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    slot_ref = relationship("Slot", foreign_keys=[slot_id])

    def __repr__(self):
        return f"<Lead(lead_id={self.lead_id!r}, slot_id={self.slot_id!r}, status={self.status!r})>"
