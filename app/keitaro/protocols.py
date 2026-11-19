"""Narrow interfaces the service layer depends on.

Services depend on these Protocols rather than on :class:`KeitaroGateway`
(dependency inversion), which keeps them trivially testable with fakes and
free of HTTP concerns.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.keitaro.models import Campaign, Domain, Group, Offer, Stream, TrafficSource


@runtime_checkable
class CatalogReader(Protocol):
    """Read-only access to Keitaro reference data."""

    async def list_offers(self) -> list[Offer]: ...
    async def list_groups(self) -> list[Group]: ...
    async def list_domains(self) -> list[Domain]: ...
    async def list_traffic_sources(self) -> list[TrafficSource]: ...


@runtime_checkable
class CampaignReader(Protocol):
    async def list_campaigns(self) -> list[Campaign]: ...
    async def get_campaign(self, campaign_id: int) -> Campaign: ...
    async def list_streams(self, campaign_id: int) -> list[Stream]: ...


@runtime_checkable
class ReferenceReader(CatalogReader, CampaignReader, Protocol):
    """Everything the catalog service reads and caches."""


@runtime_checkable
class CampaignWriter(Protocol):
    async def create_campaign(self, payload: dict[str, Any]) -> Campaign: ...
    async def delete_campaign(self, campaign_id: int) -> None: ...


@runtime_checkable
class StreamWriter(Protocol):
    async def create_stream(self, payload: dict[str, Any]) -> Stream: ...
    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> Stream: ...
    async def delete_stream(self, stream_id: int) -> None: ...


@runtime_checkable
class ReportReader(Protocol):
    async def build_report(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class KeitaroPort(
    CatalogReader, CampaignReader, CampaignWriter, StreamWriter, ReportReader, Protocol
):
    """Everything the application needs from Keitaro."""
