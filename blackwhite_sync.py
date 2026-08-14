#!/usr/bin/env python3
"""
blackwhite_sync.py — sync aprobacion_presidencial.csv with Black & White polls.

Black & White isn't covered by wiki_sync.py: its reports never reliably land
on the Wikipedia table (see README). This script scrapes the report listing
at blackwhite.global directly and reads each new PDF's "Aprobación del
gobierno" slide.

The PDFs have a real text layer for titles, dates, and sample size, but the
stacked-bar-chart percentages (desaprueba / no aprueba ni desaprueba) are
graphics with no text layer — those two are read via OCR (tesseract) and
cross-checked against the aprueba % that IS in the text layer (stated in the
slide's prose, "Un XX% aprueba..."). A row is only written if the OCR'd
triplet sums to 100 and its aprueba figure matches the text-layer one
exactly; otherwise the report is skipped and flagged for manual entry.

Requires the `tesseract` and `pdftotext`/`pdftoppm` (poppler) binaries on PATH.

Usage
-----
    python blackwhite_sync.py            # check and sync new reports
    python blackwhite_sync.py --dry-run  # preview without writing anything
"""

import argparse
import csv
import html
import io
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT     = Path(__file__).parent
CSV_PATH = ROOT / "data" / "aprobacion_presidencial.csv"

LISTING_URL = "https://www.blackwhite.global/s-projects-side-by-side"
UA = "AprobacionSyncBot/1.0 (https://github.com/cbuzeta/aprobacion-presidencial; cbuzeta@gmail.com)"

CSV_FIELDS = [
    "id", "fecha_informe", "fecha_inicio_campo", "fecha_fin_campo",
    "presidente", "encuestadora", "producto",
    "aprueba_pct", "desaprueba_pct", "nr_pct", "n_muestra",
    "aprueba_gob_pct", "desaprueba_gob_pct", "nr_gob_pct", "neto_gob",
    "modalidad", "n_informe", "excluir", "url_fuente",
]

MONTH_ES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}

LISTING_CARD_RE = re.compile(
    r'href="(https://www\.blackwhite\.global/_files/ugd/[a-z0-9_]+\.pdf)" '
    r'target="_blank" class="wixui-rich-text__text"><span[^>]*>([^<]+)'
)


# ── listing page ─────────────────────────────────────────────────────────────

