#!/usr/bin/env python3
"""
Scraper for ecology / statistical ecology job positions in Norway and Sweden.
Run by GitHub Actions on a schedule; writes docs/data/jobs.json.

Norway sources:  Jobbnorge API/RSS, UiO, NINA, NIVA, NMBU, NTNU,
                 academicpositions.com, scholarshipdb.net, nature.com
Sweden sources:  SLU, Stockholm University, Uppsala University,
                 Umeå University, Lund University, NRM, nature.com
"""

import requests
from bs4 import BeautifulSoup
import feedparser
import json
import hashlib
import os
import sys
import re
import time
import random
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, '..', 'docs', 'data', 'jobs.json')

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept':           'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language':  'en-US,en;q=0.9,nb;q=0.8',
    'Accept-Encoding':  'gzip, deflate, br',
    'Sec-Fetch-Dest':   'document',
    'Sec-Fetch-Mode':   'navigate',
    'Sec-Fetch-Site':   'none',
})
TIMEOUT     = 25
MAX_RETRIES = 3

# ── Keywords ──────────────────────────────────────────────────────────────────
# Ecology: 'ecolog' matches ecology/ecological/ecologist. That's it.
# Statistics: statistical/statistician/biostatistics in an ecological context.
# A job is relevant if it matches at least one from each, OR a compound term.

ECOLOGY_TERMS = ['ecolog']   # matches ecology, ecological, ecologist

STATS_TERMS = [
    'statistical ecol',      # statistical ecology
    'ecological statistic',  # ecological statistics
    'quantitative ecol',     # quantitative ecology
    'biostatistic',          # biostatistics
]

# Stats-highlighted badge: same terms
STATS_HIGHLIGHT_KEYWORDS = STATS_TERMS[:]

# Positions to hard-exclude regardless of keyword match
EXCLUDE_MARKERS = [
    'phd candidate', 'ph.d. candidate', 'doctoral fellow', 'stipendiat',
    'phd position', 'phd fellowship', 'phd fellow', 'phd research fellow',
    'research assistant', 'research trainee', 'student assistant',
    'internship', 'intern position', 'master student', 'visiting student',
]

# Countries that are in scope — anything else from aggregators is dropped
IN_SCOPE_LOCATIONS = ['norway', 'norge', 'sweden', 'sverige',
                      'oslo', 'bergen', 'trondheim', 'tromsø', 'tromsoe',
                      'stavanger', 'kristiansand', 'ås', 'innlandet',
                      'stockholm', 'uppsala', 'umeå', 'umea', 'lund',
                      'gothenburg', 'göteborg', 'linköping']

POSTDOC_MARKERS   = ['postdoc', 'post-doc', 'postdoctoral', 'post doc',
                     'postdoctoral fellow', 'postdoctoral researcher',
                     'postdoctoral research fellow']
PERMANENT_MARKERS = ['professor', 'associate professor', 'assistant professor',
                     'førsteamanuensis', 'amanuensis', 'dosent',
                     'permanent', 'fast stilling', 'senior researcher',
                     'senior forsker', 'principal researcher', 'chief researcher',
                     'section leader', 'group leader', 'head of', 'researcher']

SKIP_NAV = ['contact us','about us','cookie','privacy policy','home page',
            'sign in','log in','register','subscribe','newsletter',
            'read more about','click here','see all jobs','show all',
            'back to','apply for this job']

AGGREGATOR_SOURCES = {'academicpositions.com', 'scholarshipdb.net'}


def is_ecology_relevant(title, description=''):
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in ECOLOGY_TERMS) or any(kw in text for kw in STATS_TERMS)

def is_stats_highlight(title, description=''):
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in STATS_HIGHLIGHT_KEYWORDS)

def is_excluded(title, description=''):
    text = (title + ' ' + description).lower()
    return any(m in text for m in EXCLUDE_MARKERS)

def is_in_scope_location(location, description=''):
    """Return True if job is in Norway or Sweden based on declared location or text."""
    text = (location + ' ' + description).lower()
    return any(loc in text for loc in IN_SCOPE_LOCATIONS)

