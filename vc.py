#!/usr/bin/env python3
"""Voorraadchecker: opdrachtregel.

  vc.py init                          database aanmaken
  vc.py masterdata <xlsx>... [--bundels <xlsx>]   masterdata importeren
  vc.py rapport <bolcom_..xlsx>       LvB-dagrapport importeren
  vc.py sync [--backfill N]           gegevens ophalen bij de marketplaces
  vc.py test-api                      controleer de bol API-gegevens
  vc.py weekmail [--niet-versturen]   weekadvies vastleggen en mailen
  vc.py gebruiker <naam> <rol>        gebruiker aanmaken of wachtwoord wijzigen (rol: beheer of logistiek)
  vc.py reservekopie                  kopie van de database maken (14 bewaard)
  vc.py serve [--port 8768]           dashboard starten
"""
from __future__ import annotations

import argparse
import getpass
import sys

from voorraad import auth, config, db


def main() -> int:
    ap = argparse.ArgumentParser(description="Voorraadchecker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("masterdata")
    p.add_argument("bestanden", nargs="+")
    p.add_argument("--bundels", action="append", default=[])
    p = sub.add_parser("rapport")
    p.add_argument("bestand")
    p.add_argument("--kanaal", default="bol")
    p = sub.add_parser("sync")
    p.add_argument("--kanaal")
    p.add_argument("--backfill", type=int, default=0, help="eenmalig N dagen orderhistorie ophalen")
    sub.add_parser("test-api")
    p = sub.add_parser("weekmail")
    p.add_argument("--niet-versturen", action="store_true")
    p = sub.add_parser("gebruiker")
    p.add_argument("naam")
    p.add_argument("rol", choices=auth.ROLES)
    p.add_argument("--wachtwoord-stdin", action="store_true")
    p = sub.add_parser("reservekopie")
    p.add_argument("--bewaar", type=int, default=14, help="aantal kopieen dat bewaard blijft")
    p = sub.add_parser("serve")
    p.add_argument("--host", default=config.get("VC_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(config.get("VC_PORT", "8768")))
    args = ap.parse_args()

    if args.cmd == "serve":
        from voorraad import server
        server.serve(args.host, args.port)
        return 0

    conn = db.connect()
    db.init(conn)
    if args.cmd == "init":
        print("Database staat klaar in %s" % config.DB_PATH)
    elif args.cmd == "masterdata":
        from voorraad import masterdata
        n = masterdata.import_files(conn, args.bestanden, args.bundels)
        print("%d regels verwerkt" % n)
    elif args.cmd == "rapport":
        from voorraad import report_import
        print(report_import.import_report(conn, args.bestand, args.kanaal))
    elif args.cmd == "sync":
        from voorraad import sync
        return 0 if sync.run(conn, args.kanaal, args.backfill) else 1
    elif args.cmd == "test-api":
        from voorraad.channels import ChannelError
        from voorraad.channels.bol import BolChannel
        bol = BolChannel()
        if not bol.configured():
            print("BOL_CLIENT_ID of BOL_CLIENT_SECRET ontbreekt in config.env")
            return 1
        try:
            data = bol._get("inventory", "/inventory", {"page": 1})
        except ChannelError as e:
            print("Mislukt: %s" % e)
            return 1
        items = data.get("inventory") or []
        print("Gelukt: bol geeft antwoord. Eerste pagina bevat %d LvB-artikelen." % len(items))
    elif args.cmd == "weekmail":
        from voorraad import mailer
        return 0 if mailer.weekly(conn, send=not args.niet_versturen) else 1
    elif args.cmd == "reservekopie":
        import sqlite3
        from datetime import date
        folder = config.DATA_DIR / "reservekopie"
        folder.mkdir(exist_ok=True)
        target = folder / ("voorraad-%s.db" % date.today().isoformat())
        dest = sqlite3.connect(str(target))
        conn.backup(dest)
        ok = dest.execute("PRAGMA integrity_check").fetchone()[0]
        dest.close()
        target.chmod(0o600)
        if ok != "ok":
            print("FOUT: reservekopie %s is beschadigd (%s)" % (target.name, ok))
            return 1
        copies = sorted(folder.glob("voorraad-*.db"))
        for old in copies[:-args.bewaar]:
            old.unlink()
        print("Reservekopie gemaakt: %s (%d bewaard)" % (target.name, min(len(copies), args.bewaar)))
    elif args.cmd == "gebruiker":
        if args.wachtwoord_stdin:
            pw = sys.stdin.readline().rstrip("\n")
        else:
            pw = getpass.getpass("Wachtwoord (minstens 10 tekens): ")
            if pw != getpass.getpass("Herhaal wachtwoord: "):
                print("De wachtwoorden zijn niet gelijk")
                return 1
        try:
            auth.set_user(conn, args.naam, pw, args.rol)
        except ValueError as e:
            print(e)
            return 1
        print("Gebruiker %s (%s) opgeslagen" % (args.naam.lower(), args.rol))
    return 0


if __name__ == "__main__":
    sys.exit(main())
