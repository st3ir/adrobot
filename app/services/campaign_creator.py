"""Use case: create a campaign with a geo stream and an offer stream."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import AdrobotError, KeitaroError
from app.core.logging import get_logger
from app.keitaro import builders
from app.keitaro.models import Campaign, Stream
from app.keitaro.protocols import CampaignWriter, StreamWriter
from app.services.catalog import CampaignDefaults, CatalogService
from app.services.naming import normalize_campaign_name

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CampaignCreateCommand:
    """Input of the campaign creator."""

    name: str
    geo: str
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class CampaignCreateResult:
    campaign: Campaign
    geo_stream: Stream
    offer_stream: Stream
    defaults: CampaignDefaults
    offer_name: str
    tracking_url: str | None


class CampaignCreatorService:
    """Builds a two-stream campaign in Keitaro.

    Stream 1 (position 1): everyone from ``geo`` is redirected to the
    configured URL (google.com by default).
    Stream 2 (position 2): everybody else rotates into the chosen offer.
    """

    def __init__(
        self,
        *,
        campaigns: CampaignWriter,
        streams: StreamWriter,
        catalog: CatalogService,
        name_prefix: str,
        redirect_url: str,
    ) -> None:
        self._campaigns = campaigns
        self._streams = streams
        self._catalog = catalog
        self._name_prefix = name_prefix
        self._redirect_url = redirect_url

    async def create(self, command: CampaignCreateCommand) -> CampaignCreateResult:
        name = normalize_campaign_name(command.name, prefix=self._name_prefix)
        offer = await self._catalog.get_offer(command.offer_id)
        defaults = await self._catalog.resolve_campaign_defaults(
            domain_id=command.domain_id,
            group_id=command.group_id,
            source_id=command.source_id,
        )

        campaign = await self._campaigns.create_campaign(
            builders.build_campaign_payload(
                name=name,
                domain_id=defaults.domain_id,
                group_id=defaults.group_id,
                source_id=defaults.source_id,
            )
        )
        logger.info("Created Keitaro campaign id=%s name=%s", campaign.id, campaign.name)

        try:
            geo_stream = await self._streams.create_stream(
                builders.build_geo_redirect_stream_payload(
                    campaign_id=campaign.id,
                    country_code=command.geo,
                    redirect_url=self._redirect_url,
                )
            )
            offer_stream = await self._streams.create_stream(
                builders.build_offer_stream_payload(
                    campaign_id=campaign.id,
                    offer_ids=[offer.id],
                )
            )
        except AdrobotError:
            await self._rollback(campaign.id)
            raise

        return CampaignCreateResult(
            campaign=campaign,
            geo_stream=geo_stream,
            offer_stream=offer_stream,
            defaults=defaults,
            offer_name=offer.name,
            tracking_url=self._tracking_url(defaults.domain_name, campaign.alias),
        )

    async def _rollback(self, campaign_id: int) -> None:
        """Best-effort cleanup so a half-built campaign is not left behind."""
        try:
            await self._campaigns.delete_campaign(campaign_id)
            logger.warning("Rolled back campaign id=%s after a stream failure", campaign_id)
        except KeitaroError:
            logger.error(
                "Could not roll back campaign id=%s; it may need manual cleanup", campaign_id
            )

    @staticmethod
    def _tracking_url(domain_name: str, alias: str | None) -> str | None:
        if not alias:
            return None
        host = domain_name.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return f"{host}/{alias}"
