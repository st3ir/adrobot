"""ORM models.

Keitaro stays the source of truth for campaigns and offers. This database only
holds what Keitaro does not give us: local accounts, an audit trail of every
mutating action, and a record of campaigns created through this tool.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AuditAction(enum.StrEnum):
    """Mutating operations worth recording."""

    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    CAMPAIGN_CREATED = "campaign_created"
    OFFER_ATTACHED = "offer_attached"
    OFFER_DETACHED = "offer_detached"
    OFFER_SHARES_UPDATED = "offer_shares_updated"
    OFFER_RESTORED = "offer_restored"
    CAMPAIGN_SYNCED = "campaign_synced"
    DRAFT_PUBLISHED = "draft_published"
    DRAFT_DISCARDED = "draft_discarded"


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class User(TimestampMixin, Base):
    """A local operator account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaigns: Mapped[list[CampaignRecord]] = relationship(back_populates="created_by")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} email={self.email!r}>"


class CampaignRecord(TimestampMixin, Base):
    """A campaign created through Adrobot, mirrored locally for history."""

    __tablename__ = "campaign_records"
    __table_args__ = (Index("ix_campaign_records_keitaro_id", "keitaro_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geo: Mapped[str] = mapped_column(String(2), nullable=False)
    offer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[User | None] = relationship(back_populates="campaigns")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<CampaignRecord keitaro_id={self.keitaro_id} name={self.name!r}>"


class AuditLogEntry(TimestampMixin, Base):
    """Append-only audit trail. Never stores secrets or raw credentials."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_action_created_at", "action", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False, length=40), nullable=False
    )
    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, native_enum=False, length=16),
        nullable=False,
        default=AuditOutcome.SUCCESS,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(320), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime]

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AuditLogEntry action={self.action.value} outcome={self.outcome.value}>"


# --------------------------------------------------------------------------
# Editor working copy
#
# The editor is a draft system: streams are fetched from Keitaro into these
# tables, edited locally, and only pushed back on an explicit publish. That is
# why offers carry both a desired state (what the operator wants) and a synced
# state (what Keitaro is believed to hold) — their difference is what makes a
# stream "unpublished".
# --------------------------------------------------------------------------
class OfferState(enum.StrEnum):
    """What the operator wants the offer to be."""

    ACTIVE = "active"
    REMOVED = "removed"


class SyncState(enum.StrEnum):
    """What Keitaro held at the last successful fetch or publish."""

    #: Added locally, Keitaro has never seen it.
    ABSENT = "absent"
    ACTIVE = "active"
    REMOVED = "removed"


class TrackedCampaign(TimestampMixin, Base):
    """A Keitaro campaign the editor has fetched at least once."""

    __tablename__ = "tracked_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    streams: Mapped[list[TrackedStream]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="TrackedStream.position",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<TrackedCampaign keitaro_id={self.keitaro_id} name={self.name!r}>"


class TrackedStream(TimestampMixin, Base):
    """A stream of a tracked campaign."""

    __tablename__ = "tracked_streams"
    __table_args__ = (
        UniqueConstraint("campaign_id", "keitaro_id", name="tracked_streams_campaign_keitaro"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    keitaro_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Only streams with ``schema=landings`` carry offers and can be edited.
    holds_offers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Display-only details for streams we do not edit.
    redirect_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    countries: Mapped[str | None] = mapped_column(String(512), nullable=True)

    campaign: Mapped[TrackedCampaign] = relationship(back_populates="streams")
    offers: Mapped[list[TrackedOffer]] = relationship(
        back_populates="stream",
        cascade="all, delete-orphan",
        order_by="TrackedOffer.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<TrackedStream keitaro_id={self.keitaro_id} name={self.name!r}>"


class TrackedOffer(TimestampMixin, Base):
    """An offer slot inside a tracked stream."""

    __tablename__ = "tracked_offers"
    __table_args__ = (
        UniqueConstraint("stream_id", "offer_id", name="tracked_offers_stream_offer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_streams.id", ondelete="CASCADE"), nullable=False
    )
    offer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    state: Mapped[OfferState] = mapped_column(
        Enum(OfferState, native_enum=False, length=16),
        nullable=False,
        default=OfferState.ACTIVE,
    )
    synced_state: Mapped[SyncState] = mapped_column(
        Enum(SyncState, native_enum=False, length=16),
        nullable=False,
        default=SyncState.ABSENT,
    )
    share: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_share: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: A pinned share survives every recalculation.
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    stream: Mapped[TrackedStream] = relationship(back_populates="offers")

    @property
    def is_active(self) -> bool:
        return self.state is OfferState.ACTIVE

    @property
    def is_dirty(self) -> bool:
        """True when the local intent differs from what Keitaro holds."""
        if self.state is OfferState.ACTIVE:
            return self.synced_state is not SyncState.ACTIVE or self.share != self.synced_share
        return self.synced_state is SyncState.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<TrackedOffer offer_id={self.offer_id} state={self.state.value}>"
