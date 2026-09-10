#!/usr/bin/env python3
"""
patch_historical_urls.py

Two operations on data/aprobacion_presidencial.csv:

1. URL + n_muestra backfill — for existing Piñera/Boric rows that have a
   matching Wikipedia entry with a source URL or sample size, fill in those
   blank fields.

2. Missing-row insert — 60 rows present on the Piñera / Boric Wikipedia
   approval-poll pages but absent from the CSV (DecideChile omitted them)
   are appended, with full Wikipedia metadata.

After patching, the CSV is re-sorted by fecha_informe (oldest first) and
IDs are reassigned 1-N.

HISTORICAL RECORD — already run once (2026-09), as one step of the Piñera/
Boric backfill (see README.md → 'Cobertura histórica'). Both presidencies
are closed, so there is no new Wikipedia data for this script to find; it
is NOT part of the automated sync routine. Re-running it with --apply would
re-sort and renumber the ENTIRE live CSV (including all current-president
rows) for no benefit — use with caution, and prefer a dry-run first.

Usage
-----
    python scripts/patch_historical_urls.py          # preview (dry-run)
    python scripts/patch_historical_urls.py --apply  # write changes
"""

import argparse
import csv
import io
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT     = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "aprobacion_presidencial.csv"

UA = "AprobacionSyncBot/1.0 (https://github.com/cbuzeta/aprobacion-presidencial; cbuzeta@gmail.com)"
_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", UA)]

WIKI_PAGES = {
    "Sebastián Piñera": (
        "Anexo:Encuestas_de_aprobaci%C3%B3n_del_segundo_gobierno_de_Sebasti%C3%A1n_Pi%C3%B1era"
    ),
    "Gabriel Boric": (
        "Anexo:Encuestas_de_aprobaci%C3%B3n_del_gobierno_de_Gabriel_Boric"
    ),
}

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

CSV_FIELDS = [
    "id", "fecha_informe", "fecha_inicio_campo", "fecha_fin_campo",
    "presidente", "encuestadora", "producto",
    "aprueba_pct", "desaprueba_pct", "nr_pct", "n_muestra",
    "aprueba_gob_pct", "desaprueba_gob_pct", "nr_gob_pct", "neto_gob",
    "modalidad", "n_informe", "excluir", "url_fuente",
]

PRODUCTO_MAP = {
    "Cadem":               "Plaza Pública",
    "Criteria":            "Agenda Criteria",
    "Activa Research":     "Pulso Ciudadano",
    "TuInfluyes.com":      "DataInfluye",
    "CEP":                 "Encuesta CEP",
    "Feedback Research":   "Estudio Feedback",
    "Research Chile":      "Research Chile",
    "Panel Ciudadano-UDD": "Panel Ciudadano",
    "CERC-MORI":           "CERC-MORI",
    "MORI-Fiel":           "MORI-Fiel",
    "Black & White":       "B&W",
    "GfK Adimark":         "GfK Adimark",
    "MORI":                "MORI",
    "Ipsos":               "Ipsos",
    "Collect GfK":         "Collect GfK",
    "Imaginacción":        "Imaginacción",
    "Opina":               "Opina",
    "FLACSO":              "FLACSO",
    "Demoscópica":         "Demoscópica",
}


# ── Wikipedia parsing ─────────────────────────────────────────────────────────

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


def _extract_url(line: str) -> str:
    m = re.search(r"\|url=([^|}\s]+)", line)
    return m.group(1).strip() if m else ""


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


def fetch_wiki_rows(presidente: str, title: str) -> list[dict]:
    url = f"https://es.wikipedia.org/w/index.php?title={title}&action=raw"
    print(f"  Fetching {presidente}…", end=" ", flush=True)
    wikitext = _opener.open(url, timeout=20).read().decode("utf-8")
    print(f"{len(wikitext):,} chars")

    rows = []
    for cells in _parse_table(wikitext):
        if len(cells) < 7:
            continue
        raw0 = cells[0]
        name = re.sub(r"<ref[^>]*/?>.*?</ref>", "", raw0[1:], flags=re.DOTALL)
        name = re.sub(r"<ref[^>]*/>", "", name).strip()
        url_src = _extract_url(raw0)
        enc = ENC_MAP.get(name, name)
        ini, fin = _parse_date(_cell_value(cells[1]))
        n = _cell_value(cells[2]).replace(".", "").replace(",", "")
        a  = _pct(cells[3]) if len(cells) > 3 else ""
        d  = _pct(cells[4]) if len(cells) > 4 else ""
        nr = _pct(cells[6]) if len(cells) > 6 else ""
        rows.append({
            "encuestadora":   enc,
            "wiki_name":      name,
            "fecha_inicio":   ini,
            "fecha_fin":      fin,
            "aprueba":        a,
            "desaprueba":     d,
            "nr":             nr,
            "n":              n,
            "url":            url_src,
            "presidente":     presidente,
        })
    return rows