def fetch_listing() -> list[tuple[str, str]]:
    """Return [(title, pdf_url), ...] in newest-first page order."""
    req = urllib.request.Request(LISTING_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", errors="replace")

    seen, cards = set(), []
    for m in LISTING_CARD_RE.finditer(page):
        url, raw_title = m.group(1), m.group(2).strip()
        title = html.unescape(raw_title)
        if url in seen or len(title) <= 3 or title.isdigit():
            continue
        seen.add(url)
        cards.append((title, url))
    return cards


# ── PDF helpers ───────────────────────────────────────────────────────────────

def download(url: str, dest: Path, retries: int = 5) -> None:
    """GET url to dest, retrying with backoff on blackwhite.global's 429s.

    The 429 window observed on this endpoint outlasts a naive ~1min backoff
    (a live run needed >5min before a retry succeeded), so this escalates
    much further — acceptable since this only ever runs unattended on a
    schedule, never blocking a human."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    delay = 60
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                f.write(r.read())
            return
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries:
                raise
            print(f"  … 429 from server, waiting {delay}s before retry "
                  f"({attempt + 1}/{retries})")
            time.sleep(delay)
            delay *= 2


def pdf_pages_text(pdf_path: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", errors="replace")
    return out.split("\f")


def render_page_png(pdf_path: Path, page_num: int, out_prefix: Path) -> Path:
    subprocess.run(
        ["pdftoppm", "-png", "-r", "400", "-f", str(page_num), "-l", str(page_num),
         str(pdf_path), str(out_prefix)],
        check=True, capture_output=True,
    )
    candidates = sorted(out_prefix.parent.glob(f"{out_prefix.name}*.png"))
    if not candidates:
        raise RuntimeError(f"pdftoppm produced no output for page {page_num}")
    return candidates[0]


def ocr_total_column(png_path: Path) -> list[int] | None:
    """OCR the chart with sparse-text mode and return the leftmost ('Total')
    column's numbers, top-to-bottom: [no_aprueba, desaprueba, aprueba]."""
    out = subprocess.run(
        ["tesseract", str(png_path), "stdout", "--psm", "11", "tsv"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", errors="replace")

    nums = []
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        if re.fullmatch(r"\d{1,3}", text):
            left, top, width, height = (int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]))
            nums.append((left + width / 2, top + height / 2, int(text)))

    if not nums:
        return None
    nums.sort(key=lambda n: n[0])
    x0 = nums[0][0]
    cluster = sorted([n for n in nums if n[0] - x0 < 100], key=lambda n: n[1])
    if len(cluster) != 3:
        return None
    return [n[2] for n in cluster]


def find_approval_page(pages: list[str]) -> int | None:
    """1-indexed page number of the (non-comparative) 'Aprobación del gobierno' slide."""
    for i, page in enumerate(pages, start=1):
        first_line = next((l.strip() for l in page.splitlines() if l.strip()), "")
        if first_line == "Aprobación del gobierno":
            return i
    return None


def parse_report(pages: list[str]) -> dict | None:
    full_text = "\n".join(pages)

    n_match = re.search(r"realizaron\s+([\d.,]+)\s+encuestas", full_text)
    campo_match = re.search(r"Trabajo de campo\s*\n\s*([^\n]+)", full_text)
    if not n_match or not campo_match:
        return None
    n_muestra = n_match.group(1).replace(".", "").replace(",", "")
    fecha_inicio, fecha_fin = parse_field_dates(campo_match.group(1).strip())
    if not fecha_inicio or not fecha_fin:
        return None

    page_num = find_approval_page(pages)
    if page_num is None:
        return None
    approval_page = pages[page_num - 1]

    aprueba_match = re.search(r"Un\s+(\d{1,3})%\s+aprueba", approval_page)
    if not aprueba_match:
        return None
    aprueba_text = int(aprueba_match.group(1))

    date_match = re.search(r"(\d{1,2}\s+\w+\s+202\d)\s*$", approval_page.strip())
    fecha_informe = parse_informe_date(date_match.group(1)) if date_match else fecha_fin

    return {
        "n_muestra": n_muestra,
        "fecha_inicio_campo": fecha_inicio,
        "fecha_fin_campo": fecha_fin,
        "fecha_informe": fecha_informe or fecha_fin,
        "aprueba_text": aprueba_text,
        "approval_page_num": page_num,
    }


def parse_field_dates(s: str) -> tuple[str, str]:
    """'13 de julio 2026' or a range -> (DD-MM-YYYY, DD-MM-YYYY)."""
    s = s.strip().replace("–", "-").replace("—", "-")

    m = re.match(r"(\d+)\s+de\s+(\w+)\s*-\s*(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})", s)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        return (f"{d1.zfill(2)}-{MONTH_ES.get(mo1.lower(),'??')}-{yr}",
                f"{d2.zfill(2)}-{MONTH_ES.get(mo2.lower(),'??')}-{yr}")

    m = re.match(r"(\d+)\s*-\s*(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})", s)
    if m:
        d1, d2, mo, yr = m.groups()
        mo_n = MONTH_ES.get(mo.lower(), "??")
        return f"{d1.zfill(2)}-{mo_n}-{yr}", f"{d2.zfill(2)}-{mo_n}-{yr}"

    m = re.match(r"(\d+)\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", s)
    if m:
        d, mo, yr = m.groups()
        date = f"{d.zfill(2)}-{MONTH_ES.get(mo.lower(), '??')}-{yr}"
        return date, date

    return "", ""


def parse_informe_date(s: str) -> str:
    """'14 julio 2026' (no "de") -> DD-MM-YYYY, or '' if unparseable."""
    m = re.match(r"(\d+)\s+(\w+)\s+(\d{4})", s.strip())
    if not m:
        return ""
    d, mo, yr = m.groups()
    mo_n = MONTH_ES.get(mo.lower())
    if not mo_n:
        return ""
    return f"{d.zfill(2)}-{mo_n}-{yr}"


# ── CSV helpers ───────────────────────────────────────────────────────────────

def load_csv() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def append_rows(rows: list[dict], next_id: int) -> None:
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for row in rows:
            row["id"] = next_id
            next_id += 1
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


# ── main ──────────────────────────────────────────────────────────────────────

def _key(fecha_inicio_campo: str, aprueba_pct: int) -> tuple:
    """Dedup key independent of source URL: the same poll is sometimes
    mirrored under a different URL (e.g. an Emol re-post of a B&W report),
    so URL-only dedup can miss it."""
    return ("Black & White", fecha_inicio_campo, aprueba_pct)


def process_report(title: str, url: str, existing_keys: set) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pdf_path = tmp / "report.pdf"
        try:
            download(url, pdf_path)
        except Exception as e:
            print(f"  ⚠  Could not download {url}: {e}")
            return None

        pages = pdf_pages_text(pdf_path)
        parsed = parse_report(pages)
        if parsed is None:
            print(f"  ⚠  Could not parse methodology/approval slide for '{title}' — skipping")
            return None

        key = _key(parsed["fecha_inicio_campo"], parsed["aprueba_text"])
        if key in existing_keys:
            print(f"  Already in the CSV under a different URL (same fecha/aprueba%) — skipping")
            return None

        try:
            png_path = render_page_png(pdf_path, parsed["approval_page_num"], tmp / "approval")
            triplet = ocr_total_column(png_path)
        except Exception as e:
            print(f"  ⚠  OCR failed for '{title}': {e} — skipping")
            return None

        if triplet is None:
            print(f"  ⚠  Could not read 3 numbers off the approval chart for '{title}' — skipping")
            return None

        no_aprueba, desaprueba, aprueba_chart = triplet
        if aprueba_chart != parsed["aprueba_text"]:
            print(f"  ⚠  OCR mismatch for '{title}': chart says {aprueba_chart}% aprueba, "
                  f"text says {parsed['aprueba_text']}% — skipping (needs manual entry)")
            return None
        if aprueba_chart + desaprueba + no_aprueba != 100:
            print(f"  ⚠  OCR checksum failed for '{title}': "
                  f"{aprueba_chart}+{desaprueba}+{no_aprueba} != 100 — skipping (needs manual entry)")
            return None

        return {
            "fecha_informe":      parsed["fecha_informe"],
            "fecha_inicio_campo": parsed["fecha_inicio_campo"],
            "fecha_fin_campo":    parsed["fecha_fin_campo"],
            "presidente":         "José Antonio Kast",
            "encuestadora":       "Black & White",
            "producto":           "B&W",
            "aprueba_pct":        aprueba_chart,
            "desaprueba_pct":     desaprueba,
            "nr_pct":             no_aprueba,
            "n_muestra":          parsed["n_muestra"],
            "modalidad":          "online",
            "n_informe":          title,
            "excluir":            0,
            "url_fuente":         url,
        }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry-run", action="store_true", help="preview without writing anything")
    args = ap.parse_args()

    print("Fetching Black & White report listing…")
    try:
        cards = fetch_listing()
    except Exception as e:
        print(f"Error fetching listing page: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(cards)} report cards found on the listing page.")

    existing = load_csv()
    known_urls = {r["url_fuente"] for r in existing}
    existing_keys = {
        _key(r["fecha_inicio_campo"], int(float(r["aprueba_pct"])))
        for r in existing if r["encuestadora"] == "Black & White" and r["aprueba_pct"]
    }
    new_cards = [(t, u) for t, u in cards if u not in known_urls]
    new_cards.reverse()  # listing is newest-first; IDs must increase with recency

    if not new_cards:
        print("CSV is already up to date — no new Black & White reports to add.")
        return

    next_id = max((int(r["id"]) for r in existing), default=0) + 1
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}Checking {len(new_cards)} new report(s):")

    rows = []
    for i, (title, url) in enumerate(new_cards):
        if i > 0:
            print("\n… waiting 3 min before the next report, to stay under "
                  "blackwhite.global's download rate limit")
            time.sleep(180)
        print(f"\n- {title}")
        row = process_report(title, url, existing_keys)
        if row is None:
            continue
        print(f"  [{next_id + len(rows):>3}] {row['fecha_fin_campo']}  n={row['n_muestra']:<6} "
              f"{row['aprueba_pct']}% / {row['desaprueba_pct']}% / {row['nr_pct']}%")
        rows.append(row)
        existing_keys.add(_key(row["fecha_inicio_campo"], row["aprueba_pct"]))

    if not rows:
        print("\nNo rows could be verified automatically this run.")
        return

    if args.dry_run:
        print(f"\n[dry-run] Would append {len(rows)} row(s). Nothing written.")
        return

    append_rows(rows, next_id)
    print(f"\n✓ Appended {len(rows)} row(s) to {CSV_PATH.name}.")


if __name__ == "__main__":
    main()
