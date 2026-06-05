# auth_scrapper_lite

Beta version gotcha: a lightweight Python scraper for the Clinical Trials Registry - India (CTRI) search portal. The project searches CTRI by keyword, solves the CTRI CAPTCHA through Groq Vision, extracts trial result rows, scrapes each trial detail page, validates each parsed record with Pydantic models, and writes structured JSON output.

## What this does

- Searches the CTRI advanced-search form with a keyword, defaulting to `lung`.
- Uses Groq Vision to read the CAPTCHA image required by CTRI, with optional Tesseract and manual fallbacks.
- Extracts trial links from the CTRI result table.
- Scrapes trial detail pages concurrently with configurable worker count and request delay.
- Parses clinical-trial fields into a normalized schema in `schema.py`.
- Saves resumable progress in `ctri_progress.json`.
- Exports combined results to `ctri_results.json`.
- Optionally splits the combined result file into one JSON file per CTRI record under `results/`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `scraper.py` | Main CTRI scraper CLI and parser implementation. |
| `schema.py` | Pydantic models for validated trial records. |
| `split_results.py` | Utility that splits `ctri_results.json` into per-record JSON files. |
| `test_scraper.py` | End-to-end smoke test that runs a small scrape and validates the output shape. |
| `requirements.txt` | Python dependency pins for scraping, parsing, OCR/browser tooling, async utilities, and Groq. |
| `.env.example` | Template for local provider API key configuration. |

Generated runtime files such as `.env`, `ctri_results.json`, `ctri_progress.json`, `test_results.json`, `results/`, and `results_ctri/` are ignored by git.

## Requirements

- Python 3.10 or newer.
- A Groq API key with access to the configured vision/chat model.
- Optional API keys for Zerve AI, Tinyfish AI, and Firecrawl if you extend the scraper with those providers.
- Internet access to `https://ctri.nic.in`.
- Optional: Tesseract OCR installed locally if you extend the OCR path through `pytesseract`.
- Optional: Playwright browsers if you add browser-driven scraping flows.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a local `.env` file:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and set:

```text
GROQ_API_KEY=your_groq_api_key_here
GROQ_API_KEY_FALLBACK=your_backup_groq_api_key_here
CAPTCHA_SOLVERS=groq,tesseract,manual
ZERVE_API_KEY=your_zerve_api_key_here
TINYFISH_API_KEY=your_tinyfish_api_key_here
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
```

For multiple Groq keys, either use `GROQ_API_KEY` plus `GROQ_API_KEY_FALLBACK`, or provide a comma-separated list in `GROQ_API_KEYS`.
`CAPTCHA_SOLVERS` controls fallback order. The default is `groq,tesseract,manual`.

If you plan to use Playwright-based extensions, install browser binaries:

```powershell
python -m playwright install
```

## Usage

Run the default scrape for the `lung` keyword:

```powershell
python scraper.py
```

Run a small capped scrape:

```powershell
python scraper.py --keyword lung --max-records 10 --workers 3 --delay 0.75
```

Write to custom files:

```powershell
python scraper.py --keyword asthma --output asthma_results.json --progress asthma_progress.json
```

Force a fresh run instead of resuming:

```powershell
python scraper.py --keyword lung --no-resume
```

Pass the Groq API key directly for one run:

```powershell
python scraper.py --api-key "your_groq_api_key_here"
```

## CLI options

| Option | Default | Description |
| --- | --- | --- |
| `--keyword` | `lung` | CTRI search keyword. |
| `--max-records` | unlimited | Maximum number of detail records to scrape. |
| `--output` | `ctri_results.json` | Combined output JSON path. |
| `--progress` | `ctri_progress.json` | Resume checkpoint path. |
| `--workers` | `5` | Number of concurrent detail-page workers. |
| `--delay` | `0.5` | Delay before each detail request. |
| `--api-key` | environment / `.env` | Groq API key override. |
| `--no-resume` | off | Deletes the progress file before starting. |

## Provider configuration

The current scraper uses Groq for CAPTCHA solving. Zerve AI, Tinyfish AI, and Firecrawl keys are reserved in `.env.example` for provider-specific extensions, orchestration, or alternate extraction flows.

| Environment variable | Used now | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | yes | Primary Groq key for CAPTCHA image solving. |
| `GROQ_API_KEY_FALLBACK` | yes | Backup Groq key if the primary fails. |
| `GROQ_API_KEYS` | yes | Optional comma-separated Groq key list. |
| `CAPTCHA_SOLVERS` | yes | Ordered CAPTCHA fallback list: `groq`, `tesseract`, `manual`. |
| `ZERVE_API_KEY` | reserved | Zerve AI integration key. |
| `TINYFISH_API_KEY` | reserved | Tinyfish AI integration key. |
| `FIRECRAWL_API_KEY` | reserved | Firecrawl integration key. |

CAPTCHA fallback behavior:

- `groq` tries every configured Groq key in order.
- `tesseract` uses local OCR through `pytesseract`; install the Tesseract executable separately and ensure it is on PATH.
- `manual` prompts for typed CAPTCHA text only when the script is run from an interactive terminal.

## Output format

The combined output is a JSON array. Each item follows the `ClinicalTrial` model from `schema.py` and can include:

- registry metadata such as `ctri_number`, `registration_date`, `last_modified_on`, and registration timing;
- titles, acronym, trial type, study type, design, phase, and recruitment status;
- principal investigator and scientific/public contact details;
- sponsors, support sources, recruitment countries, study sites, ethics committees, and DCGI status;
- health conditions, interventions, inclusion and exclusion criteria;
- primary and secondary outcomes;
- sample-size fields, enrollment dates, duration, publications, IPD statement, and summary.

Split combined output into one file per trial:

```powershell
python split_results.py
```

That writes files like:

```text
results/CTRI_2010_091_000440.json
results/CTRI_2007_091_000017.json
```

## Resume behavior

The scraper writes `ctri_progress.json` while running. If the file exists and the keyword matches, the next run reuses the stored trial list, cookies, and already parsed records. A completed full run removes the checkpoint after exporting the final combined JSON. Use `--no-resume` to discard the checkpoint and start from a fresh CTRI search.

## Testing

The smoke test executes a real capped scrape, so it needs network access and a valid Groq key:

```powershell
python -m unittest test_scraper.py
```

The test expects a successful run with up to three records and checks that key schema fields exist in each returned record.

## Notes for contributors

- Keep secrets out of source. Use `.env`, `GROQ_API_KEY`, or `--api-key`.
- Start with low `--max-records`, lower `--workers`, and a polite `--delay` when testing changes against the live CTRI site.
- If CTRI changes its HTML, update `parse_detail_html()` and the table parsing helpers in `scraper.py`.
- Generated datasets can become large; keep runtime output out of git unless a release explicitly needs a sample artifact.
