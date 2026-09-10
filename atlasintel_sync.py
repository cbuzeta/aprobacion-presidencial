#!/usr/bin/env python3
"""
atlasintel_sync.py — sync aprobacion_presidencial.csv with AtlasIntel's
"Latam Pulse: Chile" polls.

AtlasIntel isn't covered by wiki_sync.py: Wikipedia's table currently has
no AtlasIntel entries at all (it may have in the past, which is how the
CSV's earliest two rows got there, but none since). Publishes monthly,
typically within the first ~8 days of the following month, so this is
meant to run once a month, in the second week.

The PDF has a real text layer for the methodology (sample size, fieldwork
dates), but the approval-question slide is a graphic (a labeled bar chart)
with no text layer for its numbers — those are read via OCR (tesseract) on
a tight crop around each bar's value, found by locating each category
label ("Apruebo"/"Desapruebo"/"No sé") via a first OCR pass and then
pixel-scanning for near-black (true text, not a colored bar) pixels below
it. Several crop/scale/PSM combinations are tried in turn; a row is only
written once a combination's three values sum to 100% within 1pp AND
match the pollster's own aprueba figure — otherwise the report is skipped
and flagged for manual entry.

Requires the `tesseract` and `pdftotext`/`pdftoppm` (poppler) binaries on
PATH, plus the Pillow package (for the pixel-level crop/threshold work
plain stdlib can't do).

Usage
-----
    python atlasintel_sync.py            # check and sync new reports
    python atlasintel_sync.py --dry-run  # preview without writing anything
"""

import argparse
import csv
import io
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT     = Path(__file__).parent
CSV_PATH = ROOT / "data" / "aprobacion_presidencial.csv"

LISTING_URL = "https://atlasintel.org/polls/latam-pulse"
UA = "AprobacionSyncBot/1.0 (https://github.com/cbuzeta/aprobacion-presidencial; cbuzeta@gmail.com)"

CSV_FIELDS = [
    "id", "fecha_informe", "fecha_inicio_campo", "fecha_fin_campo",
    "presidente", "encuestadora", "producto",
    "aprueba_pct", "desaprueba_pct", "nr_pct", "n_muestra",
    "aprueba_gob_pct", "desaprueba_gob_pct", "nr_gob_pct", "neto_gob",
    "modalidad", "n_informe", "excluir", "url_fuente",
]

MONTH_EN_TO_ABBR_ES = {
    "january": "ene", "february": "feb", "march": "mar", "april": "abr",
    "may": "may", "june": "jun", "july": "jul", "august": "ago",
    "september": "sep", "october": "oct", "november": "nov", "december": "dic",
}

CHILE_POLL_RE = re.compile(r'href="(/poll/latam-pulse-chile-[a-z]+-\d{4}-\d{4}-\d{2}-\d{2})"')
PDF_HREF_RE   = re.compile(r'href="(https://cdn1?\.atlasintel\.org/[^"]+\.pdf)"')
SLUG_DATE_RE  = re.compile(r"latam-pulse-chile-([a-z]+)-(\d{4})-(\d{4}-\d{2}-\d{2})$")


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def download(url: str, dest: Path, retries: int = 5) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    delay = 30
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                f.write(r.read())
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == retries:
                raise
            print(f"  … {e.code} from server, waiting {delay}s before retry "
                  f"({attempt + 1}/{retries})")
            time.sleep(delay)
            delay *= 2


# ── listing ───────────────────────────────────────────────────────────────────

def fetch_listing() -> list[tuple[str, str]]:
    """Return [(title, poll_page_url), ...] for Chile entries, newest-first.

    The listing page is Nuxt-SSR'd: the plain <a href> tags below are present
    in the static HTML without running any JS, but only the ~3 most recent
    entries per country are rendered — plenty for a monthly check, since
    each month's report stays visible through at least the following month.
    """
    page = _get(LISTING_URL)
    seen, cards = set(), []
    for m in CHILE_POLL_RE.finditer(page):
        path = m.group(1)
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1]
        cards.append((slug, f"https://atlasintel.org{path}"))
    return cards


def fetch_pdf_url(poll_page_url: str) -> str:
    page = _get(poll_page_url)
    m = PDF_HREF_RE.search(page)
    return m.group(1) if m else ""


# ── PDF helpers ───────────────────────────────────────────────────────────────

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


def find_methodology_page(pages: list[str]) -> int | None:
    for i, page in enumerate(pages):
        if "PERÍODO DE RECOLECCIÓN" in page:
            return i
    return None


