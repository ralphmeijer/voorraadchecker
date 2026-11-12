"""Het contract voor een marketplace-koppeling.

Een nieuwe marketplace (Amazon, Joybuy, Walmart, ...) toevoegen betekent:
  1. een module in deze map met een klasse die Channel uitbreidt;
  2. die klasse registreren in channels/__init__.py;
  3. een rij toevoegen aan de tabel `channels` (met eigen parameters, zoals de doorlooptijd).
Rekenmodel, database en dashboard hoeven daarvoor niet te veranderen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StockRow:
    ean: str
    stock: int            # verkoopbare voorraad in het fulfilment-magazijn van de marketplace
    graded: int = 0       # niet (als nieuw) verkoopbaar
    sku: str = ""
    title: str = ""


@dataclass
class OrderLine:
    item_id: str          # unieke sleutel van de orderregel
    order_id: str
    ean: str
    placed_date: str      # JJJJ-MM-DD, lokale datum van bestellen
    quantity: int
    cancelled: int = 0


@dataclass
class ReturnLine:
    rma_id: str
    ean: str
    reg_date: str         # JJJJ-MM-DD
    quantity: int


@dataclass
class ShipmentLine:
    ean: str
    announced: int
    received: int = 0
    in_progress: int = 0
    regular: int = 0      # opgeboekt als verkoopbaar
    graded: int = 0       # opgeboekt als niet (als nieuw) verkoopbaar


@dataclass
class Shipment:
    """Een aanvulzending naar het magazijn van de marketplace.

    state is een van: ANNOUNCED, IN_TRANSIT, ARRIVED_AT_WH, IN_PROGRESS_AT_WH, DONE, CANCELLED.
    """
    ship_id: str
    reference: str
    state: str
    created: str          # JJJJ-MM-DD, datum van aanmelden
    expected: str = None  # verwachte leverdatum
    arrived: str = None   # datum van aankomst in het magazijn
    done_at: str = None   # datum waarop alles is opgeboekt
    lines: list = field(default_factory=list)


class ChannelError(Exception):
    pass


class Channel:
    """Alleen voorraad die door de marketplace zelf wordt verzonden telt mee."""

    adapter = ""

    def configured(self) -> bool:
        raise NotImplementedError

    def fetch_stock(self) -> list:
        raise NotImplementedError

    def fetch_order_lines(self, backfill_days: int = 0) -> list:
        raise NotImplementedError

    def fetch_returns(self, since: str) -> list:
        return []

    def fetch_shipments(self, since: str, skip_ids=()) -> list:
        """Zendingen die sinds `since` zijn aangemeld. skip_ids: al afgeronde zendingen die we al kennen."""
        return []
