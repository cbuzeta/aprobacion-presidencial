#!/usr/bin/env python3
"""
wiki_sync.py — sync aprobacion_presidencial.csv from Spanish Wikipedia.

Detects changes to the Kast government approval poll table and appends new
rows to the CSV.  Fields not available on Wikipedia (n_informe, exact
fecha_informe) are left blank for manual completion.

Usage
-----
    python wiki_sync.py            # check and sync if page was updated
    python wiki_sync.py --force    # sync regardless of revision change
    python wiki_sync.py --dry-run  # preview without writing anything
"""

import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
CSV_PATH   = ROOT / "data" / "aprobacion_presidencial.csv"
STATE_PATH = ROOT / "data" / ".wiki_state.json"

# ── Wikipedia ─────────────────────────────────────────────────────────────────
WIKI_TITLE = "Anexo:Encuestas_de_aprobación_del_gobierno_de_José_Antonio_Kast"
WIKI_API   = "https://es.wikipedia.org/w/api.php"
WIKI_RAW   = (
    "https://es.wikipedia.org/w/index.php"
    f"?title={urllib.parse.quote(WIKI_TITLE)}&action=raw"
)
UA = "AprobacionSyncBot/1.0 (https://github.com/cbuzeta/aprobacion-presidencial; cbuzeta@gmail.com)"

_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", UA)]

# ── pollster lookup ───────────────────────────────────────────────────────────
# Maps Wikipedia display name → CSV fields that can't be derived from the table.
# Add new entries here whenever a new pollster appears on Wikipedia.
POLLSTERS: dict[str, dict] = {
    "Cadem":           {"encuestadora": "Cadem",               "producto": "Plaza Pública",     "modalidad": "online", "excluir": 0},
    "Criteria":        {"encuestadora": "Criteria",            "producto": "Agenda Criteria",   "modalidad": "online", "excluir": 0},
    "Activa":          {"encuestadora": "Activa Research",     "producto": "Pulso Ciudadano",   "modalidad": "online", "excluir": 0},
    "Panel Ciudadano": {"encuestadora": "Panel Ciudadano-UDD", "producto": "Panel Ciudadano",   "modalidad": "online", "excluir": 0},
    "Data Influye":    {"encuestadora": "TuInfluyes.com",      "producto": "DataInfluye",       "modalidad": "online", "excluir": 0},
    "Black & White":   {"encuestadora": "Black & White",       "producto": "Black & White",     "modalidad": "online",  "excluir": 0},
    "AtlasIntel":      {"encuestadora": "AtlasIntel",          "producto": "Latam Pulse Chile", "modalidad": "online",  "excluir": 0},
    "CEP":             {"encuestadora": "CEP",                 "producto": "Encuesta CEP",      "modalidad": "offline", "excluir": 0},
}

# Rows that exist on Wikipedia but must never be imported.
# Key matches _key(): (encuestadora, fecha_inicio_campo, aprueba_pct, desaprueba_pct)
# Panel Ciudadano Apr-16-2026: "after" wave of a before/after experiment, not a standalone poll.
KNOWN_FALSE_POSITIVES: set[tuple] = {
    ("Panel Ciudadano-UDD", "16-04-2026", "39", "49"),
}

MONTH_ES: dict[str, str] = {
    "Ene": "01", "Feb": "02", "Mar": "03", "Abr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Ago": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dic": "12",
}

CSV_FIELDS = [
    "id", "fecha_informe", "fecha_inicio_campo", "fecha_fin_campo",
    "presidente", "encuestadora", "producto",
    "aprueba_pct", "desaprueba_pct", "nr_pct", "n_muestra",
    "aprueba_gob_pct", "desaprueba_gob_pct", "nr_gob_pct", "neto_gob",
    "modalidad", "n_informe", "excluir", "url_fuente",
]


# ── Wikipedia helpers ─────────────────────────────────────────────────────────

def _get(url: str) -> bytes:
    with _opener.open(url, timeout=15) as r:
        return r.read()


