"""Fetch jobs from RSS and seed data."""
import os
import csv
import sys
import html
import re
import requests
import feedparser
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.database import db

DEFAULT_RSS_URLS = [
    "https://www.jobs.ps/rss/jobs/gaza-jobs",
    "https://www.jobs.ps/en/rss/jobs/gaza-jobs"
]

JOBS_RSS_URL = os.environ.get("JOBS_RSS_URL", "https://www.jobs.ps/rss/jobs/gaza-jobs")

LOCATIONS_MAP = [
    ("خانيونس", "خانيونس - قطاع غزة"),
    ("خان يونس", "خانيونس - قطاع غزة"),
    ("دير البلح", "دير البلح - قطاع غزة"),
    ("رفح", "رفح - قطاع غزة"),
    ("شمال غزة", "شمال قطاع غزة"),
    ("غزة", "مدينة غزة"),
    ("Gaza", "قطاع غزة"),
    ("Remote", "عن بُعد (Remote)"),
    ("عن بعد", "عن بُعد (Remote)"),
    ("عن بُعد", "عن بُعد (Remote)")
]


def _detect_location(text):
    """Return a detected location or a Gaza default."""
    if not text:
        return "قطاع غزة"
    for keyword, standard_name in LOCATIONS_MAP:
        if keyword.lower() in text.lower():
            return standard_name
    return "قطاع غزة"



def _extract_company(title, description):
    """Return a company name from the title or description."""
    for sep in [" - ", " – ", " — "]:
        if sep in title:
            parts = title.rsplit(sep, 1)
            candidate = parts[1].strip()
            if candidate and len(candidate) < 60:
                return candidate

    patterns = [
        r"تعلن\s+شركة\s+([^\n\.\,\،\(\)]+)",
        r"تعلن\s+([^\n\.\,\،\(\)]+)\s+عن\s+توفر",
        r"نبذة\s+عن\s+المؤسسة\s+([^\n\.\,\،\(\)]+)",
        r"انضم\s+إلى\s+فريق\s+([^\n\.\,\،\(\)]+)",
        r"(?:at|with|join)\s+([A-Z][a-zA-Z0-9\s&]{2,30})\s+(?:is hiring|seeks|team)",
        r"(?:Organization|Company):\s*([^\n\.\,]+)"
    ]
    for pattern in patterns:
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            comp = m.group(1).strip()
            if comp and len(comp) < 50:
                return comp

    return "jobs.ps"


def _load_seed_jobs():
    """Load seed jobs when live data is unavailable."""
    seed_path = os.path.join(os.path.dirname(__file__), '..', '..', 'flask_app',
                             'database', 'initial_data', 'jobs_seed.csv')
    if not os.path.exists(seed_path):
        return 0
    count = 0
    with open(seed_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jid = db.insert_job(
                title=row["title"],
                company=row["company"],
                description=row["description"],
                link=row["link"],
                location=row.get("location", "فلسطين"),
                published_at=row.get("published_at", datetime.now().strftime("%Y-%m-%d"))
            )
            if jid:
                count += 1
    return count


def fetch_jobs_from_rss():
    """Return jobs read from the RSS feeds."""
    target_urls = [JOBS_RSS_URL] if JOBS_RSS_URL else DEFAULT_RSS_URLS
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"
    }

    jobs = []
    seen_links = set()
    seen_job_ids = set()

    for url in target_urls:
        try:
            print(f"[jobs_fetcher] Fetching live jobs from: {url}")
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()

            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                link = html.unescape(getattr(entry, "link", "")).strip()
                if not link or link in seen_links:
                    continue
                seen_links.add(link)

                job_id_match = re.search(r'-(\d+)$', link)
                if job_id_match:
                    job_num = job_id_match.group(1)
                    if job_num in seen_job_ids:
                        continue
                    seen_job_ids.add(job_num)

                raw_title = html.unescape(getattr(entry, "title", "")).strip()
                title_clean = raw_title
                for sep in [" - ", " – ", " — "]:
                    if sep in raw_title:
                        title_clean = raw_title.rsplit(sep, 1)[0].strip()
                        break

                raw_desc = html.unescape(getattr(entry, "summary", "") or getattr(entry, "description", "")).strip()
                clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
                clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

                pub_date = getattr(entry, "published", "") or getattr(entry, "pubDate", "")
                if not pub_date:
                    pub_date = datetime.now().strftime("%Y-%m-%d")

                company = _extract_company(raw_title, clean_desc)
                location = _detect_location(f"{title_clean} {clean_desc} {link}")

                jobs.append({
                    "title": title_clean,
                    "company": company,
                    "description": clean_desc if clean_desc else title_clean,
                    "link": link,
                    "location": location,
                    "published_at": pub_date
                })

        except Exception as e:
            print(f"[jobs_fetcher] RSS fetch error for {url}: {e}")

    print(f"[jobs_fetcher] Total unique live jobs fetched from jobs.ps: {len(jobs)}")
    return jobs


def ensure_jobs_available(limit=20):
    """Fetch current jobs, then use stored or seed data as fallback."""
    rss_jobs = fetch_jobs_from_rss()
    new_count = 0
    for job in rss_jobs:
        jid = db.insert_job(
            title=job["title"],
            company=job["company"],
            description=job["description"],
            link=job["link"],
            location=job.get("location", "فلسطين"),
            published_at=job.get("published_at", "")
        )
        if jid:
            new_count += 1

    if new_count > 0:
        print(f"[jobs_fetcher] Inserted {new_count} new jobs into database.")

    recent_jobs = db.get_recent_jobs(limit=limit)
    if recent_jobs:
        return recent_jobs

    existing = db.get_all_jobs()
    if existing:
        return existing[:limit]

    print("[jobs_fetcher] No jobs available, loading seed fallback...")
    _load_seed_jobs()
    return db.get_recent_jobs(limit=limit)
