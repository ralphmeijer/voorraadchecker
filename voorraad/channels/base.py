"""Het contract voor een marketplace-koppeling.

Een nieuwe marketplace (Amazon, Joybuy, Walmart, ...) toevoegen betekent:
  1. een module in deze map met een klasse die Channel uitbreidt;
  2. die klasse registreren in channels/__init__.py;
  3. een rij toevoegen aan de tabel `channels` (met eigen parameters, zoals de doorlooptijd).
Rekenmodel, database en dashboard hoeven daarvoor niet te veranderen.
"""
from __future__ import annotations

from dataclasses import dataclass


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
class InboundLine:
    ref: str              # kenmerk van de zending
    ean: str
    quantity: int         # aangemeld en nog niet op voorraad geboekt
    state: str
    created: str          # JJJJ-MM-DD


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

    def fetch_inbound(self) -> list:
        return []
