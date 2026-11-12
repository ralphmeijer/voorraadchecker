"""Koppeling met de bol.com Retailer API v10 (alleen lezen, alleen LvB/FBB)."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from .. import config
from .base import Channel, ChannelError, OrderLine, ReturnLine, Shipment, ShipmentLine, StockRow

TOKEN_URL = "https://login.bol.com/token"
API = "https://api.bol.com/retailer"
ACCEPT = "application/vnd.retailer.v10+json"
# Minimale tijd tussen twee aanroepen per soort, ruim binnen de gepubliceerde limieten
# (inventory 20/min, orders 25/min, returns 20/min, replenishments 10/min).
PAUSE = {"inventory": 3.2, "orders": 2.6, "returns": 3.2, "replenishments": 6.5}
OPEN_STATES = ("ANNOUNCED", "IN_TRANSIT", "ARRIVED_AT_WH", "IN_PROGRESS_AT_WH")
MAX_PAGES = 200


class BolChannel(Channel):
    adapter = "bol"

    def __init__(self):
        self.client_id = config.get("BOL_CLIENT_ID")
        self.client_secret = config.get("BOL_CLIENT_SECRET")
        self._token = None
        self._token_until = 0.0
        self._last = {}
        # BOL_DEMO=1 gebruikt de testomgeving van bol: vaste voorbeeldantwoorden, geen echte wijzigingen.
        self.demo = config.get("BOL_DEMO") == "1"
        self.api = "https://api.bol.com/retailer-demo" if self.demo else API
        self.shared = "https://api.bol.com/shared-demo" if self.demo else "https://api.bol.com/shared"

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # --- http -----------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_until:
            return self._token
        basic = base64.b64encode(("%s:%s" % (self.client_id, self.client_secret)).encode()).decode()
        req = urllib.request.Request(
            TOKEN_URL, data=b"grant_type=client_credentials", method="POST",
            headers={"Authorization": "Basic " + basic, "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise ChannelError("Bol weigert de inloggegevens: controleer BOL_CLIENT_ID en BOL_CLIENT_SECRET")
            raise ChannelError("Inloggen bij bol mislukt (HTTP %s)" % e.code)
        except urllib.error.URLError as e:
            raise ChannelError("Bol is niet bereikbaar: %s" % e.reason)
        self._token = data["access_token"]
        self._token_until = time.time() + int(data.get("expires_in", 299)) - 30
        return self._token

    def _get(self, kind: str, path: str, params: dict = None):
        if not self.configured():
            raise ChannelError("De bol API-gegevens ontbreken in config.env")
        url = self.api + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            wait = PAUSE.get(kind, 1.0) - (time.time() - self._last.get(kind, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[kind] = time.time()
            req = urllib.request.Request(
                url, headers={"Authorization": "Bearer " + self._get_token(), "Accept": ACCEPT})
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    body = resp.read().decode()
                    return json.loads(body) if body.strip() else {}
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry = e.headers.get("Retry-After")
                    time.sleep(min(120, int(retry) if retry and retry.isdigit() else 60))
                    continue
                if e.code == 401 and attempt == 0:
                    self._token = None
                    continue
                if e.code >= 500 and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise ChannelError("Bol API-fout %s op %s %s" % (e.code, path, detail))
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise ChannelError("Bol is niet bereikbaar: %s" % e.reason)
        raise ChannelError("Bol API blijft de aanvraag weigeren (limiet bereikt) op %s" % path)

    def _call(self, method: str, url: str, body: dict = None):
        """Een enkele aanroep zonder herhaling. Voor schrijfacties: een herhaalde POST zou een dubbele
        zending kunnen aanmaken, dus bij een fout stoppen we en melden we die."""
        if not self.configured():
            raise ChannelError("De bol API-gegevens ontbreken in config.env")
        headers = {"Authorization": "Bearer " + self._get_token(), "Accept": ACCEPT}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = ACCEPT
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                text = resp.read().decode()
                return json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                problem = json.loads(e.read().decode())
                detail = problem.get("detail") or problem.get("title") or ""
                reasons = "; ".join("%s: %s" % (v.get("name"), v.get("reason")) for v in problem.get("violations") or [])
                if reasons:
                    detail = (detail + " " + reasons).strip()
            except Exception:
                pass
            if e.code == 429:
                raise ChannelError("Bol staat even geen nieuwe aanvragen toe (limiet bereikt). Probeer het over een minuut opnieuw.")
            raise ChannelError("Bol meldt een fout (%s): %s" % (e.code, detail or "geen toelichting"))
        except urllib.error.URLError as e:
            raise ChannelError("Bol is niet bereikbaar: %s" % e.reason)

    # --- zendingen aanmaken ----------------------------------------------------
    supports_create = True

    def process_status(self, process_id: str) -> dict:
        d = self._call("GET", "%s/process-status/%s" % (self.shared, urllib.parse.quote(str(process_id))))
        return {"status": d.get("status") or "PENDING", "entity_id": d.get("entityId"), "error": d.get("errorMessage")}

    def request_destinations(self, eans: list) -> str:
        d = self._call("POST", self.api + "/replenishments/product-destinations", {"eans": [{"ean": e} for e in eans]})
        if not d.get("processStatusId"):
            raise ChannelError("Bol gaf geen volgnummer terug voor het opvragen van de adressen")
        return str(d["processStatusId"])

    def get_destinations(self, destinations_id: str) -> list:
        d = self._call("GET", "%s/replenishments/product-destinations/%s" % (self.api, urllib.parse.quote(str(destinations_id))))
        out = []
        for item in d.get("productDestinations") or []:
            address = (item.get("destinationWarehouse") or {}).get("address") or item.get("destinationWarehouse") or {}
            out.append({"address": address, "eans": [str(e.get("ean")) for e in item.get("eans") or [] if e.get("ean")]})
        return out

    def delivery_dates(self) -> list:
        d = self._call("GET", self.api + "/replenishments/delivery-dates")
        return [str(x)[:10] for x in d.get("deliveryDates") or []]

    def create_replenishment(self, reference, lines, transporter, expected_date, labeling_by_bol, load_carriers) -> str:
        body = {
            "reference": reference,
            "deliveryInfo": {"expectedDeliveryDate": expected_date, "transporterCode": transporter},
            "labelingByBol": bool(labeling_by_bol),
            "numberOfLoadCarriers": int(load_carriers),
            "lines": [{"ean": ean, "quantity": int(qty)} for ean, qty in lines],
        }
        d = self._call("POST", self.api + "/replenishments", body)
        if not d.get("processStatusId"):
            raise ChannelError("Bol gaf geen volgnummer terug voor de nieuwe zending")
        return str(d["processStatusId"])

    def cancel_replenishment(self, ship_id: str) -> str:
        d = self._call("PUT", "%s/replenishments/%s" % (self.api, urllib.parse.quote(str(ship_id))), {"state": "CANCELLED"})
        return str(d.get("processStatusId") or "")

    def _pages(self, kind, path, key, params):
        for page in range(1, MAX_PAGES + 1):
            data = self._get(kind, path, dict(params, page=page))
            items = data.get(key) or []
            if not items:
                return
            for item in items:
                yield item

    # --- gegevens --------------------------------------------------------------
    def fetch_stock(self) -> list:
        out = []
        for it in self._pages("inventory", "/inventory", "inventory", {}):
            if it.get("ean"):
                out.append(StockRow(ean=str(it["ean"]), stock=int(it.get("regularStock") or 0),
                                    graded=int(it.get("gradedStock") or 0),
                                    sku=str(it.get("bsku") or ""), title=it.get("title") or ""))
        return out

    def _order_lines(self, params):
        for order in self._pages("orders", "/orders", "orders", params):
            placed = (order.get("orderPlacedDateTime") or "")[:10]
            for it in order.get("orderItems") or []:
                if it.get("fulfilmentMethod") not in (None, "FBB"):
                    continue
                yield OrderLine(item_id=str(it["orderItemId"]), order_id=str(order.get("orderId")),
                                ean=str(it.get("ean")), placed_date=placed,
                                quantity=int(it.get("quantity") or 0),
                                cancelled=int(it.get("quantityCancelled") or 0))

    def fetch_order_lines(self, backfill_days: int = 0) -> list:
        """Standaard: open orders plus alles wat de laatste 48 uur is verzonden of geannuleerd.

        De API heeft geen datumbereik. Daarom draait de sync dagelijks en bewaren we de historie zelf.
        Met backfill_days halen we per dag de gewijzigde orders op (latest-change-date); bol noemt dat
        een noodoptie, dus alleen gebruiken voor een eenmalige startvulling.
        """
        lines = {}
        base = {"fulfilment-method": "FBB", "status": "ALL"}
        for line in self._order_lines(base):
            lines[line.item_id] = line
        for i in range(1, backfill_days + 1):
            day = (date.today() - timedelta(days=i)).isoformat()
            for line in self._order_lines(dict(base, **{"latest-change-date": day})):
                lines.setdefault(line.item_id, line)
        return list(lines.values())

    def fetch_returns(self, since: str) -> list:
        out = {}
        for handled in ("false", "true"):
            old_in_a_row = 0
            for ret in self._pages("returns", "/returns", "returns",
                                   {"fulfilment-method": "FBB", "handled": handled}):
                reg = (ret.get("registrationDateTime") or "")[:10]
                if reg and reg < since:
                    # Aanname: nieuwste retouren eerst. Na twee pagina's oude retouren stoppen we.
                    old_in_a_row += 1
                    if old_in_a_row >= 100:
                        break
                    continue
                old_in_a_row = 0
                for it in ret.get("returnItems") or []:
                    qty = sum(int(pr.get("quantity") or 0) for pr in it.get("processingResults") or [])
                    out[str(it.get("rmaId"))] = ReturnLine(
                        rma_id=str(it.get("rmaId")), ean=str(it.get("ean")), reg_date=reg,
                        quantity=qty or int(it.get("expectedQuantity") or 0))
        return list(out.values())

    def fetch_photo_urls(self, ean: str) -> dict:
        """Hoofdfoto van een artikel: {'small': url, 'medium': url}."""
        data = self._get("products", "/products/%s/assets" % ean, {"usage": "PRIMARY"})
        out = {}
        for asset in data.get("assets") or []:
            for v in asset.get("variants") or []:
                if v.get("mimeType") == "image/jpeg" and v.get("size") and v.get("url"):
                    out.setdefault(v["size"], v["url"])
            if out:
                break
        return out

    def fetch_shipments(self, since: str, skip_ids=()) -> list:
        out, seen = [], set(skip_ids)
        for state in OPEN_STATES + ("DONE",):
            for rep in self._pages("replenishments", "/replenishments", "replenishments",
                                   {"state": state, "start-date": since}):
                rid = str(rep.get("replenishmentId"))
                if rid in seen:
                    continue
                seen.add(rid)
                d = self._get("replenishments", "/replenishments/" + rid)
                moments = {t.get("state"): (t.get("stateDateTime") or "")[:10] for t in d.get("stateTransitions") or []}
                arrived = min([m for k, m in moments.items() if k in ("ARRIVED_AT_WH", "IN_PROGRESS_AT_WH") and m] or [""])
                lines = [ShipmentLine(ean=str(l["ean"]), announced=int(l.get("quantityAnnounced") or 0),
                                      received=int(l.get("quantityReceived") or 0),
                                      in_progress=int(l.get("quantityInProgress") or 0),
                                      regular=int(l.get("quantityWithRegularState") or 0),
                                      graded=int(l.get("quantityWithGradedState") or 0))
                         for l in d.get("lines") or [] if l.get("ean")]
                out.append(Shipment(
                    ship_id=rid, reference=d.get("reference") or rid, state=d.get("state") or state,
                    created=(d.get("creationDateTime") or "")[:10],
                    expected=(d.get("deliveryInformation") or {}).get("expectedDeliveryDate"),
                    arrived=arrived or None, done_at=moments.get("DONE") or None, lines=lines))
        return out
