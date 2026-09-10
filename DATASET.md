# MetaAprobación: A Harmonized Dataset of Chilean Presidential Approval Polling, 2018–2026

**Version:** 1.11 · **Maintainer:** Cristian Buzeta ([@cbuzeta](https://x.com/cbuzeta), cbuzetar@fen.uchile.cl) · **Live dashboard:** https://github.com/cbuzeta/aprobacion-presidencial

## 1. Overview

This dataset harmonizes presidential approval polling in Chile into a single, consistently-coded table spanning three administrations: **Sebastián Piñera** (second term, 2018–2022), **Gabriel Boric** (2022–2026), and **José Antonio Kast** (2026–, ongoing). Each row is one published measurement from one pollster: fieldwork dates, sample size, approval/disapproval/don't-know percentages, methodology, and a link to the original source report.

Most datasets on Chilean presidential approval exist as a single pollster's time series, or as an unstructured table on a Wikipedia page. This one:
- **Combines 14 pollsters** into one schema (see §6), so cross-house comparisons and pooled estimates don't require separate scraping/harmonization work.
- **Cites a primary or credible secondary source for 98.5% of rows** (§4), individually verified as a live, resolvable URL as of the dataset's last update — not just "trust us."
- **Is reproducible going forward**: the current-president portion is kept current by three automated pipelines (§5) that re-derive from the same public sources (Wikipedia's own polling tables, pollster report listings) rather than manual entry.

### 1.1 Coverage summary

| Administration | Date range | Pollster-measurements | Excluded (no verifiable source) |
|---|---|---|---|
| Sebastián Piñera (2018–2022) | 16-03-2018 – 04-03-2022 | 399 | 7 |
| Gabriel Boric (2022–2026) | 18-03-2022 – 12-03-2026 | 428 | 7 |
| José Antonio Kast (2026–) | 15-03-2026 – present | 134 | 0 |
| **Total** | **16-03-2018 – present** | **961** | **14** |

Excluded rows (`excluir=1`) are real data points kept in the table for completeness — the transcribed values from the original compilation this dataset extends (see §5.2) — but not independently source-verified, so they're flagged out of any published estimate. 947 of 961 rows (98.5%) are active.

## 2. How to cite

If citing the dataset itself (recommended for reproducibility of any analysis built on a specific snapshot):

> Buzeta, C. (2026). *MetaAprobación: A Harmonized Dataset of Chilean Presidential Approval Polling, 2018–2026* (Version 1.11) [Data set]. Zenodo. https://doi.org/xx.xxxx/zenodo.xxxxxxx

*(DOI to be filled in once archived — see §8.)*

If citing a specific pollster's finding drawn from a row in this dataset, cite the original report via that row's `url_fuente`, not this dataset — the pollster is the primary source of the measurement itself; this dataset is a secondary compilation (see §7 on licensing).

## 3. Data files

- **`data/aprobacion_presidencial.csv`** — the dataset proper. UTF-8 with BOM, comma-delimited, 961 data rows + 1 header row, one row per poll-pollster-measurement.
- **`README.md`** — build/run instructions for the companion dashboard (`index.html`), and documentation of the three automated sync pipelines that keep the Kast-era portion current.
- **`scripts/`** — the four one-shot scripts used to construct the historical (Piñera/Boric) portion of the dataset, kept as a methodological record (see §5.2).

## 4. Codebook

```
id,fecha_informe,fecha_inicio_campo,fecha_fin_campo,presidente,encuestadora,producto,
aprueba_pct,desaprueba_pct,nr_pct,n_muestra,aprueba_gob_pct,desaprueba_gob_pct,
nr_gob_pct,neto_gob,modalidad,n_informe,excluir,url_fuente
```

| Column | Type | Description |
|---|---|---|
| `id` | integer | Row identifier, sequential 1–961, sorted by `fecha_fin_campo`. Not a stable external key — do not treat as a permanent identifier across dataset versions; join on `(encuestadora, fecha_fin_campo, aprueba_pct)` instead if merging across versions. |
| `fecha_informe` | date, DD-MM-YYYY | Publication date of the report. |
| `fecha_inicio_campo` | date, DD-MM-YYYY | Fieldwork start date. **Blank for 32 rows** (3.3%, mostly 2018–2019 reports whose original document didn't state one). |
| `fecha_fin_campo` | date, DD-MM-YYYY | Fieldwork end date; the field the dashboard and this codebook use as each measurement's reference date. |
| `presidente` | categorical | President in office: `Sebastián Piñera`, `Gabriel Boric`, or `José Antonio Kast`. |
| `encuestadora` | categorical | Polling house. 14 distinct values — see §6. |
| `producto` | text | The pollster's own name for the instrument/wave (e.g. "Plaza Pública", "Agenda Criteria"). |
| `aprueba_pct` | float, 0–100 | % approve of the president. |
| `desaprueba_pct` | float, 0–100 | % disapprove of the president. |
| `nr_pct` | float, 0–100 | % don't know / no answer / neither. Not always independently reported — some rows derive it as `100 − aprueba − desaprueba`. |
| `n_muestra` | integer | Nominal sample size. **Blank for 32 rows** (3.3%, same rows generally as missing `fecha_inicio_campo`). |
| `aprueba_gob_pct` / `desaprueba_gob_pct` / `nr_gob_pct` / `neto_gob` | float / float / float / integer | **Government** (not presidential) approval, when the pollster asks it as a separate question. Populated on only 6 of 961 rows — almost all pollsters in this dataset ask presidential approval only. Treat as sparse/exploratory, not a usable time series on its own. |
| `modalidad` | categorical | Fieldwork mode: `online`, `telefónica`, `presencial`, or `offline` (CEP's face-to-face national survey). |
| `n_informe` | text | Human-readable report label. Either derived from the pollster's own report numbering/filename (e.g. Cadem's `Track-PP-NNN`), or, for rows only locatable via a secondary source, `"Citado en {sitio} ({fecha})"` — see §5. Blank only for the 14 `excluir=1` rows. |
| `excluir` | 0/1 | **1 = exclude from any published estimate** (no independently verifiable source found, see §5.2.4); **0 = include**. Always filter on this column before analysis: `df[df.excluir == 0]`. |
| `url_fuente` | text (URL) | Link to the original report or a corroborating secondary source. Individually verified as HTTP 200 as of 2026-09-10 (see §5.2.3) — expect natural link rot over time; re-verification is a maintenance task, not a one-time guarantee. |

**Missing-value convention:** empty string, not `NA`/`NaN`/`-999`. Cast on load (e.g. `pd.read_csv(..., na_values=[""])`).

## 5. Provenance and construction methodology

### 5.1 Current-president portion (Kast, 134 rows) — automated, ongoing

Sourced live and continuously from three pipelines documented in full in `README.md`:
- **`wiki_sync.py`** — daily scrape of Wikipedia's own "Anexo:Encuestas de aprobación del gobierno de José Antonio Kast" table, which is itself sourced to `{{Cita web}}` citations of each pollster's original report. `n_informe`/`fecha_informe` are derived from that citation, with a sanity check against the fieldwork date to catch citation typos.
- **`blackwhite_sync.py`** — daily OCR-based scrape of Black & White's own report listing (this pollster stopped appearing reliably on the Wikipedia table).
- **`atlasintel_sync.py`** — monthly OCR-based scrape of AtlasIntel's "Latam Pulse: Chile" listing.

All three fail loudly (non-zero exit, but still commit whatever *did* verify) rather than silently skipping a report that couldn't be automatically read, so gaps are caught within a day rather than accumulating unnoticed.

### 5.2 Historical portion (Piñera + Boric, 827 rows) — one-time construction, 2026-09

Unlike the Kast-era portion, Piñera's and Boric's presidencies are closed, so this was a one-time backfill rather than an ongoing sync. Four stages, each documented in the corresponding script under `scripts/`:

1. **Baseline transcription** (`append_historical.py`): initial approval figures transcribed from [DecideChile](https://decidechile.cl), an existing Chilean poll aggregator. This is the weakest link in the provenance chain — a transcription of a transcription — which is why every subsequent stage exists.
2. **Cross-check against Wikipedia's own historical tables** (`patch_historical_urls.py`, `fill_dates_modalidad.py`): Wikipedia maintains "Anexo:Encuestas de aprobación..." pages for both prior presidencies, each poll cited the same way as the current Kast page. Rows were matched to their Wikipedia entry by pollster + fieldwork date (±2–5 days) + approval percentage (±1.5pp), backfilling `url_fuente`, `n_muestra`, and `fecha_inicio_campo` from the citation whenever a confident match was found, and inserting ~60 rows Wikipedia had that DecideChile's transcription had missed entirely.
3. **Independent link recovery and re-verification** (this session, not a checked-in script — see the git history around commit `683699f`): every remaining `url_fuente` was bulk-checked for HTTP liveness. ~450 had gone dead (mostly Cadem/"Plaza Pública" PDFs, which the host prunes after about a month — the same issue independently found and fixed for the Kast-era data — plus assorted 2018–2023 pollster-site reorganizations). Live replacements were found via the Wayback Machine's CDX API and, where no snapshot existed, contemporaneous news coverage of the same release (La Tercera, Emol, BioBioChile, CNN Chile, El Mostrador, Ex-Ante, Cooperativa, La Nación, AIM Chile). For the 37 rows with no source at all going into this step, the same search-and-verify process found credible sources — primary or corroborating — for 23; two of those were found to disagree with DecideChile's transcribed percentage by 1pp and were corrected to match the primary source.
4. **Disclosure of the residual gap**: 14 rows (1.5% of the historical portion) had no identifiable source after this process and are marked `excluir=1` rather than silently dropped or left looking as reliable as the rest.

`n_informe` for historical rows follows the same derivation logic as the live pipeline (per-pollster regex against the report's own filename/URL) where possible, falling back to `"Citado en {sitio} ({fecha})"` for rows only locatable via a secondary source — 96 of 827 historical rows use this fallback label.

### 5.3 What this means for reliability

- **Approval/disapproval percentages**: high confidence for the ~85% of rows sourced directly to the pollster's own report (primary source), and for the subset independently spot-checked against `pdftotext` extraction of the underlying PDF. Somewhat lower confidence — but still corroborated, not merely asserted — for rows sourced only to a secondary news report of the same release.
- **Sample sizes and fieldwork start dates**: incomplete for ~3% of rows, concentrated in 2018–2019 reports that didn't publish one. Not imputed; left blank.
- **This dataset has not been independently re-OCR'd against every underlying PDF.** The Kast-era portion is (OCR/text-layer extraction with a numeric checksum gate, per pollster — see README). The historical portion relies on the pollster's own published figure as transcribed by DecideChile and cross-checked as described above, not independent re-extraction from the primary document for every row. Treat the historical portion as "verified against a live, on-topic primary or secondary source" rather than "independently re-measured."

## 6. Pollster directory

| Pollster | Rows | Modality | Administrations covered |
|---|---|---|---|
| Cadem | 474 | Online | Piñera, Boric, Kast |
| Criteria | 140 | Online | Piñera, Boric, Kast |
| Activa Research | 138 | Online | Piñera, Boric, Kast |
| TuInfluyes.com | 77 | Online | Piñera, Boric, Kast |
| Black & White | 31 | Online | Kast |
| Feedback Research | 20 | Online (from 2021) / Telefónica (before) | Piñera, Boric |
| Panel Ciudadano-UDD | 20 | Online | Boric, Kast |
| GfK Adimark | 19 | Online (from 2020) / Presencial (before) | Piñera |
| CEP | 16 | Presencial / offline | Piñera, Boric, Kast |
| Research Chile | 13 | Online | Boric |
| AtlasIntel | 6 | Online | Kast |
| MORI | 5 | Telefónica | Piñera |
| MORI-Fiel | 1 | Telefónica | Boric |
| CERC-MORI | 1 | Telefónica | Boric |

Nearly all pollsters use non-probability online panels. Confidence intervals computed downstream (e.g. in the companion dashboard) should be read as approximate/orientational, not as guarantees under simple random sampling — this is stated explicitly in the dashboard's own methodology note and applies equally to any analysis built directly on this CSV.

## 7. License

- **This compilation (CSV structure, derived fields, documentation, code)**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: "MetaAprobación dataset, Cristian Buzeta, [DOI/repo link]."
- **The underlying poll measurements are not this project's intellectual property.** Each figure originates from the named pollster's own published report; `url_fuente` links to that report (or, per §5.2, a corroborating secondary account of it). This dataset reproduces the *facts* reported — dates, percentages, sample sizes — not the original documents' text, design, or analysis. That distinction matters for two reasons: (1) facts and data points are generally not subject to copyright protection independent of their original expression, in Chile as in most jurisdictions; and (2) it mirrors exactly how Wikipedia's own "Anexo:Encuestas de aprobación..." pages already tabulate this same information under an open license (CC BY-SA), which this dataset partly draws from.
- **No original PDF reports, images, or other pollster-authored documents are bundled, mirrored, or redistributed in this dataset or repository.** Only the tabulated facts and a link to the source. If archiving to Zenodo, keep it that way — attach the CSV and this descriptor, not copies of the underlying reports.
- If a pollster objects to even this level of reuse for a specific figure, the fix is to remove that row (set `excluir=1` and drop the values, keeping only the citation) rather than argue the point — that's a low-cost accommodation given how few rows any single pollster represents.

## 8. Publishing checklist (Zenodo via GitHub)

1. Confirm the repository is public.
2. Link the GitHub repo to Zenodo once, at https://zenodo.org/account/settings/github/ (sign in with GitHub, flip the switch next to `cbuzeta/aprobacion-presidencial`).
3. Cut a GitHub Release (not just a tag — Releases are what Zenodo listens for) off the `v1.11` tag, or bundle this into the next version bump.
4. Zenodo auto-archives the release and mints a DOI within a few minutes. Fill in its metadata form using §1–2 of this document (title, description, creators, keywords: `public opinion`, `presidential approval`, `Chile`, `polling`, `political science`); set license to CC BY 4.0; add a note pointing to §7 for the data-vs-compilation distinction.
5. Every subsequent GitHub Release under the same Zenodo linkage gets its own **versioned** DOI automatically, plus a stable "concept DOI" that always resolves to the latest version — cite the concept DOI in general references, the versioned one for exact reproducibility.
6. Come back and replace the placeholder DOI in §2 once it exists.

## 9. Acknowledgments

This project has benefited from feedback from Rodrigo Uribe (Universidad de Chile), Paulina Valenzuela (Datavoz), and Alejandra Ojeda (IPSOS).