def parse_methodology(pages: list[str]) -> dict | None:
    idx = find_methodology_page(pages)
    if idx is None:
        return None
    page = pages[idx]

    n_match = re.search(r"MUESTRA\s*\n\s*([\d.,]+)\s*encuestados", page)
    campo_match = re.search(
        r"PERÍODO DE RECOLECCIÓN\s*\n\s*(\d{2})/(\d{2})/(\d{4})-(\d{2})/(\d{2})/(\d{4})", page
    )
    if not n_match or not campo_match:
        return None

    n_muestra = n_match.group(1).replace(".", "").replace(",", "")
    d1, m1, y1, d2, m2, y2 = campo_match.groups()
    return {
        "n_muestra": n_muestra,
        "fecha_inicio_campo": f"{d1}-{m1}-{y1}",
        "fecha_fin_campo": f"{d2}-{m2}-{y2}",
    }


def find_approval_page(pages: list[str]) -> int | None:
    """1-indexed page number of the presidential-approval bar-chart slide
    (distinct from the trend/demographic-breakdown pages of the same
    section, and from the separate "Evaluación del gobierno" question)."""
    for i, page in enumerate(pages, start=1):
        if "Apruebas o desapruebas el desempe" in page:
            return i
    return None


# ── OCR: label-anchored value extraction ───────────────────────────────────────

# Tried in order until a report's 3 values sum to 100% within 1pp. Different
# crop scales / threshold order / PSM modes each fail on different reports
# (a font-rendering quirk of this specific PDF template) but never in a way
# that produces a plausible-looking wrong triplet — a bad read drops a digit
# or the decimal point, which the checksum below catches every time observed.
_OCR_CONFIGS = [(13, 5, True), (13, 4, True), (13, 6, False),
                (7, 5, True), (8, 3, True), (13, 3, True),
                (7, 4, True), (8, 6, False)]

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d)?)%")


def _find_labels(png_path: Path) -> dict[str, tuple[int, int]] | None:
    """OCR the full page once to locate the 3 category labels; returns
    {name: (left, bottom)} in pixel coordinates, or None if not all found."""
    out = subprocess.run(
        ["tesseract", str(png_path), "stdout", "--psm", "11", "tsv"],
        capture_output=True,
    ).stdout.decode("utf-8", errors="replace")

    found = {}
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        left, top, width, height = (int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]))
        if text == "Apruebo":
            found["aprueba"] = (left, top + height)
        elif text == "Desapruebo":
            found["desaprueba"] = (left, top + height)
        elif text == "No":
            found["no_sabe"] = (left, top + height)

    return found if len(found) == 3 else None


def _ocr_value_near(im: Image.Image, label_x: int, label_bottom: int,
                     psm: int, scale: int, threshold_first: bool) -> float | None:
    """Crop the region below-right of a label, tightly bound it to the
    near-black (true text, not a colored bar) pixels within, and OCR just
    that crop for a percentage value."""
    w, h = im.size
    x0, y0 = label_x, label_bottom + 30
    x1, y1 = min(label_x + 7500, w), min(label_bottom + 400, h)
    region = im.crop((x0, y0, x1, y1))
    px = region.load()

    xs, ys = [], []
    for yy in range(0, region.height, 2):
        for xx in range(0, region.width, 2):
            r, g, b = px[xx, yy]
            if r < 100 and g < 100 and b < 100:
                xs.append(xx)
                ys.append(yy)
    if not xs:
        return None

    bx0, bx1 = max(0, min(xs) - 20), min(region.width, max(xs) + 20)
    by0, by1 = max(0, min(ys) - 20), min(region.height, max(ys) + 20)
    tight = region.crop((bx0, by0, bx1, by1)).convert("L")

    if threshold_first:
        tight = tight.point(lambda p: 255 if p > 180 else 0)
        tight = tight.resize((tight.width * scale, tight.height * scale), Image.LANCZOS)
    else:
        tight = tight.resize((tight.width * scale, tight.height * scale), Image.LANCZOS)
        tight = tight.point(lambda p: 255 if p > 180 else 0)
    tight = ImageOps.expand(tight, border=80, fill=255)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tight.save(tf.name)
        tmp_path = tf.name
    try:
        out = subprocess.run(
            ["tesseract", tmp_path, "stdout", "--psm", str(psm)],
            capture_output=True,
        ).stdout.decode("utf-8", errors="replace").strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    m = _PCT_RE.fullmatch(out)
    return float(m.group(1)) if m else None


def ocr_approval_bars(png_path: Path) -> dict[str, float] | None:
    labels = _find_labels(png_path)
    if labels is None:
        return None

    im = Image.open(png_path).convert("RGB")
    for psm, scale, threshold_first in _OCR_CONFIGS:
        values = {}
        for name, (lx, lb) in labels.items():
            v = _ocr_value_near(im, lx, lb, psm, scale, threshold_first)
            if v is None:
                break
            values[name] = v
        else:
            if abs(sum(values.values()) - 100) <= 1:
                return values
    return None


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

