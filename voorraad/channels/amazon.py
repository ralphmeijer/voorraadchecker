"""Koppeling met Amazon FBA via de Selling Partner API (SP-API).

Nog niet gebouwd: het kanaal bestaat al wel, zodat het tabblad en de eigen parameters klaarstaan.
De koppeling volgt zodra de API-gegevens er zijn (AMAZON_LWA_CLIENT_ID, AMAZON_LWA_CLIENT_SECRET,
AMAZON_REFRESH_TOKEN in config.env). Tot die tijd slaat de ophaalronde dit kanaal over.
"""
from __future__ import annotations

from .base import Channel, ChannelError


class AmazonChannel(Channel):
    adapter = "amazon"
    built = False

    def configured(self) -> bool:
        return False

    def fetch_stock(self) -> list:
        raise ChannelError("De koppeling met Amazon is nog niet gebouwd")

    def fetch_order_lines(self, backfill_days: int = 0) -> list:
        raise ChannelError("De koppeling met Amazon is nog niet gebouwd")