def get_wiki_revision() -> tuple[int, str]:
    """Return (revid, iso_timestamp) of the latest page revision."""
    params = urllib.parse.urlencode({
        "action": "query", "prop": "revisions",
        "titles": WIKI_TITLE, "rvprop": "ids|timestamp", "format": "json",
    })
    data = json.loads(_get(f"{WIKI_API}?{params}"))
    page = next(iter(data["query"]["pages"].values()))
    rev  = page["revisions"][0]
    return rev["revid"], rev["timestamp"]


def fetch_wikitext() -> str:
    return _get(WIKI_RAW).decode("utf-8")


# ── state ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"revid": None}


def save_state(revid: int, timestamp: str) -> None:
    STATE_PATH.write_text(
        json.dumps({"revid": revid, "timestamp": timestamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── wikitext parsing ──────────────────────────────────────────────────────────

def _cell_value(line: str) -> str:
    """Return the display value of a wikitext cell line, stripping all markup."""
    content = line[1:]  # drop leading |
    # Handle "| bgcolor="…" |value" and "| style="…" |value" patterns
    m = re.match(r'^\s*(?:bgcolor|style)="[^"]*"\s*\|(.*)', content)
    if m:
        content = m.group(1)
    # Strip <ref>…</ref> blocks (including self-closing)
    content = re.sub(r"<ref[^>]*/?>.*?</ref>", "", content, flags=re.DOTALL)
    content = re.sub(r"<ref[^>]*/>", "", content)
    # Strip bold/italic markers and wikilinks
    content = content.replace("'''", "").replace("''", "")
    content = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", content)
    return content.strip()


def _extract_url(line: str) -> str:
    """Extract the first url= value from a <ref>{{Cita web|…}}</ref> block."""
    m = re.search(r"\|url=([^|}\s]+)", line)
    return m.group(1).strip() if m else ""


_REF_DEF_RE = re.compile(r'<ref name="([^"]+)">(\{\{Cita web\|.*?\}\})</ref>')
_REF_USE_RE = re.compile(r'<ref name="([^"]+)"\s*/>')
_REF_INLINE_RE = re.compile(r"<ref[^>]*>(\{\{Cita web\|.*?\}\})</ref>", re.DOTALL)


def _build_ref_index(wikitext: str) -> dict[str, str]:
    """Map named-reference id -> its {{Cita web|…}} text, so a row whose cell
    only has <ref name="X" /> (Wikipedia reusing an earlier citation) can
    still be traced back to the original citation's fields."""
    return {m.group(1): m.group(2) for m in _REF_DEF_RE.finditer(wikitext)}


def _get_citation(raw0: str, ref_index: dict) -> str:
    """Return this cell's {{Cita web|…}} text, resolving a self-closing
    named reference against ref_index if the cell doesn't define one inline."""
    m = _REF_USE_RE.search(raw0)
    if m:
        return ref_index.get(m.group(1), "")
    m = _REF_INLINE_RE.search(raw0)
    return m.group(1) if m else ""


def _citation_field(cita: str, field: str) -> str:
    m = re.search(rf"\|{field}=([^|}}]+)", cita)
    return m.group(1).strip() if m else ""


_MONTH_NUM_TO_NAME = {v: k for k, v in MONTH_ES.items()}  # "08" -> "Ago"
_MONTH_FULL = {
    "Ene": "Enero", "Feb": "Febrero", "Mar": "Marzo", "Abr": "Abril",
    "May": "Mayo", "Jun": "Junio", "Jul": "Julio", "Ago": "Agosto",
    "Sep": "Septiembre", "Oct": "Octubre", "Nov": "Noviembre", "Dic": "Diciembre",
}


def _parse_citation_fecha(s: str) -> tuple[str, str, str]:
    """'31 de agosto de 2026' or ISO '2026-08-31' -> ('31', 'Agosto', '2026');
    ('', '', '') if unparseable."""
    s = s.strip()
    m = re.match(r"(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})", s)
    if m:
        d, mo, yr = m.groups()
        return d, mo.capitalize(), yr
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        yr, mo_num, d = m.groups()
        mes = _MONTH_FULL.get(_MONTH_NUM_TO_NAME.get(mo_num, ""), "")
        if mes:
            return d, mes, yr
    return "", "", ""


def _sanity_check_fecha_informe(fecha_informe: str, fecha_fin: str, name: str) -> str:
    """A citation's own fecha= field occasionally has a typo in the Wikipedia
    source itself (a wrong year has happened). Guard against writing that
    straight into the CSV: a report can't be published before its own
    fieldwork ends, and is never dozens of days after either — fall back to
    fecha_fin_campo (the old proxy) rather than silently corrupting the
    timeline this feeds the chart."""
    try:
        d1, m1, y1 = fecha_informe.split("-")
        d2, m2, y2 = fecha_fin.split("-")
        informe_dt = date(int(y1), int(m1), int(d1))
        fin_dt = date(int(y2), int(m2), int(d2))
    except (ValueError, TypeError):
        return fecha_fin
    delta = (informe_dt - fin_dt).days
    if delta < 0 or delta > 30:
        print(f"  ⚠  Citation date '{fecha_informe}' for '{name}' looks wrong "
              f"(fieldwork ends {fecha_fin}) — using {fecha_fin} instead; "
              f"check the Wikipedia citation for a typo")
        return fecha_fin
    return fecha_informe


def _derive_n_informe(encuestadora: str, url: str, cita: str, fecha_fin: str = "") -> str:
    """Best-effort report label, mirroring the conventions already used in
    the CSV for each pollster's own reports. Falls back to citing the
    secondary source (news outlet, newsletter, etc.) when the row isn't
    backed by the pollster's own report — e.g. a poll only mentioned in a
    journalist's article, with no standalone PDF to cite."""
    if encuestadora == "Cadem":
        m = re.search(r"Track-PP-(\d+)", url, re.IGNORECASE)
        if m:
            return m.group(1)
    elif encuestadora == "Criteria":
        m = re.search(r"Agenda_Criteria_(\d+)_([A-Za-z]+)_(\d{4})", url)
        if m:
            d, mo, yr = m.groups()
            return f"{int(d)} de {mo.capitalize()} {yr}"
    elif encuestadora == "Activa Research":
        num = re.search(r"Publicaci[oó]n\s*#(\d+)", cita)
        # Use the row's own fieldwork-end month, not the citation's — Activa's
        # own título labels are sometimes mislabeled by a month (seen in the
        # wild: a "#121" report titled "Abril 26" whose actual dates were in
        # May), and the citation's publication date can spill into the
        # following month too.
        if num and fecha_fin:
            _, mo_num, yr = fecha_fin.split("-")
            mes = _MONTH_FULL.get(_MONTH_NUM_TO_NAME.get(mo_num, ""), "")
            if mes:
                return f"{num.group(1)} - {mes} {yr}"
    elif encuestadora == "TuInfluyes.com":
        m = re.search(r"/e/([a-z]+)-(\d{4})", url)
        if m:
            mes, yr = m.groups()
            return f"{mes[:3]}-{yr[2:]}"
    elif encuestadora == "CEP":
        m = re.search(r"N[°º]\s*(\d+)", cita)
        if m:
            return f"Encuesta CEP {m.group(1)}"
    elif encuestadora == "Panel Ciudadano-UDD" and "panelciudadano.cl" in url:
        d, mes, yr = _parse_citation_fecha(_citation_field(cita, "fecha"))
        if d:
            return f"{int(d)} de {mes} {yr}"

    # Generic fallback: the row isn't backed by the pollster's own report
    # (e.g. cited only via a news article) — note the secondary source
    # instead of leaving a blank a human would have to track down by hand.
    sitioweb = _citation_field(cita, "sitioweb")
    d, mes, yr = _parse_citation_fecha(_citation_field(cita, "fecha"))
    if sitioweb and d:
        mm = MONTH_ES.get(mes[:3], "??")
        return f"Citado en {sitioweb} ({d.zfill(2)}-{mm}-{yr})"
    return ""


def _parse_date(s: str) -> tuple[str, str]:
    """Return (fecha_inicio, fecha_fin) in DD-MM-YYYY from a Wikipedia date string."""
    s = s.strip().replace("–", "-").replace("—", "-")

    # Cross-month range: "31 Mar – 2 Abr 2026" (spaces around dash are optional)
    m = re.match(r"(\d+)\s+(\w+)\s*-\s*(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        return (
            f"{d1.zfill(2)}-{MONTH_ES.get(mo1, '??')}-{yr}",
            f"{d2.zfill(2)}-{MONTH_ES.get(mo2, '??')}-{yr}",
        )

    # Same-month range: "17-18 Mar 2026"
    m = re.match(r"(\d+)\s*-\s*(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d1, d2, mo, yr = m.groups()
        mo_n = MONTH_ES.get(mo, "??")
        return f"{d1.zfill(2)}-{mo_n}-{yr}", f"{d2.zfill(2)}-{mo_n}-{yr}"

    # Single date: "1 May 2026"
    m = re.match(r"(\d+)\s+(\w+)\s+(\d{4})", s)
    if m:
        d, mo, yr = m.groups()
        date = f"{d.zfill(2)}-{MONTH_ES.get(mo, '??')}-{yr}"
        return date, date

    return "", ""


def _parse_row(cells: list[str], ref_index: dict | None = None) -> dict | None:
    """Convert 8 raw cell lines into a CSV row dict, or None if unparseable."""
    if len(cells) != 8:
        return None

    # Column 0: pollster name + source URL
    raw0 = cells[0]
    name = _cell_value(raw0)   # strips bgcolor/style prefix, refs, markup, wikilinks
    cita = _get_citation(raw0, ref_index or {})
    # A row reusing an earlier citation (<ref name="X" />) has no inline
    # "url=" of its own — the url only lives in the citation it points to.
    url = _extract_url(raw0) or _extract_url(cita)

    info = POLLSTERS.get(name)
    if info is None:
        print(f"  ⚠  Unknown pollster '{name}' — add to POLLSTERS in wiki_sync.py")
        info = {"encuestadora": name, "producto": "", "modalidad": "online", "excluir": 0}

    # Column 1: fieldwork date(s)
    raw_date = _cell_value(cells[1])
    fecha_ini, fecha_fin = _parse_date(raw_date)
    if not fecha_ini or not fecha_fin:
        print(f"  ⚠  Unparseable date '{raw_date}' for '{name}' — skipping row "
              f"(add a case to _parse_date instead of importing it blank)")
        return None

    # Column 2: sample size (strip Spanish thousands separator)
    n = _cell_value(cells[2]).replace(".", "").replace(",", "")
    if n in ("—", "-"):
        n = ""

    # Columns 3, 4, 6: approval %, disapproval %, NS/NR %
    def pct(line: str) -> str:
        v = _cell_value(line).replace("%", "").replace(",", ".").strip()
        return "" if v in ("—", "-", "") else v

    # The citation's own "fecha=" field is the report's real publication date;
    # fall back to fecha_fin_campo only when there's no citation to read it from.
    d, mes, yr = _parse_citation_fecha(_citation_field(cita, "fecha"))
    fecha_informe = f"{d.zfill(2)}-{MONTH_ES.get(mes[:3], '??')}-{yr}" if d else fecha_fin
    fecha_informe = _sanity_check_fecha_informe(fecha_informe, fecha_fin, name)

    return {
        "fecha_informe":      fecha_informe,
        "fecha_inicio_campo": fecha_ini,
        "fecha_fin_campo":    fecha_fin,
        "presidente":         "José Antonio Kast",
        "encuestadora":       info["encuestadora"],
        "producto":           info["producto"],
        "aprueba_pct":        pct(cells[3]),
        "desaprueba_pct":     pct(cells[4]),
        "nr_pct":             pct(cells[6]),  # column 5 is "Ninguna" (usually —)
        "n_muestra":          n,
        "aprueba_gob_pct":    "",
        "desaprueba_gob_pct": "",
        "nr_gob_pct":         "",
        "neto_gob":           "",
        "modalidad":          info["modalidad"],
        "n_informe":          _derive_n_informe(info["encuestadora"], url, cita, fecha_fin),
        "excluir":            info.get("excluir", 0),
        "url_fuente":         url,
    }


def parse_table(wikitext: str) -> list[dict]:
    """Extract all data rows from the wikitext table."""
    ref_index = _build_ref_index(wikitext)
    rows: list[dict] = []
    cells: list[str] = []
    in_row = False

    for line in wikitext.splitlines():
        if line.startswith("|-"):
            if in_row and cells:
                row = _parse_row(cells, ref_index)
                if row:
                    rows.append(row)
            cells, in_row = [], True
        elif line.startswith("|}"):
            if in_row and cells:
                row = _parse_row(cells, ref_index)
                if row:
                    rows.append(row)
            in_row = False
        elif in_row and line.startswith("|"):
            cells.append(line)

    return rows


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _key(r: dict) -> tuple:
    """Deduplication key: same pollster + same fieldwork start + same approval/disapproval.
    Intentionally omits fecha_fin and n_muestra, which can differ slightly between
    Wikipedia and the CSV (date ranges vs single dates, minor rounding in sample sizes)."""
    return (r["encuestadora"], r["fecha_inicio_campo"], r["aprueba_pct"], r["desaprueba_pct"])


def load_csv() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8-sig") as f:  # utf-8-sig strips BOM if present
        return list(csv.DictReader(f))


def append_rows(rows: list[dict], next_id: int) -> None:
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for row in rows:
            row["id"] = next_id
            next_id += 1
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--force",   action="store_true", help="sync regardless of revision change")
    ap.add_argument("--dry-run", action="store_true", help="preview without writing anything")
    args = ap.parse_args()

    print("Checking Wikipedia revision…")
    try:
        revid, timestamp = get_wiki_revision()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} from Wikipedia: {e.reason}", file=sys.stderr)
        print(f"Response body:\n{body[:1000]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error contacting Wikipedia: {e}", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    if not args.force and state.get("revid") == revid:
        print(f"No changes since last sync (rev {revid}, {timestamp}).")
        return

    print(f"Update detected: rev {revid} ({timestamp}). Fetching wikitext…")
    wikitext = fetch_wikitext()

    print("Parsing table…")
    wiki_rows = parse_table(wikitext)
    print(f"  {len(wiki_rows)} rows found in Wikipedia table.")

    existing      = load_csv()
    existing_keys = {_key(r) for r in existing}
    new_rows      = [r for r in wiki_rows
                     if _key(r) not in existing_keys
                     and _key(r) not in KNOWN_FALSE_POSITIVES]
    new_rows.reverse()  # wiki_rows is newest-first; IDs must increase with recency

    if not new_rows:
        print("CSV is already up to date — no new rows to add.")
        if not args.dry_run:
            save_state(revid, timestamp)
        return

    next_id = max((int(r["id"]) for r in existing), default=0) + 1
    prefix  = "[dry-run] " if args.dry_run else ""

    print(f"\n{prefix}New rows ({len(new_rows)}):")
    missing_informe = []
    for i, row in enumerate(new_rows):
        flag = "  ← excluir=1" if row["excluir"] else ""
        print(
            f"  [{next_id + i:>3}] {row['encuestadora']:<22} "
            f"{row['fecha_fin_campo']}  n={row['n_muestra']:<6} "
            f"{row['aprueba_pct']}% / {row['desaprueba_pct']}%{flag}"
        )
        if not row["n_informe"]:
            missing_informe.append(f"{row['encuestadora']} {row['fecha_fin_campo']}")

    if args.dry_run:
        print("\n[dry-run] Nothing written.")
        return

    append_rows(new_rows, next_id)
    save_state(revid, timestamp)

    if missing_informe:
        # Every recognized pollster/citation shape gets an n_informe derived
        # automatically (see _derive_n_informe); a blank one here means a URL
        # or citation pattern we haven't seen before. Exit non-zero so the
        # daily workflow surfaces it instead of silently leaving a gap.
        print(
            f"\n⚠  Could not derive n_informe for {len(missing_informe)} row(s), "
            f"needs manual entry: {', '.join(missing_informe)}"
        )
        sys.exit(1)
    print(f"\n✓ Appended {len(new_rows)} row(s) to {CSV_PATH.name}.")


if __name__ == "__main__":
    main()
