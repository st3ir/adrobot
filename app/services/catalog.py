"""Reference data (offers, domains, groups, sources) and campaign defaults."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import CatalogIncompleteError, KeitaroNotFoundError
from app.core.logging import get_logger
from app.keitaro.builders import CAMPAIGN_GROUP_TYPE
from app.keitaro.models import Campaign, Domain, Group, Offer, TrafficSource
from app.keitaro.protocols import ReferenceReader
from app.services.cache import TTLCache

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CampaignDefaults:
    """The domain/group/source a new campaign is attached to."""

    domain_id: int
    group_id: int
    source_id: int
    domain_name: str
    group_name: str
    source_name: str


class CatalogService:
    """Read-side service over Keitaro reference data, with a short TTL cache."""

    def __init__(
        self,
        keitaro: ReferenceReader,
        *,
        ttl_seconds: int = 60,
        preferred_domain: str | None = None,
        preferred_group: str | None = None,
        preferred_source: str | None = None,
    ) -> None:
        self._keitaro = keitaro
        self._preferred_domain = preferred_domain
        self._preferred_group = preferred_group
        self._preferred_source = preferred_source
        self._offers: TTLCache[list[Offer]] = TTLCache(ttl_seconds)
        self._groups: TTLCache[list[Group]] = TTLCache(ttl_seconds)
        self._domains: TTLCache[list[Domain]] = TTLCache(ttl_seconds)
        self._sources: TTLCache[list[TrafficSource]] = TTLCache(ttl_seconds)
        self._campaigns: TTLCache[list[Campaign]] = TTLCache(ttl_seconds)

    # -- raw listings ------------------------------------------------------
    async def offers(self) -> list[Offer]:
        return await self._offers.get(self._keitaro.list_offers)

    async def groups(self) -> list[Group]:
        return await self._groups.get(self._keitaro.list_groups)

    async def domains(self) -> list[Domain]:
        return await self._domains.get(self._keitaro.list_domains)

    async def traffic_sources(self) -> list[TrafficSource]:
        return await self._sources.get(self._keitaro.list_traffic_sources)

    async def campaigns(self) -> list[Campaign]:
        return await self._campaigns.get(self._keitaro.list_campaigns)

    def invalidate(self) -> None:
        for cache in (
            self._offers,
            self._groups,
            self._domains,
            self._sources,
            self._campaigns,
        ):
            cache.invalidate()

    # -- offers ------------------------------------------------------------
    async def search_offers(
        self, query: str | None = None, *, limit: int = 20, include_archived: bool = False
    ) -> list[Offer]:
        """Autocomplete search over offer name and id."""
        offers = await self.offers()
        if not include_archived:
            offers = [offer for offer in offers if not offer.is_archived]

        needle = (query or "").strip().lower()
        if needle:
            offers = [offer for offer in offers if self._matches(offer, needle)]
            offers.sort(key=lambda offer: self._relevance(offer, needle))
        else:
            offers.sort(key=lambda offer: offer.name.lower())
        return offers[:limit]

    async def get_offer(self, offer_id: int) -> Offer:
        for offer in await self.offers():
            if offer.id == offer_id:
                return offer
        raise KeitaroNotFoundError(f"Offer {offer_id} was not found in Keitaro.")

    async def get_offers_by_ids(self, offer_ids: list[int]) -> dict[int, Offer]:
        wanted = set(offer_ids)
        return {offer.id: offer for offer in await self.offers() if offer.id in wanted}

    @staticmethod
    def _matches(offer: Offer, needle: str) -> bool:
        return needle in offer.name.lower() or needle == str(offer.id)

    @staticmethod
    def _relevance(offer: Offer, needle: str) -> tuple[int, str]:
        name = offer.name.lower()
        if str(offer.id) == needle:
            rank = 0
        elif name.startswith(needle):
            rank = 1
        else:
            rank = 2
        return rank, name

    # -- campaigns ---------------------------------------------------------
    async def search_campaigns(
        self, query: str | None = None, *, limit: int = 50
    ) -> list[Campaign]:
        """Search campaigns by name or id, newest first."""
        campaigns = await self.campaigns()
        needle = (query or "").strip().lower()
        if needle:
            campaigns = [
                campaign
                for campaign in campaigns
                if needle in campaign.name.lower() or needle == str(campaign.id)
            ]
        campaigns.sort(key=lambda campaign: campaign.id, reverse=True)
        return campaigns[:limit]

    # -- campaign defaults -------------------------------------------------
    async def resolve_campaign_defaults(
        self,
        *,
        domain_id: int | None = None,
        group_id: int | None = None,
        source_id: int | None = None,
    ) -> CampaignDefaults:
        """Pick the domain/group/source for a new campaign.

        Explicit ids win; otherwise the configured preferred name is matched;
        otherwise the first available entity is used.
        """
        domains = await self.domains()
        groups = [g for g in await self.groups() if g.type in (None, CAMPAIGN_GROUP_TYPE)]
        sources = await self.traffic_sources()

        domain = self._pick(domains, domain_id, self._preferred_domain, "domain")
        group = self._pick(groups, group_id, self._preferred_group, "campaign group")
        source = self._pick(sources, source_id, self._preferred_source, "traffic source")

        return CampaignDefaults(
            domain_id=domain.id,
            group_id=group.id,
            source_id=source.id,
            domain_name=domain.name,
            group_name=group.name,
            source_name=source.name,
        )

    @staticmethod
    def _pick(
        items: list[Domain] | list[Group] | list[TrafficSource],
        explicit_id: int | None,
        preferred_name: str | None,
        label: str,
    ) -> Domain | Group | TrafficSource:
        if not items:
            raise CatalogIncompleteError(f"Keitaro has no {label} configured.")
        if explicit_id is not None:
            for item in items:
                if item.id == explicit_id:
                    return item
            raise KeitaroNotFoundError(f"Unknown {label} id: {explicit_id}.")
        if preferred_name:
            needle = preferred_name.strip().lower()
            for item in items:
                if item.name.strip().lower() == needle:
                    return item
            logger.warning(
                "Preferred %s %r not found; falling back to the first one.",
                label,
                preferred_name,
            )
        return items[0]
