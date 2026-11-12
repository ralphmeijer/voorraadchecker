#!/bin/bash
# Zet de laatste versie op de VPS: eerst naar GitHub, daarna haalt de VPS die op en herstart het dashboard.
# Database en config.env op de VPS blijven ongemoeid (ze staan niet in git).
set -e
cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain)" ]; then
  echo "Er zijn wijzigingen die nog niet zijn vastgelegd (git commit). Leg ze eerst vast."
  exit 1
fi
git push origin main
ssh ralphmeijer@141.138.137.119 'cd voorraadchecker && git pull --ff-only && sudo systemctl restart voorraadchecker && sleep 2 && systemctl is-active voorraadchecker'
