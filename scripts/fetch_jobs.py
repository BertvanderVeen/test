#!/usr/bin/env python3
"""
Scraper for Norwegian ecology / statistical ecology job positions.
Run by GitHub Actions on a schedule; writes docs/data/jobs.json.
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
    'User-Agent': 'Mozilla/5.0 ...',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,nb;q=0.8',
})
TIMEOUT     = 25
MAX_RETRIES = 3

ECOLOGY_KEYWORDS = [
    'ecolog', 'biodiversity', 'species distribution', 'population biology',
    'population ecol', 'wildlife', 'conservation biolog', 'nature research',
    'naturforsk', 'marine biolog', 'terrestrial ecol', 'evolutionary biolog',
    'biostatistics', 'quantitative biolog', 'quantitative ecol',
    'statistical ecol', 'environmental science', 'bioscience',
    'forest ecol', 'aquatic ecol', 'vegetation ecol', 'community ecol',
    'joint species', 'ordination', 'species modell', 'habitat model',
    'trophic', 'biogeograph', 'macroecol', 'limnolog',
    'zoolog', 'botany', 'plant ecol', 'predator', 'food web',
    'naturforvaltning', 'nature management', 'species richness',
]

STATS_HIGHLIGHT_KEYWORDS = [
    'statistical ecol', 'quantitative ecol', 'ecological statistician',
    'population model', 'species distribution model', 'hierarchical model',
    'bayesian ecol', 'mixed model', 'multivariate ecol',
    'biodiversity statistics', 'biostatistics', 'statistical population',
    'approximate inference', 'occupancy model', 'capture-recapture',
    'mark-recapture', 'spatial capture', 'integrated population',
    'latent variable', 'ordination model', 'joint species distribution',
]

PHD_MARKERS       = ['phd candidate','ph.d.','doctoral fellow','research fellow',
                     'stipendiat','phd position','phd fellowship','phd research fellow']
POSTDOC_MARKERS   = ['postdoc','post-doc','postdoctoral','post doc',
                     'research associate','postdoctoral fellow','postdoctoral researcher']
PERMANENT_MARKERS = ['professor','associate professor','assistant professor',
                     'førsteamanuensis','amanuensis','dosent',
                     'permanent','fast stilling','senior researcher',
                     'senior forsker','researcher','forsker',
                     'principal researcher','chief researcher']

SKIP_NAV = ['contact us','about us','cookie','privacy policy','home page',
            'sign in','log in','register','subscribe','newsletter',
            'read more about','click here','see all jobs','show all',
            'back to','apply for this job']


def is_ecology_relevant(title, description=''):
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in ECOLOGY_KEYWORDS)

def is_stats_highlight(title, description=''):
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in STATS_HIGHLIGHT_KEYWORDS)

def classify_type(title, description=''):
    text = (title + ' ' + description).lower()
    if any(m in text for m in PHD_MARKERS):      return 'phd'
    if any(m in text for m in POSTDOC_MARKERS):  return 'postdoc'
    if any(m in text for m in PERMANENT_MARKERS): return 'permanent'
    return 'unknown'

def relevance_score(title, description=''):
    text = (title + ' ' + description).lower()
    score = sum(5 for kw in STATS_HIGHLIGHT_KEYWORDS if kw in text)
    score += sum(1 for kw in ECOLOGY_KEYWORDS if kw in text)
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

def make_job(title, url, institution='', location='Norway',
             deadline=None, description='', source='', job_type=None):
    desc  = re.sub(r'\s+', ' ', description).strip()[:700]
    jtype = job_type if job_type else classify_type(title, desc)
    return {
        'id':             make_job_id(url),
        'title':          title.strip(),
        'institution':    institution.strip(),
        'location':       location.strip(),
        'url':            url,
        'deadline':       deadline,
        'type':           jtype,
        'description':    desc,
        'source':         source,
        'stats_highlight':is_stats_highlight(title, desc),
        'relevant':       is_ecology_relevant(title, desc),
        'relevance_score':relevance_score(title, desc),
        'fetched_at':     datetime.now(timezone.utc).isoformat(),
    }

def get_html(url, extra_headers=None):
    parsed = urlparse(url)
    hdrs = {'Referer': f'{parsed.scheme}://{parsed.netloc}/'}
    if extra_headers:
        hdrs.update(extra_headers)

    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, headers=hdrs, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp

        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response else '?'
            if code in (403, 404):
                return None

            wait = 2.0 * (2 ** attempt) + random.uniform(0, 0.5)
            print(f'HTTP {code} attempt {attempt+1} – retry in {wait:.1f}s', file=sys.stderr)
            time.sleep(wait)

        except requests.RequestException as exc:
            import traceback
            traceback.print_exc()

            wait = 2.0 * (2 ** attempt) + random.uniform(0, 0.5)
            print(f'Connection error – retry in {wait:.1f}s', file=sys.stderr)
            time.sleep(wait)

    return None

def delay(): time.sleep(random.uniform(0.8, 1.8))


# ─── Sources ──────────────────────────────────────────────────────────────────

def fetch_jobbnorge_api():
    """Probe Jobbnorge undocumented JSON API endpoints."""
    probes = [
        'https://www.jobbnorge.no/api/jobad/search?q={q}&lang=en&pagesize=50',
        'https://www.jobbnorge.no/api/search?q={q}&lang=en&pagesize=50',
        'https://www.jobbnorge.no/search/api?q={q}&lang=en',
    ]
    queries = ['ecology', 'ecologist', 'biodiversity', 'statistician']
    for pattern in probes:
        for q in queries:
            url = pattern.format(q=q)
            try:
                resp = SESSION.get(url, headers={
                    'Accept': 'application/json',
                    'Referer': 'https://www.jobbnorge.no/'
                }, timeout=TIMEOUT)
                if resp.status_code == 200 and 'json' in resp.headers.get('Content-Type',''):
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
                pass
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
    for url in ['https://www.niva.no/en/about-niva/vacancies',
                'https://www.niva.no/en/about-niva/work-with-us']:
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
    delay(); resp = get_html('https://www.nmbu.no/en/about-nmbu/vacancies')
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


def scrape_euraxess():
    jobs = []
    url  = 'https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=country%3ANO'
    delay()
    resp = get_html(url, extra_headers={'Referer': 'https://euraxess.ec.europa.eu/'})
    if not resp: return jobs
    soup = BeautifulSoup(resp.text, 'html.parser')
    for a in soup.select('h3 a, h2 a, .views-field-title a, .job-title a'):
        title = a.get_text(strip=True)
        href  = a['href']
        if not href.startswith('http'): href = urljoin('https://euraxess.ec.europa.eu', href)
        if looks_like_nav(title): continue
        parent = (a.parent.parent if a.parent and a.parent.parent else a.parent)
        ctx = parent.get_text(' ', strip=True) if parent else ''
        m   = re.search(r'(University|Institute|NTNU|UiO|UiT|UiB|NMBU|NINA|NIVA)', ctx, re.IGNORECASE)
        jobs.append(make_job(title, href, institution=m.group(0) if m else '',
                             location='Norway', deadline=extract_deadline(ctx),
                             description=ctx[:400], source='euraxess.eu'))
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


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def deduplicate(jobs):
    seen_ids, seen_urls, result = set(), set(), []
    for j in jobs:
        if j['id'] in seen_ids or j['url'] in seen_urls: continue
        seen_ids.add(j['id']); seen_urls.add(j['url']); result.append(j)
    return result

def filter_relevant(jobs): return [j for j in jobs if j.get('relevant', False)]

def sort_jobs(jobs):
    order = {'permanent':0,'unknown':1,'postdoc':2,'phd':3}
    return sorted(jobs, key=lambda j: (order.get(j['type'],9), -j.get('relevance_score',0)))


SOURCES = [
    ('jobbnorge-api',     fetch_jobbnorge_api),
    ('jobbnorge-rss',     fetch_jobbnorge_rss),
    ('uio',               scrape_uio),
    ('nina',              scrape_nina),
    ('niva',              scrape_niva),
    ('nmbu',              scrape_nmbu),
    ('ntnu',              scrape_ntnu),
    ('academicpositions', scrape_academicpositions),
    ('scholarshipdb',     scrape_scholarshipdb),
    ('euraxess',          scrape_euraxess),
    ('nature-careers',    scrape_nature_careers),
]


def main():
    now = datetime.now(timezone.utc)
    print(f'Norway Ecology Jobs – {now.isoformat()}')
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
    sorted_  = sort_jobs(relevant)

    perm    = sum(1 for j in sorted_ if j['type']=='permanent')
    postdoc = sum(1 for j in sorted_ if j['type']=='postdoc')
    phd     = sum(1 for j in sorted_ if j['type']=='phd')

    print(f'\n  raw={len(all_jobs)} deduped={len(deduped)} relevant={len(sorted_)} '
          f'(perm={perm} postdoc={postdoc} phd={phd})')

    output = {
        'last_updated': now.isoformat(),
        'stats': {'total': len(sorted_), 'permanent': perm, 'postdoc': postdoc, 'phd': phd},
        'jobs': sorted_,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
    print(f'  Written → {OUTPUT_PATH}')

if __name__ == '__main__':
    main()
