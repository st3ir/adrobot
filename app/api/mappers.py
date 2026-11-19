"""Pure functions mapping domain objects onto API DTOs."""

from __future__ import annotations

from app.core.geo import country_name
from app.keitaro.models import Campaign
from app.schemas.campaigns import (
    CampaignCreateResponse,
    CampaignDraftResponse,
    CampaignSummaryOut,
    DraftOfferOut,
    DraftStreamOut,
    MetricsOut,
    PeriodOut,
    StreamOut,
)
from app.schemas.catalog import CampaignDefaultsOut
from app.services.campaign_creator import CampaignCreateResult
from app.services.draft import CampaignDraft, DraftOffer, DraftStream
from app.services.stats import Metrics


def campaign_summary(campaign: Campaign) -> CampaignSummaryOut:
    return CampaignSummaryOut(
        id=campaign.id,
        name=campaign.name,
        alias=campaign.alias,
        state=campaign.state,
        group_id=campaign.group_id,
        source_id=campaign.traffic_source_id,
        domain_id=campaign.domain_id,
    )


def metrics_out(metrics: Metrics) -> MetricsOut:
    return MetricsOut(
        clicks=metrics.clicks,
        unique_clicks=metrics.unique_clicks,
        conversions=metrics.conversions,
        leads=metrics.leads,
        sales=metrics.sales,
        rejected=metrics.rejected,
        revenue=metrics.revenue,
        cost=metrics.cost,
        profit=metrics.profit,
        roi=metrics.roi,
        cr=metrics.cr,
        epc=metrics.epc,
    )


def draft_offer_out(offer: DraftOffer) -> DraftOfferOut:
    return DraftOfferOut(
        offer_id=offer.offer_id,
        name=offer.name,
        share=offer.share,
        synced_share=offer.synced_share,
        pinned=offer.pinned,
        state=offer.state.value,
        synced_state=offer.synced_state.value,
        is_dirty=offer.is_dirty,
        url=offer.url,
        metrics=metrics_out(offer.metrics),
    )


def draft_stream_out(stream: DraftStream) -> DraftStreamOut:
    return DraftStreamOut(
        id=stream.keitaro_id,
        name=stream.name,
        schema_name=stream.schema_name,
        position=stream.position,
        state=stream.state,
        holds_offers=stream.holds_offers,
        redirect_url=stream.redirect_url,
        countries=list(stream.countries),
        offers=[draft_offer_out(offer) for offer in stream.offers],
        is_dirty=stream.is_dirty,
    )


def draft_out(draft: CampaignDraft) -> CampaignDraftResponse:
    return CampaignDraftResponse(
        campaign_id=draft.campaign_id,
        name=draft.name,
        alias=draft.alias,
        last_synced_at=draft.last_synced_at.isoformat() if draft.last_synced_at else None,
        is_dirty=draft.is_dirty,
        streams=[draft_stream_out(stream) for stream in draft.streams],
        totals=metrics_out(draft.stats.totals),
        stats_available=draft.stats.available,
        period=PeriodOut(
            date_from=draft.period.date_from.isoformat(),
            date_to=draft.period.date_to.isoformat(),
        ),
    )


def create_response(
    result: CampaignCreateResult, *, geo: str, redirect_url: str
) -> CampaignCreateResponse:
    streams = [
        StreamOut(
            id=result.geo_stream.id,
            name=result.geo_stream.name or "Geo redirect",
            schema_name=result.geo_stream.schema_,
            position=result.geo_stream.position,
            state=result.geo_stream.state,
            redirect_url=result.geo_stream.action_payload or redirect_url,
            countries=[geo],
            holds_offers=False,
        ),
        StreamOut(
            id=result.offer_stream.id,
            name=result.offer_stream.name or "Offers",
            schema_name=result.offer_stream.schema_,
            position=result.offer_stream.position,
            state=result.offer_stream.state,
            redirect_url=None,
            countries=[],
            holds_offers=True,
        ),
    ]
    return CampaignCreateResponse(
        campaign=campaign_summary(result.campaign),
        tracking_url=result.tracking_url,
        geo=geo,
        geo_name=country_name(geo),
        redirect_url=redirect_url,
        offer_id=result.offer_stream.offers[0].offer_id
        if result.offer_stream.offers
        else 0,
        offer_name=result.offer_name,
        defaults=CampaignDefaultsOut(
            domain_id=result.defaults.domain_id,
            domain_name=result.defaults.domain_name,
            group_id=result.defaults.group_id,
            group_name=result.defaults.group_name,
            source_id=result.defaults.source_id,
            source_name=result.defaults.source_name,
        ),
        streams=streams,
    )
