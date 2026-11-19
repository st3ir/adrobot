"""The editor's draft model.

Streams are fetched from Keitaro into local tables, edited there, and pushed
back only on an explicit publish. Each offer therefore carries two states: what
the operator wants (``state``) and what Keitaro is believed to hold
(``synced_state``). Their difference is what marks a stream as unpublished.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    CampaignNotTrackedError,
    NoOfferStreamError,
    NothingToPublishError,
    OfferAlreadyAttachedError,
    OfferNotAttachedError,
    PinnedSharesExceededError,
)
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    OfferState,
    SyncState,
    TrackedCampaign,
    TrackedOffer,
    TrackedStream,
)
from app.keitaro import builders
from app.keitaro.models import Offer, Stream
from app.keitaro.protocols import CampaignReader, StreamWriter
from app.services.catalog import CatalogService
from app.services.stats import CampaignStats, DateRange, Metrics, StatsService

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DraftOffer:
    offer_id: int
    name: str
    share: int
    synced_share: int
    pinned: bool
    state: OfferState
    synced_state: SyncState
    is_dirty: bool
    url: str | None
    metrics: Metrics

    @property
    def is_removed(self) -> bool:
        return self.state is OfferState.REMOVED


@dataclass(frozen=True, slots=True)
class DraftStream:
    keitaro_id: int
    name: str
    schema_name: str | None
    position: int
    state: str | None
    holds_offers: bool
    redirect_url: str | None
    countries: tuple[str, ...]
    offers: tuple[DraftOffer, ...]
    is_dirty: bool


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    campaign_id: int
    name: str
    alias: str | None
    last_synced_at: datetime | None
    streams: tuple[DraftStream, ...]
    stats: CampaignStats
    period: DateRange

    @property
    def is_dirty(self) -> bool:
        return any(stream.is_dirty for stream in self.streams)


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------
class CampaignDraftService:
    """Fetch, edit and publish the offers of a Keitaro campaign."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        campaigns: CampaignReader,
        streams: StreamWriter,
        catalog: CatalogService,
        stats: StatsService,
    ) -> None:
        self._session = session
        self._campaigns = campaigns
        self._streams = streams
        self._catalog = catalog
        self._stats = stats

    # -- fetch -------------------------------------------------------------
    async def sync(self, campaign_id: int) -> None:
        """Pull the campaign from Keitaro into the working copy.

        Offers the working copy knows about but Keitaro no longer has are
        archived rather than dropped, so they can be brought back. Local
        changes that were never published survive the fetch.
        """
        campaign = await self._campaigns.get_campaign(campaign_id)
        remote_streams = await self._campaigns.list_streams(campaign_id)

        tracked = await self._find(campaign_id)
        if tracked is None:
            # The empty collection is passed explicitly: without it SQLAlchemy
            # would try to lazy-load it later, which async sessions forbid.
            tracked = TrackedCampaign(
                keitaro_id=campaign.id, name=campaign.name, streams=[]
            )
            self._session.add(tracked)
        tracked.name = campaign.name
        tracked.alias = campaign.alias
        tracked.last_synced_at = utcnow()

        local_streams = {stream.keitaro_id: stream for stream in tracked.streams}
        seen: set[int] = set()

        for remote in sorted(remote_streams, key=lambda s: (s.position or 0, s.id)):
            seen.add(remote.id)
            stream = local_streams.get(remote.id)
            if stream is None:
                stream = TrackedStream(keitaro_id=remote.id, name="", offers=[])
                tracked.streams.append(stream)
            self._update_stream_fields(stream, remote)
            if stream.holds_offers:
                self._reconcile_offers(stream, remote)
            else:
                # Streams without offers are tracked, but their contents are
                # not the editor's business.
                stream.offers.clear()

        for stream in list(tracked.streams):
            if stream.keitaro_id not in seen:
                tracked.streams.remove(stream)

        await self._session.flush()
        await self._refresh_offer_names(tracked)

    @staticmethod
    def _update_stream_fields(stream: TrackedStream, remote: Stream) -> None:
        stream.name = remote.name or f"Stream #{remote.id}"
        stream.schema_name = remote.schema_
        stream.position = remote.position or 0
        stream.state = remote.state
        stream.holds_offers = remote.holds_offers
        stream.redirect_url = remote.action_payload or None
        stream.countries = ",".join(_countries_of(remote)) or None

    @staticmethod
    def _reconcile_offers(stream: TrackedStream, remote: Stream) -> None:
        remote_shares = {slot.offer_id: slot.share for slot in remote.active_offers}
        local = {offer.offer_id: offer for offer in stream.offers}

        for offer_id, share in remote_shares.items():
            row = local.get(offer_id)
            if row is None:
                stream.offers.append(
                    TrackedOffer(
                        offer_id=offer_id,
                        state=OfferState.ACTIVE,
                        synced_state=SyncState.ACTIVE,
                        share=share,
                        synced_share=share,
                    )
                )
                continue
            # An offer with no local edits simply follows Keitaro; one with a
            # staged change keeps the operator's intent until it is published.
            was_clean = not row.is_dirty
            row.synced_state = SyncState.ACTIVE
            row.synced_share = share
            if was_clean:
                row.state = OfferState.ACTIVE
                row.share = share

        for row in stream.offers:
            if row.offer_id in remote_shares:
                continue
            if row.synced_state is SyncState.ACTIVE:
                # Removed in Keitaro behind our back: archive, do not drop.
                row.synced_state = SyncState.REMOVED
                row.state = OfferState.REMOVED
                row.share = 0

    # -- read --------------------------------------------------------------
    async def load(self, campaign_id: int, period: DateRange) -> CampaignDraft:
        tracked = await self._require(campaign_id)
        stats = await self._stats.campaign_stats(campaign_id, period)
        catalog = await self._catalog.get_offers_by_ids(
            [offer.offer_id for stream in tracked.streams for offer in stream.offers]
        )

        streams = tuple(
            self._to_draft_stream(stream, catalog, stats)
            for stream in sorted(tracked.streams, key=lambda s: (s.position, s.keitaro_id))
        )

        return CampaignDraft(
            campaign_id=tracked.keitaro_id,
            name=tracked.name,
            alias=tracked.alias,
            last_synced_at=tracked.last_synced_at,
            streams=streams,
            stats=stats,
            period=period,
        )

    @classmethod
    def _to_draft_stream(
        cls,
        stream: TrackedStream,
        catalog: dict[int, Offer],
        stats: CampaignStats,
    ) -> DraftStream:
        return DraftStream(
            keitaro_id=stream.keitaro_id,
            name=stream.name,
            schema_name=stream.schema_name,
            position=stream.position,
            state=stream.state,
            holds_offers=stream.holds_offers,
            redirect_url=stream.redirect_url,
            countries=tuple(stream.countries.split(",")) if stream.countries else (),
            offers=tuple(cls._to_draft_offer(offer, catalog, stats) for offer in stream.offers),
            is_dirty=any(offer.is_dirty for offer in stream.offers),
        )

    @staticmethod
    def _to_draft_offer(
        offer: TrackedOffer,
        catalog: dict[int, Offer],
        stats: CampaignStats,
    ) -> DraftOffer:
        known = catalog.get(offer.offer_id)
        return DraftOffer(
            offer_id=offer.offer_id,
            name=offer.name or (known.name if known else f"Offer #{offer.offer_id}"),
            share=offer.share,
            synced_share=offer.synced_share,
            pinned=offer.pinned,
            state=offer.state,
            synced_state=offer.synced_state,
            is_dirty=offer.is_dirty,
            url=known.action_payload if known else None,
            metrics=stats.per_offer.get(offer.offer_id, Metrics()),
        )

    async def is_tracked(self, campaign_id: int) -> bool:
        return await self._find(campaign_id) is not None

    # -- edit --------------------------------------------------------------
    async def add_offer(self, campaign_id: int, offer_id: int) -> None:
        """Stage an offer. Nothing reaches Keitaro until publish."""
        offer = await self._catalog.get_offer(offer_id)
        tracked = await self._require(campaign_id)
        stream = self._primary_offer_stream(tracked)

        existing = next((row for row in stream.offers if row.offer_id == offer.id), None)
        if existing is None:
            stream.offers.append(
                TrackedOffer(
                    offer_id=offer.id,
                    name=offer.name,
                    state=OfferState.ACTIVE,
                    synced_state=SyncState.ABSENT,
                )
            )
        elif existing.state is OfferState.ACTIVE:
            raise OfferAlreadyAttachedError
        else:
            existing.state = OfferState.ACTIVE
            existing.name = offer.name

        await self._session.flush()
        self._rebalance(stream)

    async def remove_offer(self, campaign_id: int, offer_id: int) -> None:
        """Mark an offer removed. It stays in the archive until brought back."""
        tracked = await self._require(campaign_id)
        stream, row = self._locate(tracked, offer_id)
        if row.state is OfferState.REMOVED:
            raise OfferNotAttachedError
        row.state = OfferState.REMOVED
        row.share = 0
        row.pinned = False
        self._rebalance(stream)

    async def restore_offer(self, campaign_id: int, offer_id: int) -> None:
        """Bring an archived offer back into the rotation."""
        tracked = await self._require(campaign_id)
        stream, row = self._locate(tracked, offer_id)
        if row.state is OfferState.ACTIVE:
            raise OfferAlreadyAttachedError
        row.state = OfferState.ACTIVE
        self._rebalance(stream)

    async def set_pin(
        self, campaign_id: int, offer_id: int, *, pinned: bool, share: int | None = None
    ) -> None:
        """Pin (or release) an offer's share.

        A pinned share survives every later recalculation; the floating offers
        split whatever is left.
        """
        tracked = await self._require(campaign_id)
        stream, row = self._locate(tracked, offer_id)
        if row.state is OfferState.REMOVED:
            raise OfferNotAttachedError
        row.pinned = pinned
        if pinned and share is not None:
            row.share = share
        self._rebalance(stream)

    # -- publish / discard -------------------------------------------------
    async def publish(self, campaign_id: int) -> list[int]:
        """Push every unpublished stream to Keitaro. Returns their ids."""
        tracked = await self._require(campaign_id)
        dirty = [
            stream
            for stream in tracked.streams
            if stream.holds_offers and any(offer.is_dirty for offer in stream.offers)
        ]
        if not dirty:
            raise NothingToPublishError

        published: list[int] = []
        for stream in dirty:
            payload = [
                {
                    "offer_id": offer.offer_id,
                    "share": offer.share,
                    "state": builders.STATE_ACTIVE,
                }
                for offer in stream.offers
                if offer.state is OfferState.ACTIVE
            ]
            await self._streams.update_stream(stream.keitaro_id, {"offers": payload})
            for offer in stream.offers:
                offer.synced_share = offer.share
                offer.synced_state = (
                    SyncState.ACTIVE if offer.state is OfferState.ACTIVE else SyncState.REMOVED
                )
            published.append(stream.keitaro_id)
            logger.info(
                "Published stream %s of campaign %s (%s offers)",
                stream.keitaro_id,
                campaign_id,
                len(payload),
            )
        return published

    async def discard(self, campaign_id: int) -> None:
        """Drop unpublished changes and return to the last known Keitaro state."""
        tracked = await self._require(campaign_id)
        for stream in tracked.streams:
            for row in list(stream.offers):
                if row.synced_state is SyncState.ABSENT:
                    stream.offers.remove(row)
                    continue
                row.state = (
                    OfferState.ACTIVE
                    if row.synced_state is SyncState.ACTIVE
                    else OfferState.REMOVED
                )
                row.share = row.synced_share

    # -- helpers -----------------------------------------------------------
    async def _find(self, campaign_id: int) -> TrackedCampaign | None:
        statement = (
            select(TrackedCampaign)
            .where(TrackedCampaign.keitaro_id == campaign_id)
            .options(selectinload(TrackedCampaign.streams).selectinload(TrackedStream.offers))
        )
        return await self._session.scalar(statement)

    async def _require(self, campaign_id: int) -> TrackedCampaign:
        tracked = await self._find(campaign_id)
        if tracked is None:
            raise CampaignNotTrackedError
        return tracked

    @staticmethod
    def _primary_offer_stream(tracked: TrackedCampaign) -> TrackedStream:
        for stream in sorted(tracked.streams, key=lambda s: (s.position, s.keitaro_id)):
            if stream.holds_offers:
                return stream
        raise NoOfferStreamError

    @staticmethod
    def _locate(tracked: TrackedCampaign, offer_id: int) -> tuple[TrackedStream, TrackedOffer]:
        for stream in sorted(tracked.streams, key=lambda s: (s.position, s.keitaro_id)):
            for row in stream.offers:
                if row.offer_id == offer_id:
                    return stream, row
        raise OfferNotAttachedError

    @staticmethod
    def _rebalance(stream: TrackedStream) -> None:
        """Recalculate shares so the active offers always sum to 100%."""
        active = [offer for offer in stream.offers if offer.state is OfferState.ACTIVE]
        for offer in stream.offers:
            if offer.state is OfferState.REMOVED:
                offer.share = 0
        if not active:
            return
        pins = [offer.share if offer.pinned else None for offer in active]
        try:
            shares = builders.distribute_with_pins(pins)
        except ValueError as exc:
            raise PinnedSharesExceededError from exc
        for offer, share in zip(active, shares, strict=True):
            offer.share = share

    async def _refresh_offer_names(self, tracked: TrackedCampaign) -> None:
        """Cache offer names so the UI can render an archived offer too."""
        ids = [offer.offer_id for stream in tracked.streams for offer in stream.offers]
        if not ids:
            return
        catalog = await self._catalog.get_offers_by_ids(ids)
        for stream in tracked.streams:
            for offer in stream.offers:
                found = catalog.get(offer.offer_id)
                if found is not None:
                    offer.name = found.name


def _countries_of(stream: Stream) -> tuple[str, ...]:
    for stream_filter in stream.filters:
        if stream_filter.name != builders.FILTER_COUNTRY:
            continue
        payload = stream_filter.payload
        if isinstance(payload, list):
            return tuple(str(item).upper() for item in payload)
        if isinstance(payload, str):
            return tuple(part.strip().upper() for part in payload.split(",") if part.strip())
    return ()
