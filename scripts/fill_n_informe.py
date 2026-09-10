#!/usr/bin/env python3
"""fill_n_informe.py — Extract n_informe from url_fuente for blank rows.

HISTORICAL RECORD — already run once (2026-09), as one step of the Piñera/
Boric backfill (see README.md → 'Cobertura histórica'). Not part of the
automated sync routine (current-president n_informe derivation lives in
wiki_sync.py's _derive_n_informe). Safe to re-run (only fills currently-blank
n_informe fields) but there's nothing new left for it to find.
"""

import csv
import io
import re
import sys
import urllib.parse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CSV_PATH = Path(__file__).parent.parent / "data" / "aprobacion_presidencial.csv"

# ── Month lookup ──────────────────────────────────────────────────────────────
_M = {
    "enero": "Enero", "febrero": "Febrero", "marzo": "Marzo", "abril": "Abril",
    "mayo": "Mayo", "junio": "Junio", "julio": "Julio", "agosto": "Agosto",
    "septiembre": "Septiembre", "octubre": "Octubre",
    "noviembre": "Noviembre", "diciembre": "Diciembre",
    "ene": "Enero", "feb": "Febrero", "mar": "Marzo", "abr": "Abril",
    "jun": "Junio", "jul": "Julio", "ago": "Agosto",
    "sep": "Septiembre", "oct": "Octubre", "nov": "Noviembre", "dic": "Diciembre",
}

def _mo(s: str) -> str | None:
    return _M.get(s.lower().rstrip("."))

def _seg(url: str) -> str:
    """Last path segment, URL-decoded, no file extension."""
    s = urllib.parse.unquote(url.split("?")[0])
    s = s.split("/")[-1]
    return re.sub(r"\.(pdf|html?)$", "", s, flags=re.I)

def _yr_from_date(fecha: str) -> str:
    return fecha.split("-")[-1] if fecha else ""


# ── Pollster extractors ───────────────────────────────────────────────────────

def _cadem(url: str, fecha: str) -> str | None:
    s = _seg(url)
    # Specials without a track number (e.g. Especial-Cuenta-Publica-2025)
    if re.search(r"especial", s, re.I) and not re.search(r"track", s, re.I):
        return None
    # 3-digit standalone number = track number
    m = re.search(r"(?<!\d)(\d{3})(?!\d)", s)
    return m.group(1) if m else None


def _criteria(url: str, fecha: str) -> str | None:
    s = _seg(url)
    yr_fb = _yr_from_date(fecha)

    # 1. _DD[_de]_Mes_YYYY   e.g. _15_Marzo_2026, _27_de_Noviembre_2025
    m = re.search(r"(?i)_(\d{1,2})(?:_de)?_([a-z\xe1\xe9\xed\xf3\xfa]+)_(\d{4})", s)
    if m:
        d, mon, yr = m.groups()
        cap = _mo(mon)
        return f"{int(d)} de {cap} {yr}" if cap else None

    # 2. _Mes_YYYY_M1..M4   e.g. _Julio_2025_M2
    m = re.search(r"(?i)_([a-z\xe1\xe9\xed\xf3\xfa]+)_(\d{4})_(M\d)\b", s)
    if m:
        mon, yr, med = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr} {med}" if cap else None

    # 3. Segunda_Medicion / 2da_Medicion   e.g. Segunda_Medicion_Abril_2025
    m = re.search(
        r"(?i)(?:Segunda_Medicion|2da_Medicion)_([a-z\xe1\xe9\xed\xf3\xfa]+)_(\d{4})", s
    )
    if m:
        mon, yr = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr} M2" if cap else None

    # 4. Agenda_Criteria_Mes_YYYY / ACC-Mes-YYYY / AG-Mes-YYYY
    m = re.search(
        r"(?i)(?:Agenda_Criteria|ACC|AG)[-_]([a-z\xe1\xe9\xed\xf3\xfa]+)[-_](\d{4})", s
    )
    if m:
        mon, yr = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr}" if cap else None

    # 5. Old: Agenda-Mes2018 (no separator before year)
    m = re.search(r"(?i)Agenda-([a-z\xe1\xe9\xed\xf3\xfa]+)(\d{4})", s)
    if m:
        mon, yr = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr}" if cap else None

    # 6. Generic Mes_YYYY fallback
    m = re.search(r"(?i)([a-z\xe1\xe9\xed\xf3\xfa]{5,})[-_](\d{4})", s)
    if m:
        mon, yr = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr}" if cap else None

    return None


