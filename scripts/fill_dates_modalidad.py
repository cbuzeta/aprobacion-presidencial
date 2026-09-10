#!/usr/bin/env python3
"""
fill_dates_modalidad.py

Two fill passes on data/aprobacion_presidencial.csv:

1. fecha_inicio_campo  — matched from cached Wikipedia wikitext for Piñera/Boric rows.
2. modalidad           — inferred from known pollster methodology (all administrations).

HISTORICAL RECORD — already run once (2026-09), as one step of the Piñera/
Boric backfill (see README.md → 'Cobertura histórica'). Not part of the
automated sync routine. Safe to re-run (only fills currently-blank fields)
but there's nothing left for it to find for the closed presidencies.
"""

import csv
import io
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT     = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "aprobacion_presidencial.csv"
WIKI_PINERA = ROOT / "data" / ".wiki_pinera.txt"
WIKI_BORIC  = ROOT / "data" / ".wiki_boric.txt"

# ── Modalidad rules ───────────────────────────────────────────────────────────
# Source: each pollster's published methodology notes
MODALIDAD_FIXED = {
    "Cadem":               "online",
    "Criteria":            "online",
    "TuInfluyes.com":      "online",
    "Activa Research":     "online",
    "Panel Ciudadano-UDD": "online",
    "Research Chile":      "online",
    "Black & White":       "online",
    "AtlasIntel":          "online",
    "CEP":                 "presencial",
    "CERC-MORI":           "telefónica",
    "MORI":                "telefónica",
    "MORI-Fiel":           "telefónica",
    "Demoscópica":         "telefónica",
    "Ipsos":               "telefónica",
    "Opina":               "telefónica",
    "FLACSO":              "presencial",
    "Imaginacción":        "telefónica",
    "Collect GfK":         "presencial",
}

# GfK Adimark shifted from presencial to online around 2020
def _modalidad_gfk(fecha: str) -> str:
    try:
        yr = int(fecha.split("-")[-1])
        return "online" if yr >= 2020 else "presencial"
    except (ValueError, IndexError):
        return "presencial"

# Feedback shifted to online around 2021
def _modalidad_feedback(fecha: str) -> str:
    try:
        yr = int(fecha.split("-")[-1])
        return "online" if yr >= 2021 else "telefónica"
    except (ValueError, IndexError):
        return "telefónica"


def resolve_modalidad(enc: str, fecha: str) -> str | None:
    if enc == "GfK Adimark":
        return _modalidad_gfk(fecha)
    if enc == "Feedback Research":
        return _modalidad_feedback(fecha)
    return MODALIDAD_FIXED.get(enc)


# ── Wikipedia date parsing (reused from patch_historical_urls.py) ─────────────
MONTH_ES = {
    "Ene": "01", "Feb": "02", "Mar": "03", "Abr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Ago": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dic": "12",
}

ENC_MAP = {
    "Cadem":           "Cadem",
    "Criteria":        "Criteria",
    "Activa":          "Activa Research",
    "Activa119b":      "Activa Research",
    "Data Influye":    "TuInfluyes.com",
    "CEP":             "CEP",
    "Feedback":        "Feedback Research",
    "Research Chile":  "Research Chile",
    "Panel Ciudadano": "Panel Ciudadano-UDD",
    "CERC-MORI":       "CERC-MORI",
    "MORI-Fiel":       "MORI-Fiel",
    "Black & White":   "Black & White",
    "Adimark":         "GfK Adimark",
    "MORI":            "MORI",
    "Ipsos":           "Ipsos",
    "Collect":         "Collect GfK",
    "Imaginacción":    "Imaginacción",
    "Opina":           "Opina",
    "FLACSO":          "FLACSO",
    "Demoscópica":     "Demoscópica",
}


def _cell_value(line: str) -> str:
    content = line[1:]
    m = re.match(r'^\s*(?:bgcolor|style)="[^"]*"\s*\|(.*)', content)
    if m:
        content = m.group(1)
    content = re.sub(r"<ref[^>]*/?>.*?</ref>", "", content, flags=re.DOTALL)
    content = re.sub(r"<ref[^>]*/>", "", content)
    content = content.replace("'''", "").replace("''", "")
    content = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", content)
    return content.strip()