# ── CSV helpers ───────────────────────────────────────────────────────────────

def load_csv() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows: list[dict]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def _dmy(s: str):
    try:
        return datetime.strptime(s.strip(), "%d-%m-%Y")
    except ValueError:
        return None


def find_match(wrow: dict, csv_rows: list[dict]):
    wfin = _dmy(wrow["fecha_fin"])
    if not wfin:
        return None
    for r in csv_rows:
        if r["encuestadora"] != wrow["encuestadora"]:
            continue
        cfin = _dmy(r["fecha_fin_campo"]) or _dmy(r["fecha_informe"])
        if not cfin:
            continue
        if abs((cfin - wfin).days) > 2:
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run preview)")
    args = ap.parse_args()
    dry = not args.apply

    print("Fetching Wikipedia tables…")
    all_wiki: list[dict] = []
    for presidente, title in WIKI_PAGES.items():
        all_wiki.extend(fetch_wiki_rows(presidente, title))
    print(f"  Total wiki rows: {len(all_wiki)}")

    print("\nLoading CSV…")
    rows = load_csv()
    hist = [r for r in rows if r["presidente"] in ("Sebastián Piñera", "Gabriel Boric")]
    print(f"  Total rows: {len(rows)} | Historical: {len(hist)}")

    url_updates: dict[str, dict] = {}
    missing_wiki: list[dict] = []

    for wrow in all_wiki:
        m = find_match(wrow, hist)
        if m is None:
            missing_wiki.append(wrow)
        else:
            updates = {}
            if wrow["url"] and not m.get("url_fuente"):
                updates["url_fuente"] = wrow["url"]
            if wrow["n"] and not m.get("n_muestra"):
                updates["n_muestra"] = wrow["n"]
            if updates:
                url_updates[m["id"]] = updates

    print(f"\n{'[DRY-RUN] ' if dry else ''}Summary:")
    print(f"  Rows to backfill (URL / n_muestra): {len(url_updates)}")
    print(f"  Rows to insert (Wiki not in CSV):   {len(missing_wiki)}")

    # Preview missing rows
    print(f"\n  {'[DRY-RUN] ' if dry else ''}New rows to insert:")
    for w in missing_wiki:
        print(f"    {w['presidente'][:5]} | {w['fecha_fin']:12} | "
              f"{w['encuestadora']:22} | A={w['aprueba']:5} D={w['desaprueba']:5} "
              f"n={w['n']:5} | {w['url'][:60]}")

    if dry:
        print("\n[dry-run] Nothing written. Re-run with --apply to apply changes.")
        return

    # ── Apply URL / n backfills ───────────────────────────────────────────────
    backfilled = 0
    for r in rows:
        if r["id"] in url_updates:
            for k, v in url_updates[r["id"]].items():
                r[k] = v
            backfilled += 1

    # ── Insert missing rows ───────────────────────────────────────────────────
    new_rows = []
    for w in missing_wiki:
        enc = w["encuestadora"]
        nr_pct = ""
        try:
            nr_pct = str(max(0, round(100 - float(w["aprueba"]) - float(w["desaprueba"]), 1)))
        except (ValueError, TypeError):
            pass
        new_rows.append({
            "id":                  "",  # assigned after sort
            "fecha_informe":       w["fecha_fin"],
            "fecha_inicio_campo":  w["fecha_inicio"],
            "fecha_fin_campo":     w["fecha_fin"],
            "presidente":          w["presidente"],
            "encuestadora":        enc,
            "producto":            PRODUCTO_MAP.get(enc, enc),
            "aprueba_pct":         w["aprueba"],
            "desaprueba_pct":      w["desaprueba"],
            "nr_pct":              w["nr"] or nr_pct,
            "n_muestra":           w["n"],
            "aprueba_gob_pct":     "",
            "desaprueba_gob_pct":  "",
            "nr_gob_pct":          "",
            "neto_gob":            "",
            "modalidad":           "online",
            "n_informe":           "",
            "excluir":             "0",
            "url_fuente":          w["url"],
        })

    rows.extend(new_rows)

    # ── Re-sort and reassign IDs ──────────────────────────────────────────────
    rows.sort(key=lambda r: (_dmy(r["fecha_informe"]) or datetime.max))
    for i, r in enumerate(rows, 1):
        r["id"] = str(i)

    save_csv(rows)
    print(f"\n✓ Backfilled {backfilled} rows.")
    print(f"✓ Inserted {len(new_rows)} new rows.")
    print(f"✓ Total rows: {len(rows)}, sorted oldest→newest, IDs 1–{len(rows)}.")


if __name__ == "__main__":
    main()
