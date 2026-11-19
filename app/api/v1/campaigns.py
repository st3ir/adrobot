"""Campaign creation and offer editing endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status

from app.api import mappers
from app.api.deps import (
    AuditDep,
    AuthorizedUser,
    CatalogDep,
    ClientIp,
    ContainerDep,
    CurrentUser,
    DraftDep,
    SessionDep,
)
from app.core.logging import get_logger
from app.db.models import AuditAction, CampaignRecord, User
from app.schemas.campaigns import (
    CampaignCreateRequest,
    CampaignCreateResponse,
    CampaignDraftResponse,
    CampaignSummaryOut,
    OfferAttachRequest,
    PinRequest,
)
from app.services.audit import AuditService
from app.services.campaign_creator import CampaignCreateCommand
from app.services.stats import DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, DateRange

logger = get_logger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])

CampaignId = Annotated[int, Path(gt=0, le=2_147_483_647)]
OfferId = Annotated[int, Path(gt=0, le=2_147_483_647)]
LookbackDays = Annotated[int, Query(ge=1, le=MAX_LOOKBACK_DAYS)]


@router.post("", response_model=CampaignCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    container: ContainerDep,
    session: SessionDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
) -> CampaignCreateResponse:
    """Create a campaign with a geo redirect stream and an offer stream."""
    result = await container.creator.create(
        CampaignCreateCommand(
            name=payload.name,
            geo=payload.geo,
            offer_id=payload.offer_id,
            domain_id=payload.domain_id,
            group_id=payload.group_id,
            source_id=payload.source_id,
        )
    )

    session.add(
        CampaignRecord(
            keitaro_id=result.campaign.id,
            name=result.campaign.name,
            alias=result.campaign.alias,
            geo=payload.geo,
            offer_id=payload.offer_id,
            domain_id=result.defaults.domain_id,
            group_id=result.defaults.group_id,
            source_id=result.defaults.source_id,
            created_by_id=user.id,
        )
    )
    await audit.record(
        AuditAction.CAMPAIGN_CREATED,
        user_id=user.id,
        actor_label=user.email,
        target_type="campaign",
        target_id=result.campaign.id,
        client_ip=client_ip,
        context={
            "name": result.campaign.name,
            "geo": payload.geo,
            "offer_id": payload.offer_id,
            "domain_id": result.defaults.domain_id,
            "group_id": result.defaults.group_id,
            "source_id": result.defaults.source_id,
        },
    )
    # The new campaign must be findable in the editor immediately.
    container.catalog.invalidate()
    return mappers.create_response(
        result, geo=payload.geo, redirect_url=container.settings.geo_redirect_url
    )


@router.get("", response_model=list[CampaignSummaryOut])
async def list_campaigns(
    catalog: CatalogDep,
    _: CurrentUser,
    q: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CampaignSummaryOut]:
    """List Keitaro campaigns, optionally filtered by name or id."""
    campaigns = await catalog.search_campaigns(q, limit=limit)
    return [mappers.campaign_summary(campaign) for campaign in campaigns]


# --------------------------------------------------------------------------
# Editor: the campaign is fetched into a local draft, edited there, and pushed
# back to Keitaro only on an explicit publish.
# --------------------------------------------------------------------------
@router.post("/{campaign_id}/fetch", response_model=CampaignDraftResponse)
async def fetch_campaign(
    campaign_id: CampaignId,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Pull the campaign's streams from Keitaro into the working copy."""
    await draft.sync(campaign_id)
    await audit.record(
        AuditAction.CAMPAIGN_SYNCED,
        user_id=user.id,
        actor_label=user.email,
        target_type="campaign",
        target_id=campaign_id,
        client_ip=client_ip,
    )
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.get("/{campaign_id}/draft", response_model=CampaignDraftResponse)
async def campaign_draft(
    campaign_id: CampaignId,
    draft: DraftDep,
    _: CurrentUser,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """The local working copy. 404 until the campaign has been fetched."""
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.post("/{campaign_id}/offers", response_model=CampaignDraftResponse)
async def add_offer(
    campaign_id: CampaignId,
    payload: OfferAttachRequest,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Stage an offer. Keitaro is untouched until publish."""
    await draft.add_offer(campaign_id, payload.offer_id)
    await _record(audit, AuditAction.OFFER_ATTACHED, user, client_ip, campaign_id,
                  {"offer_id": payload.offer_id})
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.delete("/{campaign_id}/offers/{offer_id}", response_model=CampaignDraftResponse)
async def remove_offer(
    campaign_id: CampaignId,
    offer_id: OfferId,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Mark an offer removed. It stays in the archive and can be brought back."""
    await draft.remove_offer(campaign_id, offer_id)
    await _record(audit, AuditAction.OFFER_DETACHED, user, client_ip, campaign_id,
                  {"offer_id": offer_id})
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.post("/{campaign_id}/offers/{offer_id}/restore", response_model=CampaignDraftResponse)
async def restore_offer(
    campaign_id: CampaignId,
    offer_id: OfferId,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Bring an archived offer back into the rotation."""
    await draft.restore_offer(campaign_id, offer_id)
    await _record(audit, AuditAction.OFFER_RESTORED, user, client_ip, campaign_id,
                  {"offer_id": offer_id})
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.put("/{campaign_id}/offers/{offer_id}/pin", response_model=CampaignDraftResponse)
async def pin_offer(
    campaign_id: CampaignId,
    offer_id: OfferId,
    payload: PinRequest,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Pin or release an offer's share."""
    await draft.set_pin(campaign_id, offer_id, pinned=payload.pinned, share=payload.share)
    await _record(audit, AuditAction.OFFER_SHARES_UPDATED, user, client_ip, campaign_id,
                  {"offer_id": offer_id, "pinned": payload.pinned, "share": payload.share})
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.post("/{campaign_id}/publish", response_model=CampaignDraftResponse)
async def publish_draft(
    campaign_id: CampaignId,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Push every unpublished stream of the campaign to Keitaro."""
    published = await draft.publish(campaign_id)
    await _record(audit, AuditAction.DRAFT_PUBLISHED, user, client_ip, campaign_id,
                  {"streams": published})
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


@router.post("/{campaign_id}/discard", response_model=CampaignDraftResponse)
async def discard_draft(
    campaign_id: CampaignId,
    draft: DraftDep,
    audit: AuditDep,
    user: AuthorizedUser,
    client_ip: ClientIp,
    days: LookbackDays = DEFAULT_LOOKBACK_DAYS,
) -> CampaignDraftResponse:
    """Drop unpublished changes and go back to the last known Keitaro state."""
    await draft.discard(campaign_id)
    await _record(audit, AuditAction.DRAFT_DISCARDED, user, client_ip, campaign_id, None)
    return mappers.draft_out(await draft.load(campaign_id, DateRange.last_days(days)))


async def _record(
    audit: AuditService,
    action: AuditAction,
    user: User,
    client_ip: str,
    campaign_id: int,
    context: dict[str, Any] | None,
) -> None:
    """One place for the editor's audit entries."""
    await audit.record(
        action,
        user_id=user.id,
        actor_label=user.email,
        target_type="campaign",
        target_id=campaign_id,
        client_ip=client_ip,
        context=context,
    )