def _parse_date(s: str) -> tuple[str, str]:
    s = s.strip().replace("–", "-").replace("—", "-")
    m = re.match(r"(\d+)\s+(\w+)\s*-\s*(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        return (
            f"{d1.zfill(2)}-{MONTH_ES.get(mo1, '???')}-{yr}",
            f"{d2.zfill(2)}-{MONTH_ES.get(mo2, '???')}-{yr}",
        )
    m = re.match(r"(\d+)\s*-\s*(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d1, d2, mo, yr = m.groups()
        mn = MONTH_ES.get(mo, "???")
        return f"{d1.zfill(2)}-{mn}-{yr}", f"{d2.zfill(2)}-{mn}-{yr}"
    m = re.match(r"(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d, mo, yr = m.groups()
        date = f"{d.zfill(2)}-{MONTH_ES.get(mo, '???')}-{yr}"
        return date, date
    return "", ""


def _pct(line: str) -> str:
    v = _cell_value(line).replace("%", "").replace(",", ".").strip()
    return "" if v in ("—", "-", "") else v


def _parse_table(wikitext: str) -> list[list[str]]:
    rows, cells, in_row = [], [], False
    for line in wikitext.splitlines():
        if line.startswith("|-"):
            if in_row and cells:
                rows.append(cells)
            cells, in_row = [], True
        elif line.startswith("|}"):
            if in_row and cells:
                rows.append(cells)
            in_row = False
        elif in_row and line.startswith("|"):
            cells.append(line)
    return rows


def load_wiki_rows(path: Path, presidente: str) -> list[dict]:
    wikitext = path.read_text(encoding="utf-8")
    rows = []
    for cells in _parse_table(wikitext):
        if len(cells) < 7:
            continue
        raw0 = cells[0]
        name = re.sub(r"<ref[^>]*/?>.*?</ref>", "", raw0[1:], flags=re.DOTALL)
        name = re.sub(r"<ref[^>]*/>", "", name).strip()
        enc = ENC_MAP.get(name, name)
        ini, fin = _parse_date(_cell_value(cells[1]))
        a = _pct(cells[3]) if len(cells) > 3 else ""
        rows.append({
            "encuestadora": enc,
            "fecha_inicio":  ini,
            "fecha_fin":     fin,
            "aprueba":       a,
            "presidente":    presidente,
        })
    return rows


def _dmy(s: str):
    try:
        return datetime.strptime(s.strip(), "%d-%m-%Y")
    except ValueError:
        return None


def find_wiki_match(wrow: dict, csv_rows: list[dict]) -> dict | None:
    wfin = _dmy(wrow["fecha_fin"])
    if not wfin:
        return None
    for r in csv_rows:
        if r["encuestadora"] != wrow["encuestadora"]:
            continue
        cfin = _dmy(r["fecha_fin_campo"]) or _dmy(r["fecha_informe"])
        if not cfin:
            continue
        if abs((cfin - wfin).days) > 5:
            continue
        try:
            if abs(float(r["aprueba_pct"]) - float(wrow["aprueba"])) > 1.5:
                continue
        except (ValueError, TypeError):
            pass
        return r
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    fields = list(rows[0].keys())

    # Index for fast lookup
    by_id = {r["id"]: r for r in rows}

    # ── Pass 1: fecha_inicio_campo from Wikipedia ─────────────────────────────
    print("Loading Wikipedia caches…")
    wiki_rows: list[dict] = []
    wiki_rows.extend(load_wiki_rows(WIKI_PINERA, "Sebastián Piñera"))
    wiki_rows.extend(load_wiki_rows(WIKI_BORIC,  "Gabriel Boric"))
    print(f"  Wiki rows: {len(wiki_rows)}")

    hist = [r for r in rows if r["presidente"] in ("Sebastián Piñera", "Gabriel Boric")]

    date_filled = 0
    date_skipped = 0
    for wrow in wiki_rows:
        if not wrow["fecha_inicio"]:
            continue
        m = find_wiki_match(wrow, hist)
        if m and not m["fecha_inicio_campo"]:
            m["fecha_inicio_campo"] = wrow["fecha_inicio"]
            date_filled += 1
        elif m and m["fecha_inicio_campo"]:
            date_skipped += 1

    print(f"  fecha_inicio_campo filled: {date_filled}  (already had: {date_skipped})")

    # ── Pass 2: modalidad ─────────────────────────────────────────────────────
    mod_filled = 0
    mod_unknown = {}
    for r in rows:
        if r["modalidad"]:
            continue
        val = resolve_modalidad(r["encuestadora"], r["fecha_informe"])
        if val:
            r["modalidad"] = val
            mod_filled += 1
        else:
            mod_unknown[r["encuestadora"]] = mod_unknown.get(r["encuestadora"], 0) + 1

    print(f"\n  modalidad filled: {mod_filled}")
    if mod_unknown:
        print("  Still unknown (no rule):")
        for enc, n in sorted(mod_unknown.items()):
            print(f"    {enc:25} {n}")

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    still_missing_inicio = sum(1 for r in rows if not r["fecha_inicio_campo"])
    still_missing_mod    = sum(1 for r in rows if not r["modalidad"])
    print(f"\nSaved {len(rows)} rows.")
    print(f"  Still missing fecha_inicio_campo: {still_missing_inicio}")
    print(f"  Still missing modalidad:          {still_missing_mod}")


if __name__ == "__main__":
    main()