def _tuinfluyes(url: str, fecha: str) -> str | None:
    yr_fb = _yr_from_date(fecha)

    # paneltuinfluyes.com/e/mes-yyyy
    m = re.search(r"paneltuinfluyes\.com/e/([a-z\xe1\xe9\xed\xf3\xfa]+)-(\d{4})", url, re.I)
    if m:
        mon, yr = m.groups()
        cap = _mo(mon)
        return f"{cap} {yr}" if cap else None

    s = _seg(url).upper()

    if "ESPECIAL" in s:
        return None

    # ESTUDIO_TUINFLUYES_MES[_PLEBISCITO][_YYYY]
    m = re.search(r"TUINFLUYES[-_]([A-Z]+)(?:[-_]PLEBISCITO)?(?:[-_](\d{4}))?", s)
    if m:
        mon_str, yr = m.groups()
        cap = _mo(mon_str.lower())
        yr = yr or yr_fb
        if cap:
            return f"{cap} {yr}" if yr else cap

    return None


def _activa(url: str, fecha: str) -> str | None:
    yr_fb = _yr_from_date(fecha)
    s_raw = _seg(url)

    # Skip hash filenames
    if re.match(r"^[a-f0-9]{32}$", s_raw, re.I):
        return None

    s = s_raw.upper()

    # Year from 6-digit prefix: 220868 → 2022, 260978 → 2026
    yr: str | None = None
    pfx = re.match(r"^(\d{2})\d{4}", s)
    if pfx:
        yr = "20" + pfx.group(1)

    # Quarter from Q1/Q2 or Primera/Segunda Quincena
    q: str | None = None
    if re.search(r"PRIMERA.QUINCENA|[-_]Q1(?!\d)", s, re.I):
        q = "Q1"
    elif re.search(r"SEGUNDA.QUINCENA|[-_]Q2(?!\d)", s, re.I):
        q = "Q2"

    # Month
    mm = re.search(
        r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO"
        r"|SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)",
        s,
    )
    if not mm:
        return None
    cap = _mo(mm.group(1).lower())

    # Year fallback: 4-digit in filename
    if not yr:
        m4 = re.search(r"(\d{4})", s_raw)
        if m4 and 2015 <= int(m4.group(1)) <= 2030:
            yr = m4.group(1)
    if not yr:
        yr = yr_fb

    parts = [cap]
    if yr:
        parts.append(yr)
    if q:
        parts.append(q)
    return " ".join(parts)


def _gfk_adimark(url: str, fecha: str) -> str | None:
    yr_fb = _yr_from_date(fecha)
    s = _seg(url).lower()
    mm = re.search(
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre"
        r"|noviembre|diciembre|ene|feb|mar|abr|jun|jul|ago|sep|oct|nov|dic)",
        s,
    )
    if not mm:
        return None
    cap = _mo(mm.group(1))
    m4 = re.search(r"(\d{4})", s)
    if m4:
        return f"{cap} {m4.group(1)}"
    m2 = re.search(r"[-_](\d{2})(?:\b|$)", s)
    if m2:
        return f"{cap} 20{m2.group(1)}"
    return f"{cap} {yr_fb}" if yr_fb else cap


def _research_chile(url: str, fecha: str) -> str | None:
    yr_fb = _yr_from_date(fecha)
    s = _seg(url).lower()
    mm = re.search(
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre"
        r"|noviembre|diciembre)",
        s,
    )
    if not mm:
        return None
    cap = _mo(mm.group(1))
    m4 = re.search(r"(\d{4})", s)
    yr = m4.group(1) if m4 else yr_fb
    return f"{cap} {yr}" if yr else cap


EXTRACTORS = {
    "Cadem":           _cadem,
    "Criteria":        _criteria,
    "TuInfluyes.com":  _tuinfluyes,
    "Activa Research": _activa,
    "GfK Adimark":     _gfk_adimark,
    "Research Chile":  _research_chile,
}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    fields = list(rows[0].keys())

    from collections import defaultdict
    filled: defaultdict[str, int] = defaultdict(int)
    could_not: defaultdict[str, int] = defaultdict(int)

    for r in rows:
        if r["n_informe"] or not r["url_fuente"]:
            continue
        fn = EXTRACTORS.get(r["encuestadora"])
        if not fn:
            continue
        val = fn(r["url_fuente"], r["fecha_informe"])
        if val:
            r["n_informe"] = val
            filled[r["encuestadora"]] += 1
        else:
            could_not[r["encuestadora"]] += 1

    print("Filled:")
    total = 0
    for enc, n in sorted(filled.items()):
        print(f"  {enc:24} {n}")
        total += n
    print(f"  {'TOTAL':24} {total}")

    if could_not:
        print("\nCould not extract (URL has no recognisable pattern):")
        for enc, n in sorted(could_not.items()):
            print(f"  {enc:24} {n}")

    # Spot-check sample
    print("\nSample (3 per pollster):")
    seen: defaultdict[str, list] = defaultdict(list)
    for r in rows:
        if r["n_informe"] and r["encuestadora"] in EXTRACTORS:
            seen[r["encuestadora"]].append(r["n_informe"])
    for enc in sorted(seen):
        vals = seen[enc]
        print(f"  {enc}: first={vals[0]}  mid={vals[len(vals)//2]}  last={vals[-1]}")

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSaved {len(rows)} rows.")


if __name__ == "__main__":
    main()