def classify_type(title, description=''):
    text = (title + ' ' + description).lower()
    if any(m in text for m in POSTDOC_MARKERS):   return 'postdoc'
    if any(m in text for m in PERMANENT_MARKERS): return 'permanent'
    return 'unknown'

def relevance_score(title, description=''):
    text = (title + ' ' + description).lower()
    score = sum(5 for kw in STATS_TERMS if kw in text)
    score += sum(1 for kw in ECOLOGY_TERMS if kw in text)
    return score

def make_job_id(url): return hashlib.sha256(url.encode()).hexdigest()[:16]

def looks_like_nav(title):
    t = title.strip()
    if len(t) < 12 or len(t) > 220: return True
    return any(f in t.lower() for f in SKIP_NAV)

def extract_deadline(text):
    for pat in [
        r'deadline[:\s]+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})',
        r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            c = m.group(1)[:35]
            if re.search(r'20\d{2}', c): return c
    return None

# ── Institution classification ────────────────────────────────────────────────
NORWAY_UNIVERSITIES = ['uio', 'university of oslo', 'uib', 'university of bergen',
                       'uit', 'arctic university', 'ntnu', 'nmbu', 'inn university',
                       'hvl', 'western norway university', 'university of agder', 'uia',
                       'university of stavanger', 'uis', 'nord university']
NORWAY_INSTITUTES   = ['nina', 'niva', 'nibio', 'imr', 'institute of marine',
                       'norsk institutt', 'havforskningsinstituttet']
SWEDEN_UNIVERSITIES = ['slu', 'swedish university of agricultural', 'uppsala university',
                       'stockholm university', 'umeå university', 'umea university',
                       'lund university', 'gothenburg university', 'linköping university',
                       'chalmers', 'kth']
SWEDEN_INSTITUTES   = ['nrm', 'swedish museum of natural history', 'ivl',
                       'swedish environmental research']

def infer_country_and_type(institution, source, location):
    inst_l = institution.lower()
    src_l  = source.lower()
    loc_l  = location.lower()

    # Country from source domain first (most reliable)
    if any(d in src_l for d in ['uio.no','uib.no','nina.no','niva.no','nmbu.no',
                                  'ntnu.edu','inn.no','hvl.no','uia.no','uis.no',
                                  'jobbnorge.no']):
        country = 'norway'
    elif any(d in src_l for d in ['slu.se','su.se','uu.se','umu.se','lu.se','nrm.se']):
        country = 'sweden'
    elif any(c in loc_l for c in ['sweden','sverige','stockholm','uppsala','umeå',
                                   'umea','lund','gothenburg']):
        country = 'sweden'
    else:
        country = 'norway'  # default for this tracker

    # Institution type from name
    if any(k in inst_l for k in SWEDEN_INSTITUTES + NORWAY_INSTITUTES):
        inst_type = 'institute'
    elif any(k in inst_l for k in SWEDEN_UNIVERSITIES + NORWAY_UNIVERSITIES):
        inst_type = 'university'
    else:
        # Fallback: 'university' in name → university; else institute
        inst_type = 'university' if 'universit' in inst_l else 'institute'

    return country, inst_type


def make_job(title, url, institution='', location='Norway',
             deadline=None, description='', source='', job_type=None):
    desc  = re.sub(r'\s+', ' ', description).strip()[:700]
    jtype = job_type if job_type else classify_type(title, desc)
    country, inst_type = infer_country_and_type(institution, source, location)
    return {
        'id':             make_job_id(url),
        'title':          title.strip(),
        'institution':    institution.strip(),
        'location':       location.strip(),
        'country':        country,
        'inst_type':      inst_type,
        'url':            url,
        'deadline':       deadline,
        'type':           jtype,
        'description':    desc,
        'source':         source,
        'aggregator':     source in AGGREGATOR_SOURCES,
        'stats_highlight':is_stats_highlight(title, desc),
        'relevant':       (is_ecology_relevant(title, desc)
                          and not is_excluded(title, desc)
                          and is_in_scope_location(location, desc)),
        'relevance_score':relevance_score(title, desc),
        'fetched_at':     datetime.now(timezone.utc).isoformat(),
    }

def get_html(url, extra_headers=None):
    parsed = urlparse(url)
    hdrs   = {'Referer': f'{parsed.scheme}://{parsed.netloc}/'}
    if extra_headers: hdrs.update(extra_headers)
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, headers=hdrs, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code is None or code in (400, 403, 404, 410):
                return None  # no point retrying
            wait = 2.0 * (2 ** attempt) + random.uniform(0, 0.5)
            print(f'  HTTP {code} on {url} (attempt {attempt+1}), retry in {wait:.1f}s', file=sys.stderr)
            time.sleep(wait)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == MAX_RETRIES - 1:
                print(f'  Failed after {MAX_RETRIES} attempts: {url}', file=sys.stderr)
                return None
            wait = 2.0 * (2 ** attempt) + random.uniform(0, 0.5)
            print(f'  {type(exc).__name__} (attempt {attempt+1}), retry in {wait:.1f}s', file=sys.stderr)
            time.sleep(wait)
        except requests.RequestException as exc:
            print(f'  {exc}', file=sys.stderr)
            return None
    return None

def delay(): time.sleep(random.uniform(0.8, 1.8))


# ─── Sources ──────────────────────────────────────────────────────────────────

def fetch_jobbnorge_api():
    """Probe Jobbnorge undocumented JSON API endpoints. Fail silently — expected to 404."""
    probes = [
        'https://www.jobbnorge.no/api/jobad/search?q={q}&lang=en&pagesize=50',
        'https://www.jobbnorge.no/api/search?q={q}&lang=en&pagesize=50',
        'https://www.jobbnorge.no/search/api?q={q}&lang=en',
    ]
    queries = ['ecology', 'ecologist', 'biodiversity', 'statistical ecology',
               'quantitative ecology', 'population ecology']
    for pattern in probes:
        for q in queries:
            url = pattern.format(q=q)
            try:
                resp = SESSION.get(url, headers={
                    'Accept': 'application/json',
                    'Referer': 'https://www.jobbnorge.no/'
                }, timeout=TIMEOUT)
                # Only proceed on genuine 200 JSON response
                if resp.status_code != 200:
                    continue
                if 'json' not in resp.headers.get('Content-Type', ''):
                    continue
                data  = resp.json()
                items = (data.get('jobs') or data.get('results') or
                         data.get('items') or data.get('hits') or
                         (data if isinstance(data, list) else []))
                jobs = []
                for item in items:
                    if not isinstance(item, dict): continue
                    title = item.get('title') or item.get('Title') or item.get('jobTitle') or ''
                    link  = item.get('url') or item.get('link') or item.get('applicationUrl') or ''
                    inst  = item.get('employer') or item.get('organization') or ''
                    desc  = item.get('description') or item.get('ingress') or ''
                    dl    = item.get('deadline') or item.get('applicationDeadline') or ''
                    if title and link:
                        jobs.append(make_job(title, link, institution=inst,
                                             deadline=dl, description=desc,
                                             source='jobbnorge.no'))
                if jobs:
                    print(f'  [jobbnorge-api] OK: {url}')
                    return jobs
            except Exception:
                pass  # probe failures are expected and silent
    return []


def fetch_jobbnorge_rss():
    patterns = [
        'https://www.jobbnorge.no/rss/en/jobs?q=ecology',
        'https://www.jobbnorge.no/rss/en/jobs?q=biodiversity',
        'https://www.jobbnorge.no/rss/en/jobs?q=ecologist',
        'https://www.jobbnorge.no/search/en?q=ecology&format=rss',
    ]
    for rss_url in patterns:
        try:
            feed = feedparser.parse(rss_url)
            if feed.entries:
                jobs = []
                for e in feed.entries:
                    title   = e.get('title','')
                    link    = e.get('link','')
                    summary = e.get('summary', e.get('description',''))
                    dl      = e.get('published', None)
                    if title and link:
                        jobs.append(make_job(title, link, deadline=dl,
                                             description=summary, source='jobbnorge.no'))
                print(f'  [jobbnorge-rss] OK: {rss_url} → {len(jobs)} entries')
                return jobs
        except Exception as exc:
            print(f'  [jobbnorge-rss] {rss_url}: {exc}', file=sys.stderr)
    return []


def scrape_uio():
    jobs = []
    for url, inst, loc in [
        ('https://www.uio.no/english/about/vacancies/last-published.html','University of Oslo','Oslo'),
        ('https://www.mn.uio.no/english/about/vacancies/','University of Oslo (MN)','Oslo'),
    ]:
        delay(); resp = get_html(url)
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        main = soup.find('div', id='main-content') or soup.find('main') or soup
        for a in main.find_all('a', href=True):
            title = a.get_text(strip=True)
            href  = a['href']
            if not href.startswith('http'): href = urljoin('https://www.uio.no', href)
            if looks_like_nav(title): continue
            domain = urlparse(href).netloc
            if not any(d in domain for d in ['uio.no','jobbnorge.no']): continue
            ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
            jobs.append(make_job(title, href, institution=inst, location=loc,
                                 deadline=extract_deadline(ctx),
                                 description=ctx, source='uio.no'))
    return jobs


def scrape_nina():
    jobs = []
    delay(); resp = get_html('https://nina-english.attract.reachmee.com/jobs')
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://nina-english.attract.reachmee.com', href)
        if looks_like_nav(title): continue
        if 'reachmee' not in href and 'nina' not in href.lower(): continue
        ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
        jobs.append(make_job(title, href, institution='NINA', location='Norway',
                             deadline=extract_deadline(ctx), description=ctx, source='nina.no'))
    return jobs


def scrape_niva():
    jobs = []
    for url in ['https://www.niva.no/en/vacancies']:
        delay(); resp = get_html(url)
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        main = soup.find('main') or soup
        for a in main.find_all('a', href=True):
            title = a.get_text(strip=True)
            href  = a['href']
            if not href.startswith('http'): href = urljoin(url, href)
            if looks_like_nav(title): continue
            ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
            jobs.append(make_job(title, href, institution='NIVA', location='Norway',
                                 deadline=extract_deadline(ctx), description=ctx, source='niva.no'))
    return jobs


def scrape_nmbu():
    jobs = []
    delay(); resp = get_html('https://www.nmbu.no/en/about/vacancies')
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    main = soup.find('main') or soup.find('div', class_=re.compile(r'\b(content|main|article)\b')) or soup
    for a in main.find_all('a', href=True):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://www.nmbu.no', href)
        if looks_like_nav(title): continue
        ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
        jobs.append(make_job(title, href, institution='NMBU', location='Ås',
                             deadline=extract_deadline(ctx), description=ctx, source='nmbu.no'))
    return jobs


def scrape_ntnu():
    """NTNU — Dept of Biology and Dept of Mathematical Sciences are the relevant units."""
    jobs = []
    for url in [
        'https://scholaridea.com/job-vacancies-at-norwegian-university/',
        'https://scholarshipdb.net/vacancies-scholarships-in-Norway?em=NTNU-Norwegian-University-of-Science-and-Technology',
    ]:
        delay(); resp = get_html(url)
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            title = a.get_text(strip=True)
            href  = a['href']
            if not href.startswith('http'): href = urljoin(url, href)
            if looks_like_nav(title): continue
            if not any(d in href.lower() for d in ['ntnu','jobbnorge']): continue
            ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
            jt  = classify_type(title, ctx)
            jobs.append(make_job(title, href, institution='NTNU', location='Trondheim',
                                 deadline=extract_deadline(ctx), description=ctx,
                                 job_type=jt, source='ntnu.edu'))
        if jobs: break
    return jobs


def _scrape_static_vacancies(url, institution, location, source, allowed_domains=None):
    """Generic scraper for any institution with a static HTML vacancies listing."""
    jobs = []
    delay(); resp = get_html(url)
    if not resp: return jobs
    base_domain = urlparse(url).netloc.replace('www.', '')
    allowed = list(allowed_domains or []) + [base_domain, 'jobbnorge.no']
    soup = BeautifulSoup(resp.text, 'html.parser')
    main = soup.find('main') or soup.find('div', id='main-content') or soup
    for a in main.find_all('a', href=True):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin(url, href)
        if looks_like_nav(title): continue
        domain = urlparse(href).netloc.replace('www.', '')
        if not any(d in domain for d in allowed): continue
        ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
        jobs.append(make_job(title, href, institution=institution, location=location,
                             deadline=extract_deadline(ctx), description=ctx, source=source))
    return jobs


def scrape_uib():
    return _scrape_static_vacancies(
        'https://www.uib.no/en/about/84777/vacant-positions-uib',
        'University of Bergen', 'Bergen', 'uib.no',
    )

def scrape_inn():
    """Inland Norway University — strong in applied ecology (wildlife, forest, moose)."""
    return _scrape_static_vacancies(
        'https://www.inn.no/english/about-inn/work-at-inn-university/vacant-positions/',
        'INN University', 'Innlandet', 'inn.no',
    )

def scrape_hvl():
    """Western Norway University of Applied Sciences."""
    return _scrape_static_vacancies(
        'https://www.hvl.no/en/work-at-hvl/',
        'HVL', 'Western Norway', 'hvl.no',
    )

def scrape_uia():
    """University of Agder — some marine/coastal ecology."""
    return _scrape_static_vacancies(
        'https://www.uia.no/english/about-uia/working-at-uia/vacancies/',
        'University of Agder', 'Kristiansand', 'uia.no',
    )

def scrape_uis():
    """University of Stavanger — environmental sciences."""
    return _scrape_static_vacancies(
        'https://www.uis.no/en/about-uis/vacant-positions-at-uis',
        'University of Stavanger', 'Stavanger', 'uis.no',
    )




def scrape_academicpositions():
    jobs = []
    seen: set = set()
    for url in [
        'https://academicpositions.com/jobs/field/ecology-evolution-behavior/country/norway',
        'https://academicpositions.com/jobs/position/permanent/country/norway',
        'https://academicpositions.com/jobs/country/norway',
    ]:
        delay()
        resp = get_html(url, extra_headers={'Referer': 'https://academicpositions.com/'})
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        cards = soup.select('article, .job-listing, li[class*="job"], div[class*="position"]')
        if not cards: cards = [li for li in soup.find_all('li') if li.find('a')]
        for card in cards:
            a = card.find('a', href=True)
            if not a: continue
            title = a.get_text(strip=True)
            href  = a['href']
            if not href.startswith('http'): href = urljoin(url, href)
            if href in seen or looks_like_nav(title): continue
            seen.add(href)
            ct   = card.get_text(' ', strip=True)
            inst = ''
            el   = card.select_one('.institution, .employer, .university, [class*="organization"]')
            if el: inst = el.get_text(strip=True)
            jobs.append(make_job(title, href, institution=inst, location='Norway',
                                 deadline=extract_deadline(ct), description=ct[:500],
                                 source='academicpositions.com'))
    return jobs


def scrape_scholarshipdb():
    jobs = []
    seen: set = set()
    for url in [
        'https://scholarshipdb.net/ecology-scholarships-in-Norway',
        'https://scholarshipdb.net/biology-scholarships-in-Norway',
        'https://scholarshipdb.net/statistics-scholarships-in-Norway',
    ]:
        delay(); resp = get_html(url)
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        blocks = soup.select('div.scholarship, article, div.item, li.position, .card, .listing')
        if not blocks: blocks = soup.find_all('li')
        for block in blocks:
            a = block.find('a', href=True)
            if not a: continue
            title = a.get_text(strip=True)
            href  = a['href']
            if not href.startswith('http'): href = urljoin(url, href)
            if href in seen or looks_like_nav(title): continue
            seen.add(href)
            bt  = block.get_text(' ', strip=True)
            m   = re.search(r'(University|Institute|NTNU|UiO|UiT|UiB|NMBU|NINA|NIVA|NIBIO|Nord University)[^\n|·]{0,60}', bt, re.IGNORECASE)
            inst = m.group(0).strip() if m else ''
            jobs.append(make_job(title, href, institution=inst, location='Norway',
                                 deadline=extract_deadline(bt), description=bt,
                                 source='scholarshipdb.net'))
    return jobs


def scrape_nature_careers():
    jobs = []
    url  = 'https://www.nature.com/naturecareers/jobs/country/NO/'
    delay()
    resp = get_html(url, extra_headers={'Referer': 'https://www.nature.com/'})
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a in soup.select('h2 a, h3 a, .job-listing a, [data-test="job-title"] a'):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://www.nature.com', href)
        if looks_like_nav(title): continue
        parent = a.parent.parent if (a.parent and a.parent.parent) else a.parent
        ctx = parent.get_text(' ', strip=True) if parent else ''
        jobs.append(make_job(title, href, location='Norway',
                             deadline=extract_deadline(ctx),
                             description=ctx[:400], source='nature.com/naturecareers'))
    return jobs


# ─── Sweden ───────────────────────────────────────────────────────────────────
# All major Swedish universities use Varbi ATS, which exposes a public RSS feed
# at {org}.varbi.com/what:rssfeed/  — reliable, no HTML parsing needed.
# SLU uses ReachMee embedded in slu.se.
# Added Gothenburg University (marine/aquatic ecology).

VARBI_ORGS = {
    'Uppsala University':    ('uu',  'Uppsala',     'uu.se'),
    'Stockholm University':  ('su',  'Stockholm',   'su.se'),
    'Umeå University':       ('umu', 'Umeå',        'umu.se'),
    'Lund University':       ('lu',  'Lund',        'lu.se'),
    'Gothenburg University': ('gu',  'Gothenburg',  'gu.se'),
}

def _scrape_varbi_rss(org_slug, institution, location, source):
    """Fetch all vacancies from a university's public Varbi RSS feed."""
    jobs = []
    url = f'https://{org_slug}.varbi.com/what:rssfeed/'
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title   = entry.get('title', '').strip()
            link    = entry.get('link', '')
            summary = entry.get('summary', entry.get('description', ''))
            dl      = entry.get('published', None)
            if title and link:
                jobs.append(make_job(title, link, institution=institution,
                                     location=location, deadline=dl,
                                     description=summary, source=source))
    except Exception as exc:
        print(f'  [{org_slug}.varbi] {exc}', file=sys.stderr)
    return jobs


def scrape_sweden_varbi():
    """Fetch all Swedish Varbi university feeds."""
    jobs = []
    for institution, (slug, location, source) in VARBI_ORGS.items():
        delay()
        jobs.extend(_scrape_varbi_rss(slug, institution, location, source))
    return jobs


def scrape_slu():
    """SLU uses ReachMee via slu.se — correct URL confirmed."""
    jobs = []
    url = 'https://www.slu.se/en/about-slu/work-at-slu/jobs-and-vacancies/'
    delay()
    resp = get_html(url, extra_headers={'Referer': 'https://www.slu.se/'})
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    main = soup.find('main') or soup
    for a in main.find_all('a', href=True):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://www.slu.se', href)
        if looks_like_nav(title): continue
        if not any(d in urlparse(href).netloc for d in ['slu.se', 'varbi.com', 'reachmee.com']):
            continue
        ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
        jobs.append(make_job(title, href, institution='SLU', location='Sweden',
                             deadline=extract_deadline(ctx), description=ctx, source='slu.se'))
    return jobs


def scrape_nrm():
    """Swedish Museum of Natural History."""
    jobs = []
    url = 'https://www.nrm.se/en/aboutthemuseum/workatthemuseum.9000254.html'
    delay()
    resp = get_html(url)
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    main = soup.find('main') or soup
    for a in main.find_all('a', href=True):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://www.nrm.se', href)
        if looks_like_nav(title): continue
        if 'nrm.se' not in urlparse(href).netloc: continue
        ctx = a.parent.get_text(' ', strip=True) if a.parent else ''
        jobs.append(make_job(title, href, institution='Swedish Museum of Natural History',
                             location='Stockholm', deadline=extract_deadline(ctx),
                             description=ctx, source='nrm.se'))
    return jobs


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def deduplicate(jobs):
    seen_ids, seen_urls, result = set(), set(), []
    for j in jobs:
        if j['id'] in seen_ids or j['url'] in seen_urls: continue
        seen_ids.add(j['id']); seen_urls.add(j['url']); result.append(j)
    return result

def filter_relevant(jobs): return [j for j in jobs if j.get('relevant', False)]

def filter_expired(jobs):
    """Drop jobs with a parseable deadline that has already passed."""
    from datetime import date
    import re
    today = date.today()
    result = []
    for job in jobs:
        dl = job.get('deadline')
        if not dl:
            result.append(job)
            continue
        # Try ISO date first, then dd.mm.yyyy, then give benefit of doubt
        parsed = None
        try:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', dl)
            if m:
                parsed = date.fromisoformat(m.group(1))
            else:
                m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', dl)
                if m:
                    parsed = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except Exception:
            pass
        if parsed is None or parsed >= today:
            result.append(job)
    return result

def sort_jobs(jobs):
    order = {'permanent':0,'postdoc':1,'unknown':2}
    return sorted(jobs, key=lambda j: (order.get(j['type'],9), -j.get('relevance_score',0)))


SOURCES = [
    # ── Norway ──────────────────────────────────────────────────────────────
    ('jobbnorge-api',     fetch_jobbnorge_api),
    ('jobbnorge-rss',     fetch_jobbnorge_rss),
    ('uio',               scrape_uio),
    ('uib',               scrape_uib),
    ('nina',              scrape_nina),
    ('niva',              scrape_niva),
    ('nmbu',              scrape_nmbu),
    ('ntnu',              scrape_ntnu),
    ('inn',               scrape_inn),
    ('hvl',               scrape_hvl),
    ('uia',               scrape_uia),
    ('uis',               scrape_uis),
    ('academicpositions', scrape_academicpositions),
    ('scholarshipdb',     scrape_scholarshipdb),
    ('nature-careers-no', scrape_nature_careers),
    # ── Sweden ───────────────────────────────────────────────────────────────
    # Varbi RSS covers Uppsala, Stockholm, Umeå, Lund, Gothenburg
    ('sweden-varbi',      scrape_sweden_varbi),
    ('slu',               scrape_slu),
    ('nrm',               scrape_nrm),
]


def main():
    now = datetime.now(timezone.utc)
    print(f'Norway & Sweden Ecology Jobs – {now.isoformat()}')
    all_jobs = []

    for name, fn in SOURCES:
        try:
            jobs = fn()
            print(f'  {name:<25} → {len(jobs):3d} raw')
            all_jobs.extend(jobs)
        except Exception as exc:
            print(f'  {name:<25} → FAILED: {exc}', file=sys.stderr)

    deduped  = deduplicate(all_jobs)
    relevant = filter_relevant(deduped)
    active   = filter_expired(relevant)
    sorted_  = sort_jobs(active)

    perm    = sum(1 for j in sorted_ if j['type']=='permanent')
    postdoc = sum(1 for j in sorted_ if j['type']=='postdoc')

    print(f'\n  raw={len(all_jobs)} deduped={len(deduped)} relevant={len(sorted_)} '
          f'(perm={perm} postdoc={postdoc})')

    output = {
        'last_updated': now.isoformat(),
        'stats': {'total': len(sorted_), 'permanent': perm, 'postdoc': postdoc},
        'jobs': sorted_,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
    print(f'  Written → {OUTPUT_PATH}')

if __name__ == '__main__':
    main()
