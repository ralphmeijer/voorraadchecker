# Voorraadchecker — projectinstructie

LvB-voorraadchecker voor Dexxon (merken Philips en Grixx): haalt via de bol.com Retailer API voorraad, bestellingen en retouren op, berekent het aanvuladvies en toont dit in een dashboard op de VPS.

## Opbouw

- Python (standaardbibliotheek plus `openpyxl`) met SQLite in `data/voorraad.db`. Geen Docker: de VPS heeft 843 MB geheugen. Code moet werken op Python 3.9 (deze Mac) en 3.14 (VPS).
- `vc.py` is de opdrachtregel: `init`, `masterdata`, `rapport`, `sync`, `test-api`, `weekmail`, `gebruiker`, `serve`. Lokaal starten: `.venv/bin/python vc.py serve` (poort 8768).
- `voorraad/calc.py` bevat het rekenmodel uit de projectinstructie van Ralph (doel 60, lead time 7, buffer 7, trigger 16, velocity 14 dagen; per kanaal instelbaar).
- `voorraad/channels/` bevat per marketplace een koppeling met hetzelfde contract (`base.py`). Nieuwe marketplace: module toevoegen, registreren in `__init__.py`, rij in tabel `channels`.
- Zendingen (`voorraad/shipments.py`): per zending aangemeld, ontvangen en opgeboekt. Afwijkingen: afgeronde zending met ander aantal opgeboekt dan aangemeld, of aangekomen en na de lead time nog niet afgerond. Staat een afwijking er een dag later nog, dan gaat er een mail uit; afhandelen kan in het dashboard. Onderweg telt op aankomstdatum, niet op aanmelddatum (aanmelden kan weken voor levering).
- Artikelfoto's (`voorraad/photos.py`): bij de ophaalronde eenmalig per artikel van bol gehaald en bewaard in `data/fotos` (niet in git, opnieuw op te halen). Alleen zichtbaar na inloggen via `/foto/<ean>.jpg`; in de weekmail als ingesloten afbeelding.
- Zendingen aanmaken (`voorraad/drafts.py`): goedkeuren (hele advies of aangepast) -> magazijnadressen opvragen bij bol -> per magazijn een deelzending met vervoerder, leverdatum, laadeenheden en labelservice -> pas na bevestiging aanmaken. Nooit automatisch en schrijfacties nooit herhalen. Kenmerk zoals logistiek: DDMMJJJJ + NR + volgnummer. `BOL_DEMO=1` gebruikt de testomgeving van bol. Een echte zending aanmaken doet Ralph zelf in het dashboard; Claude mag dat in deze sessie niet.
- Versiebeheer: besloten repository `ralphmeijer/voorraadchecker` op GitHub. Naar de VPS zetten: wijzigingen vastleggen en `deploy/bijwerken.sh` draaien (push, daarna `git pull` op de VPS en herstart). De VPS heeft een eigen leessleutel.
- Geheimen staan in `config.env` (niet in git). Ralph vult die zelf in; nooit sleutels in de chat of in de code.
- Bol-orders: de API geeft alleen open orders plus 48 uur terug, dus de dagelijkse sync bouwt de historie op. Het LvB-dagrapport (`vc.py rapport`) is de startvulling en de terugvaloptie.
- SSD's gaan per doos van 20. Besteleenheden nooit gokken: ontbrekende eenheid blijft leeg en wordt gemeld.

## Werkwijze met Ralph

- Communiceer in het Nederlands.
- **Stel vragen als meerkeuze.** Gebruik de vragen-dialoog (AskUserQuestion) met 2 tot 4 concrete opties per vraag, de aanbevolen optie eerst. Stel geen lange lijsten open vragen in lopende tekst. Alleen wat echt niet in opties te vangen is (bijvoorbeeld een hostnaam) mag een open vraag zijn.
- Eerst samen afstemmen, dan bouwen: benoem aannames en vraag bevestiging voordat iets definitief wordt.
- Eerlijke kadering: benoem zwaktes in de data en onzekerheden expliciet.
