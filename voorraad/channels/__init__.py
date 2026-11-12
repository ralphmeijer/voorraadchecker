from __future__ import annotations

from .base import Channel, ChannelError
from .amazon import AmazonChannel
from .bol import BolChannel

# adapter-naam (kolom channels.adapter) -> klasse
ADAPTERS = {
    "bol": BolChannel,
    "amazon": AmazonChannel,
}


def get_adapter(ch) -> Channel:
    cls = ADAPTERS.get(ch["adapter"])
    if cls is None:
        raise ChannelError("Onbekende koppeling: %s" % ch["adapter"])
    return cls()
