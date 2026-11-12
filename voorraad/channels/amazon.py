"""Koppeling met Amazon FBA via de Selling Partner API (alleen lezen).

Bijzonderheden ten opzichte van bol:
  - Amazon geeft geen EAN terug (de catalogus-API valt buiten de aangevraagde rollen). Elk artikel
    krijgt daarom een interne sleutel van 13 cijfers die met 29 begint, afgeleid van de Amazon-SKU.
    De SKU staat als artikelcode bij het artikel; de ophaalronde neemt besteleenheid en foto over
    van het artikel met dezelfde artikelcode uit de masterdata.
  - Wat onderweg is komt rechtstreeks uit de voorraadopgave van Amazon (working, shipped, receiving).
  - Bestellingen zijn over een datumbereik op te vragen, dus er is geen startvulling nodig.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .. import config
from .base import Channel, ChannelError, OrderLine, Shipment, ShipmentLine, StockRow

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
API = "https://sellingpartnerapi-eu.amazon.com"
# Duitsland, Nederland, Belgie, Frankrijk
DEFAULT_MARKETPLACES = "A1PA6795UKMFR9,A1805IZSGTT6HS,AMEN7PMS3EDWL,A13V1IB3VIYZZH"
# Minimale tijd tussen twee aanroepen per soort, ruim binnen de limieten van Amazon.
PAUSE = {"inventory": 0.6, "orders": 3.0, "order_items": 2.2, "shipments": 0.6}
STATE_MAP = {"WORKING": "ANNOUNCED", "READY_TO_SHIP": "ANNOUNCED", "SHIPPED": "IN_TRANSIT", "IN_TRANSIT": "IN_TRANSIT",
             "DELIVERED": "ARRIVED_AT_WH", "CHECKED_IN": "ARRIVED_AT_WH", "RECEIVING": "IN_PROGRESS_AT_WH",
             "CLOSED": "DONE", "CANCELLED": "CANCELLED", "DELETED": "CANCELLED", "ERROR": "CANCELLED"}

try:
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo("Europe/Amsterdam")
except Exception:  # geen tijdzonegegevens: reken met vaste wintertijd
    LOCAL = timezone(timedelta(hours=1))


def key_for(sku: str) -> str:
    """Interne artikelsleutel voor een Amazon-SKU: 13 cijfers, beginnend met 29 (EAN-bereik voor eigen gebruik)."""
    return "29" + str(int(hashlib.sha1(sku.encode()).hexdigest(), 16))[-11:].zfill(11)


def _local_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL).date().isoformat()
    except (ValueError, AttributeError):
        return (iso or "")[:10]


class AmazonChannel(Channel):
    adapter = "amazon"

    def __init__(self):
        self.client_id = config.get("AMAZON_LWA_CLIENT_ID")
        self.client_secret = config.get("AMAZON_LWA_CLIENT_SECRET")
        self.refresh_token = config.get("AMAZON_REFRESH_TOKEN")
        self.marketplaces = [m.strip() for m in config.get("AMAZON_MARKETPLACES", DEFAULT_MARKETPLACES).split(",") if m.strip()]
        self.stock_marketplace = config.get("AMAZON_STOCK_MARKETPLACE") or self.marketplaces[0]
        self._token = None
        self._token_until = 0.0
        self._last = {}

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # --- http -----------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_until:
            return self._token
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self.refresh_token,
                                       "client_id": self.client_id, "client_secret": self.client_secret}).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise ChannelError("Amazon weigert de inloggegevens: controleer de drie AMAZON-regels in config.env")
            raise ChannelError("Inloggen bij Amazon mislukt (HTTP %s)" % e.code)
        except urllib.error.URLError as e:
            raise ChannelError("Amazon is niet bereikbaar: %s" % e.reason)
        self._token = data["access_token"]
        self._token_until = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def _get(self, kind: str, path: str, params: dict = None):
        if not self.configured():
            raise ChannelError("De Amazon API-gegevens ontbreken in config.env")
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            wait = PAUSE.get(kind, 1.0) - (time.time() - self._last.get(kind, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[kind] = time.time()
            req = urllib.request.Request(url, headers={
                "x-amz-access-token": self._get_token(), "Accept": "application/json",
                "User-Agent": "Voorraadchecker/1.0 (Language=Python)"})
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    text = resp.read().decode()
                    return json.loads(text) if text.strip() else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:
                    time.sleep(min(90, 15 * (attempt + 1)))
                    continue
                if e.code >= 500 and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                detail = ""
                try:
                    errors = json.loads(e.read().decode()).get("errors") or []
                    detail = "; ".join(str(x.get("message")) for x in errors)
                except Exception:
                    pass
                if e.code == 403:
                    raise ChannelError("Amazon geeft geen toegang tot %s (ontbreekt een rol?) %s" % (path, detail))
                raise ChannelError("Amazon API-fout %s op %s %s" % (e.code, path, detail))
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise ChannelError("Amazon is niet bereikbaar: %s" % e.reason)
        raise ChannelError("Amazon blijft de aanvraag weigeren (limiet bereikt) op %s" % path)

    # --- gegevens --------------------------------------------------------------
    def fetch_stock(self) -> list:
        out, token = [], None
        mp = self.stock_marketplace
        for _ in range(100):
            params = {"granularityType": "Marketplace", "granularityId": mp, "marketplaceIds": mp, "details": "true"}
            if token:
                params["nextToken"] = token
            data = self._get("inventory", "/fba/inventory/v1/summaries", params)
            for it in (data.get("payload") or {}).get("inventorySummaries") or []:
                sku = it.get("sellerSku")
                if not sku:
                    continue
                d = it.get("inventoryDetails") or {}
                inbound = sum(int(d.get(k) or 0) for k in ("inboundWorkingQuantity", "inboundShippedQuantity", "inboundReceivingQuantity"))
                out.append(StockRow(
                    ean=key_for(sku), stock=int(d.get("fulfillableQuantity") or 0),
                    graded=int((d.get("unfulfillableQuantity") or {}).get("totalUnfulfillableQuantity") or 0),
                    sku=sku, title=it.get("productName") or "", inbound=inbound))
            token = (data.get("pagination") or {}).get("nextToken")
            if not token:
                break
        return out

    def fetch_order_lines(self, backfill_days: int = 0) -> list:
        """Door Amazon verzonden bestellingen (AFN). Standaard alles wat de laatste 3 dagen is gewijzigd;
        met backfill_days alles wat in die periode is geplaatst."""
        now = datetime.now(timezone.utc)
        params = {"MarketplaceIds": ",".join(self.marketplaces), "FulfillmentChannels": "AFN", "MaxResultsPerPage": 100}
        if backfill_days:
            params["CreatedAfter"] = (now - timedelta(days=backfill_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            params["LastUpdatedAfter"] = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        orders, token = [], None
        for _ in range(200):
            data = self._get("orders", "/orders/v0/orders", {"NextToken": token, "MarketplaceIds": params["MarketplaceIds"]} if token else params)
            payload = data.get("payload") or {}
            orders.extend(payload.get("Orders") or [])
            token = payload.get("NextToken")
            if not token:
                break
        lines = []
        for o in orders:
            oid = o.get("AmazonOrderId")
            if not oid:
                continue
            placed = _local_date(o.get("PurchaseDate") or "")
            cancelled_order = o.get("OrderStatus") == "Canceled"
            token = None
            for _ in range(20):
                data = self._get("order_items", "/orders/v0/orders/%s/orderItems" % urllib.parse.quote(oid),
                                 {"NextToken": token} if token else None)
                payload = data.get("payload") or {}
                for it in payload.get("OrderItems") or []:
                    sku = it.get("SellerSKU")
                    if not sku:
                        continue
                    qty = int(it.get("QuantityOrdered") or 0)
                    lines.append(OrderLine(item_id=str(it.get("OrderItemId")), order_id=oid, ean=key_for(sku),
                                           placed_date=placed, quantity=qty, cancelled=qty if cancelled_order else 0))
                token = payload.get("NextToken")
                if not token:
                    break
        return lines

    def fetch_shipments(self, since: str, skip_ids=()) -> list:
        mp = self.stock_marketplace
        statuses = ",".join(STATE_MAP.keys())
        params = {"QueryType": "DATE_RANGE", "MarketplaceId": mp, "ShipmentStatusList": statuses,
                  "LastUpdatedAfter": since + "T00:00:00Z",
                  "LastUpdatedBefore": (date.today() + timedelta(days=1)).isoformat() + "T00:00:00Z"}
        found, token = [], None
        for _ in range(50):
            data = self._get("shipments", "/fba/inbound/v0/shipments",
                             {"QueryType": "NEXT_TOKEN", "NextToken": token, "MarketplaceId": mp} if token else params)
            payload = data.get("payload") or {}
            found.extend(payload.get("ShipmentData") or [])
            token = payload.get("NextToken")
            if not token:
                break
        out, skip = [], set(skip_ids)
        today = date.today().isoformat()
        for s in found:
            sid = s.get("ShipmentId")
            if not sid or sid in skip:
                continue
            state = STATE_MAP.get(s.get("ShipmentStatus"), "ANNOUNCED")
            lines, token = {}, None
            for _ in range(50):
                data = self._get("shipments", "/fba/inbound/v0/shipments/%s/items" % urllib.parse.quote(sid),
                                 {"MarketplaceId": mp, "NextToken": token} if token else {"MarketplaceId": mp})
                payload = data.get("payload") or {}
                for it in payload.get("ItemData") or []:
                    sku = it.get("SellerSKU")
                    if not sku:
                        continue
                    line = lines.setdefault(key_for(sku), ShipmentLine(ean=key_for(sku), announced=0))
                    line.announced += int(it.get("QuantityShipped") or 0)
                    line.received += int(it.get("QuantityReceived") or 0)
                    line.regular += int(it.get("QuantityReceived") or 0)
                token = payload.get("NextToken")
                if not token:
                    break
            # Amazon geeft geen aanmaakdatum: die staat in de naam, bijvoorbeeld "FBA STA (11/12/2026 10:57)-HAJ1".
            m = re.search(r"\((\d{2})/(\d{2})/(\d{4})", s.get("ShipmentName") or "")
            created = "%s-%s-%s" % (m.group(3), m.group(1), m.group(2)) if m else today
            centre = s.get("DestinationFulfillmentCenterId")
            out.append(Shipment(
                ship_id=sid, reference=sid + (" naar " + centre if centre else ""), state=state, created=created,
                arrived=today if state in ("ARRIVED_AT_WH", "IN_PROGRESS_AT_WH", "DONE") else None,
                done_at=today if state == "DONE" else None, lines=list(lines.values())))
        return out