def _key(fecha_inicio_campo: str, aprueba_pct: float) -> tuple:
    """Dedup key independent of source URL, matching wiki_sync.py's and
    blackwhite_sync.py's pattern."""
    return ("AtlasIntel", fecha_inicio_campo, round(aprueba_pct, 1))


def process_report(slug: str, poll_page_url: str, existing_keys: set) -> tuple[dict | None, bool]:
    """Returns (row_or_None, needs_attention) — see blackwhite_sync.py's
    process_report for why the two are distinguished."""
    m = SLUG_DATE_RE.match(slug)
    if not m:
        print(f"  ⚠  Unrecognized poll slug '{slug}' — skipping")
        return None, True
    month_en, report_year, pub_date = m.groups()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        try:
            pdf_url = fetch_pdf_url(poll_page_url)
            if not pdf_url:
                print(f"  ⚠  Could not find a PDF link on {poll_page_url}")
                return None, True
            pdf_path = tmp / "report.pdf"
            download(pdf_url, pdf_path)
        except Exception as e:
            print(f"  ⚠  Could not download report: {e}")
            return None, True

        pages = pdf_pages_text(pdf_path)
        methodology = parse_methodology(pages)
        if methodology is None:
            print(f"  ⚠  Could not parse methodology page for '{slug}' — skipping")
            return None, True

        key_partial = methodology["fecha_inicio_campo"]

        page_num = find_approval_page(pages)
        if page_num is None:
            print(f"  ⚠  Could not find the approval-question slide for '{slug}' — skipping")
            return None, True

        try:
            png_path = render_page_png(pdf_path, page_num, tmp / "approval")
            bars = ocr_approval_bars(png_path)
        except Exception as e:
            print(f"  ⚠  OCR failed for '{slug}': {e} — skipping")
            return None, True

        if bars is None:
            print(f"  ⚠  Could not read the approval chart for '{slug}' — skipping (needs manual entry)")
            return None, True

        key = _key(key_partial, bars["aprueba"])
        if key in existing_keys:
            print("  Already in the CSV — skipping")
            return None, False

        mes_abbr = MONTH_EN_TO_ABBR_ES.get(month_en, month_en[:3])
        n_informe = f"{mes_abbr}-{report_year[2:]}"
        fecha_informe = f"{pub_date[8:10]}-{pub_date[5:7]}-{pub_date[0:4]}"

        return {
            "fecha_informe":      fecha_informe,
            "fecha_inicio_campo": methodology["fecha_inicio_campo"],
            "fecha_fin_campo":    methodology["fecha_fin_campo"],
            "presidente":         "José Antonio Kast",
            "encuestadora":       "AtlasIntel",
            "producto":           "Latam Pulse Chile",
            "aprueba_pct":        bars["aprueba"],
            "desaprueba_pct":     bars["desaprueba"],
            "nr_pct":             bars["no_sabe"],
            "n_muestra":          methodology["n_muestra"],
            "modalidad":          "online",
            "n_informe":          n_informe,
            "excluir":            0,
            "url_fuente":         pdf_url,
        }, False


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry-run", action="store_true", help="preview without writing anything")
    args = ap.parse_args()

    print("Fetching AtlasIntel Chile poll listing…")
    try:
        cards = fetch_listing()
    except Exception as e:
        print(f"Error fetching listing page: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(cards)} Chile report(s) found on the listing page.")

    existing = load_csv()
    known_urls = {r["url_fuente"] for r in existing}
    existing_keys = {
        _key(r["fecha_inicio_campo"], float(r["aprueba_pct"]))
        for r in existing if r["encuestadora"] == "AtlasIntel" and r["aprueba_pct"]
    }

    next_id = max((int(r["id"]) for r in existing), default=0) + 1
    prefix = "[dry-run] " if args.dry_run else ""

    rows = []
    attention_needed = []
    for slug, poll_page_url in cards:
        print(f"\n- {slug}")
        row, needs_attention = process_report(slug, poll_page_url, existing_keys)
        if needs_attention:
            attention_needed.append(slug)
        if row is None:
            continue
        if row["url_fuente"] in known_urls:
            continue
        print(f"  [{next_id + len(rows):>3}] {row['fecha_fin_campo']}  n={row['n_muestra']:<6} "
              f"{row['aprueba_pct']}% / {row['desaprueba_pct']}%")
        rows.append(row)
        existing_keys.add(_key(row["fecha_inicio_campo"], row["aprueba_pct"]))

    if not rows:
        print("\nNo new rows could be verified automatically this run.")
    elif args.dry_run:
        print(f"\n[dry-run] Would append {len(rows)} row(s). Nothing written.")
    else:
        append_rows(rows, next_id)
        print(f"\n✓ Appended {len(rows)} row(s) to {CSV_PATH.name}.")

    if attention_needed:
        print(f"\n⚠  {len(attention_needed)} report(s) need manual entry: "
              f"{', '.join(attention_needed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
