"""Excel-export met drie tabbladen: Logistiek (momentopname), Aanvuladvies (live formules), Instellingen."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .calc import logistics_rows

COLORS = {"Kritiek": "F8C9C4", "Aanvullen": "FCE3B0", "OK": "CFE8D2", "Overstock": "CFE0F5",
          "Dood": "DDDDDD", "Gepauzeerd": "EEEEEE", "End of life": "E4E0EA"}
HEAD_FILL = PatternFill("solid", start_color="1F2A37")
HEAD_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="BBBBBB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _header(ws, row, titles):
    for i, title in enumerate(titles, 1):
        c = ws.cell(row=row, column=i, value=title)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BOX
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 32


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def build(result, channel_name: str) -> bytes:
    p = result["params"]
    wb = Workbook()

    # --- 1. Logistiek: statische momentopname --------------------------------
    ws = wb.active
    ws.title = "Logistiek"
    ws["A1"] = "Aanmeldopdracht %s" % channel_name
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Rapportdatum: %s (voorraadstand van die dag). Momentopname: wijzigt niet mee met de instellingen." % result["ref_date"]
    _header(ws, 4, ["EAN", "Artikelcode", "Productnaam", "Besteleenheid", "Aanleveren (besteleenh.)",
                    "Aanleveren (stuks)", "Prioriteit", "Aangemeld op / paraaf"])
    row = 5
    for r in logistics_rows(result):
        values = [r["ean"], r["article_code"], r["name"], r["unit"] if r["unit"] else "ontbreekt",
                  r["units"] if r["units"] else "", r["deliver"],
                  "1 - Kritiek" if r["status"] == "Kritiek" else "2 - Aanvullen", ""]
        for i, v in enumerate(values, 1):
            c = ws.cell(row=row, column=i, value=v)
            c.border = BOX
            if i == 7:
                c.fill = PatternFill("solid", start_color=COLORS[r["status"]])
        ws.cell(row=row, column=1).number_format = "@"
        row += 1
    if row == 5:
        ws["A5"] = "Geen artikelen onder de besteltrigger: er hoeft nu niets aangemeld te worden."
    _widths(ws, [16, 22, 60, 13, 14, 13, 14, 24])
    ws.freeze_panes = "A5"

    # --- 3. Instellingen (eerst opbouwen, de formules verwijzen ernaar) -------
    wi = wb.create_sheet("Instellingen")
    wi["A1"] = "Instellingen %s" % channel_name
    wi["A1"].font = Font(bold=True, size=14)
    wi["A2"] = "Wijzig de gele cellen: het tabblad Aanvuladvies rekent direct mee."
    settings = [(4, "Doel-dekking (dagen)", p["target"]), (5, "Lead time (dagen)", p["lead"]),
                (6, "Veiligheidsbuffer (dagen)", p["buffer"]), (7, "Besteltrigger (dagen dekking)", p["trigger"]),
                (8, "Velocity-periode (dagen)", p["velocity"])]
    for r_, label, value in settings:
        wi.cell(row=r_, column=1, value=label)
        c = wi.cell(row=r_, column=2, value=value)
        c.fill, c.border = PatternFill("solid", start_color="FFF2B3"), BOX
    wi["A10"], wi["B10"] = "Bestelpunt (lead time + buffer)", "=B5+B6"
    wi["B10"].border = BOX
    wi["A12"] = "Aanvulformule"
    wi["A12"].font = Font(bold=True)
    wi["A13"] = "Als dekking <= besteltrigger: MAX(0; AFRONDEN.NAAR.BOVEN((doel-dekking + lead time) x dagafzet - voorraad - onderweg)), anders 0."
    wi["A14"] = "Aanleveren = naar boven afgerond op hele besteleenheden."
    wi["A16"] = "Kleurlegenda"
    wi["A16"].font = Font(bold=True)
    legend = [("Kritiek", "Verkoopt en dekking onder het bestelpunt: loopt mogelijk leeg voor aankomst"),
              ("Aanvullen", "Dekking op of onder de besteltrigger en advies groter dan nul"),
              ("OK", "Dekking tussen besteltrigger en 1,5x doel: geen actie"),
              ("Overstock", "Dekking boven 1,5x doel: geen zending"),
              ("Dood", "Geen verkoop in de velocity-periode: niet aanvullen"),
              ("Gepauzeerd", "Op dit kanaal gepauzeerd: niet aanvullen"),
              ("End of life", "Artikel loopt uit: niet meer aanvullen")]
    for i, (status, text) in enumerate(legend):
        c = wi.cell(row=17 + i, column=1, value=status)
        c.fill, c.border = PatternFill("solid", start_color=COLORS[status]), BOX
        wi.cell(row=17 + i, column=2, value=text)
    _widths(wi, [34, 14])

    # --- 2. Aanvuladvies: alle artikelen met live formules --------------------
    wa = wb.create_sheet("Aanvuladvies", 1)
    titles = ["EAN", "Artikelcode", "Productnaam", "Voorraad", "Besteld (velocity-periode)", "Onderweg",
              "Dagafzet", "Dagen dekking", "Voorraad bij aankomst", "Advies (stuks)", "Besteleenheid",
              "Advies (besteleenh.)", "Aanleveren (stuks)", "Status", "Uitgezet", "Besteld (28 dgn)",
              "Retouren", "Onverkoopbaar", "Opmerkingen"]
    _header(wa, 1, titles)
    S = "Instellingen!"
    last = 1
    for n, r in enumerate(result["rows"], 2):
        last = n
        wa.cell(row=n, column=1, value=r["ean"]).number_format = "@"
        wa.cell(row=n, column=2, value=r["article_code"])
        wa.cell(row=n, column=3, value=r["name"])
        wa.cell(row=n, column=4, value=r["stock"])
        wa.cell(row=n, column=5, value=r["ordered"])
        wa.cell(row=n, column=6, value=r["inbound"])
        wa.cell(row=n, column=7, value="=E%d/%s$B$8" % (n, S)).number_format = "0.00"
        wa.cell(row=n, column=8, value='=IF(G%d>0,D%d/G%d,"")' % (n, n, n)).number_format = "0.0"
        wa.cell(row=n, column=9, value="=D%d-%s$B$5*G%d" % (n, S, n)).number_format = "0"
        wa.cell(row=n, column=10, value=(
            '=IF(O{n}<>"",0,IF(G{n}>0,IF(H{n}<={S}$B$7,MAX(0,ROUNDUP(({S}$B$4+{S}$B$5)*G{n}-D{n}-F{n},0)),0),0))'
        ).format(n=n, S=S))
        wa.cell(row=n, column=11, value=r["unit"])
        wa.cell(row=n, column=12, value='=IF(AND(J{n}>0,N(K{n})>0),ROUNDUP(J{n}/K{n},0),0)'.format(n=n))
        wa.cell(row=n, column=13, value='=IF(N(K{n})>0,L{n}*K{n},J{n})'.format(n=n))
        wa.cell(row=n, column=14, value=(
            '=IF(O{n}<>"",O{n},IF(E{n}=0,"Dood",IF(H{n}<{S}$B$10,"Kritiek",'
            'IF(AND(H{n}<={S}$B$7,J{n}>0),"Aanvullen",IF(H{n}>1.5*{S}$B$4,"Overstock","OK")))))'
        ).format(n=n, S=S))
        wa.cell(row=n, column=15, value={"eol": "End of life", "pauze": "Gepauzeerd"}.get(r["mode"], ""))
        wa.cell(row=n, column=16, value=r["ordered28"] if r["ordered28"] is not None else "")
        wa.cell(row=n, column=17, value=r["returns"])
        wa.cell(row=n, column=18, value=r["unsellable"])
        wa.cell(row=n, column=19, value="; ".join(text for _, text in r["signals"]))
    for status, color in COLORS.items():
        wa.conditional_formatting.add(
            "A2:S%d" % max(last, 2),
            FormulaRule(formula=['$N2="%s"' % status], fill=PatternFill("solid", start_color=color, end_color=color)))
    _widths(wa, [16, 22, 55, 10, 12, 10, 9, 10, 12, 10, 12, 12, 12, 15, 9, 10, 9, 13, 60])
    wa.freeze_panes = "D2"
    wa.auto_filter.ref = "A1:S%d" % max(last, 2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
