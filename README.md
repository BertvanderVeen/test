# Norway Ecology Jobs

A static website that auto-fetches and lists ecology and statistical ecology job postings from Norwegian institutions, updated daily via GitHub Actions.

**Live at:** `https://<your-username>.github.io/<repo-name>/`

---

## What it tracks

Permanent, postdoc, and PhD positions in:
- Ecological statistics / statistical ecology / quantitative ecology
- Biodiversity research, species distribution modelling, population ecology
- Community ecology, evolutionary biology, nature research

**Sources scraped** (all public, no authentication required):

| Source | Type | Notes |
|---|---|---|
| University of Oslo (UiO) | Direct | Static HTML vacancies pages |
| NINA | Direct | Careers portal |
| NIVA | Direct | Vacancies page |
| NMBU | Direct | Vacancies page |
| NTNU | Via aggregator | scholaridea.com (Jobbnorge is JS-only) |
| Jobbnorge RSS | RSS feed | Multiple URL patterns attempted |
| scholarshipdb.net | Aggregator | Indexes Jobbnorge, EU portals |
| academicpositions.com | Aggregator | International academic jobs |
| EURAXESS | EU portal | Norway-filtered |

**Jobbnorge** (the primary Norwegian academic job board) requires JavaScript to render search results and cannot be scraped directly. The curated portal links in the footer of the site give you direct search URLs for manual checking.

---

## Setup

### 1. Fork or create the repository

```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
```

### 2. Push to GitHub

```bash
git add .
git commit -m "initial commit"
git push origin main
```

### 3. Enable GitHub Pages

In your repository → **Settings → Pages**:
- Source: **Deploy from a branch**
- Branch: `main` / folder: `/docs`
- Save

Your site will be live at `https://<username>.github.io/<repo>/`.

### 4. Run the first fetch

In your repository → **Actions → Fetch Norway Ecology Jobs → Run workflow**.

The Action commits the populated `docs/data/jobs.json` back to the repo, triggering a Pages rebuild. After ~2 minutes the site will show results.

After that the Action runs automatically every day at 06:00 UTC.

### 5. (Optional) Local testing

```bash
pip install -r requirements.txt
python scripts/fetch_jobs.py          # writes docs/data/jobs.json

cd docs
python3 -m http.server 8000           # serve the site locally
# open http://localhost:8000
```

Note: `fetch()` in the browser requires an HTTP server — opening `index.html` directly as a `file://` URL will fail to load `jobs.json`.

---

## File structure

```
.
├── docs/
│   ├── index.html          ← Static site (served by GitHub Pages)
│   └── data/
│       └── jobs.json       ← Auto-updated by GitHub Action
├── scripts/
│   └── fetch_jobs.py       ← Scraper
├── requirements.txt
├── .github/
│   └── workflows/
│       └── fetch-jobs.yml  ← Scheduled GitHub Action
└── README.md
```

---

## Extending the scraper

Add a new source function to `scripts/fetch_jobs.py` following the existing pattern:

```python
def scrape_mysource() -> list[dict]:
    jobs = []
    resp = SESSION.get('https://example.com/vacancies', timeout=TIMEOUT)
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        title = a.get_text(strip=True)
        href = a['href']
        jobs.append(make_job(title, href, institution='My Org', source='example.com'))
    return jobs
```

Then add it to the `SOURCES` list at the bottom of the file.

---

## Keyword tuning

Edit `ECOLOGY_KEYWORDS` and `STATS_HIGHLIGHT_KEYWORDS` in `fetch_jobs.py` to broaden or narrow the relevance filter. The `★ Stats/Quant only` button in the UI surfaces only positions that match `STATS_HIGHLIGHT_KEYWORDS`.

---

## Limitations

- **Jobbnorge** is JS-rendered; its search cannot be scraped without a headless browser. The scheduled Action does not use Playwright/Selenium to keep dependencies light. Use the curated portal links in the site footer for manual Jobbnorge checking.
- Some source pages return empty or inconsistently structured HTML; the scraper fails gracefully (logs a warning, returns zero results for that source).
- Deadline parsing is regex-based and may miss or misread some date formats.
- Permanent positions in Norway are rare and advertised for short windows (~4–8 weeks). Check at least weekly.
