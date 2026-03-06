# 🤖 Job Application Agent

A fully automated job application pipeline: **scrape → score → tailor → apply**.

## Architecture

```
Scheduler (APScheduler)
    │
    ├── 1. Scraper     — LinkedIn, Indeed, Greenhouse, Lever APIs
    ├── 2. Ranker      — Claude scores each job vs your profile (0-100)
    ├── 3. Generator   — Claude tailors CV + writes cover letter per job
    └── 4. Applier     — Playwright submits forms (LinkedIn Easy Apply, GH, Lever)
         │
         └── Tracker   — SQLite logs all applications + status
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `config.py`

Edit these sections:
- **`CANDIDATE_PROFILE`** — your full profile/CV in plain text
- **`SEARCH_QUERIES`** — keywords to search on job boards
- **`TARGET_COMPANIES`** — specific companies to monitor via ATS API
- **`LOCATIONS`** — where to search (include "Remote")
- **`MIN_MATCH_SCORE`** — threshold (0-100) to decide whether to apply
- **`MAX_APPLICATIONS_PER_DAY`** — daily safety cap

### 3. Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Add your company targets

In `scrapers/scraper.py`, find `COMPANY_ATS_MAP` and add your target companies:

```python
COMPANY_ATS_MAP = {
    "Stripe":   ("greenhouse", "stripe"),
    "YourCo":   ("lever",      "your-company-slug"),
    ...
}
```

To find the slug: visit `https://boards.greenhouse.io/SLUG` or `https://jobs.lever.co/SLUG`.

---

## LinkedIn Authentication (required for LinkedIn Easy Apply)

The agent needs a valid LinkedIn session. Do this once:

```python
# Run this helper script to save your session
python save_linkedin_session.py
```

**`save_linkedin_session.py`:**
```python
import asyncio, json
from playwright.async_api import async_playwright

async def save_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.linkedin.com/login")
        input("Log in manually, then press Enter...")
        cookies = await context.cookies()
        with open("data/linkedin_cookies.json", "w") as f:
            json.dump(cookies, f)
        print("✅ Session saved to data/linkedin_cookies.json")
        await browser.close()

asyncio.run(save_session())
```

---

## Running the Agent

```bash
# Run once
python main.py

# Dry run (scrape + score but don't submit)
python main.py --dry-run

# Run on a schedule (every N hours, set in config.py)
python main.py --loop

# View statistics
python main.py --stats
```

---

## Output

```
data/
├── jobs.db                           # SQLite database
└── applications/
    ├── 20240115_1430_Stripe_Compliance_Manager_CV.txt
    ├── 20240115_1430_Stripe_Compliance_Manager_CoverLetter.txt
    ├── ...
```

---

## Monitoring

Check the database with any SQLite viewer or:

```bash
sqlite3 data/jobs.db "SELECT title, company, match_score, status FROM jobs ORDER BY scraped_at DESC LIMIT 20;"
```

---

## Extending

### Add a new ATS

1. Create `apply_myats(page, job, cv_path, cl_path)` in `appliers/auto_applier.py`
2. Add ATS detection in `detect_ats()` in `scrapers/scraper.py`
3. Route it in `apply_to_job()` in `appliers/auto_applier.py`

### Add a new job board

1. Create `scrape_myboard(page, query, location)` in `scrapers/scraper.py`
2. Add a flag in `config.py` under `ENABLED_SOURCES`
3. Call it in `run_scrapers()`

---

## Caveats & Ethics

- **Never falsify credentials** — the AI is prompted to keep facts truthful
- **Respect rate limits** — built-in delays between requests
- **LinkedIn ToS** — automated scraping may violate their ToS; use responsibly
- **Daily cap** — `MAX_APPLICATIONS_PER_DAY` prevents spam applying
- **Review before enabling** — recommended to run `--dry-run` first to check quality

---

## Roadmap

- [ ] Email notifications when applications are submitted
- [ ] Follow-up email generator (7-day, 14-day)
- [ ] Interview scheduler integration
- [ ] Google Sheets dashboard
- [ ] Workday ATS support
