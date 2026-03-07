#!/usr/bin/env python3
"""Scrape Tweakers.net Pricewatch categories and update categories.json + CATEGORIES.md.

Usage (from project root):
    python scripts/update_categories.py

Fetches the categories sitemap, visits each category page to extract the
numeric categoryId, and writes:
  - categories.json  (machine-readable, used by tweakers.py at runtime)
  - CATEGORIES.md     (human-readable reference)
"""

from __future__ import annotations

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

import requests

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BASE = "https://tweakers.net"
_SITEMAP_URL = f"{_BASE}/categories/sitemap.xml"
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

_MAX_WORKERS = 1
_REQUEST_DELAY = 1  # seconds between requests per thread
_MAX_RETRIES = 10
_RETRY_BACKOFF = 5  # seconds, doubled each retry (5, 10, 20, 40, ...)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CATEGORIES_JSON = _PROJECT_ROOT / "categories.json"
_CATEGORIES_MD = _PROJECT_ROOT / "CATEGORIES.md"

# Slugs that exist in the sitemap but 404 (meta pages, not real categories)
_SKIP_SLUGS = {"productdatabase"}


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nl,en;q=0.9",
    })
    # Init consent cookies
    s.get(f"{_BASE}/", timeout=15, allow_redirects=True)
    return s


def fetch_sitemap_slugs(session: requests.Session) -> list[str]:
    """Fetch category slugs from the Tweakers categories sitemap."""
    resp = session.get(_SITEMAP_URL, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    slugs: list[str] = []
    seen: set[str] = set()
    for loc in root.findall("sm:url/sm:loc", _SITEMAP_NS):
        if loc.text is None:
            continue
        # URL looks like https://tweakers.net/{slug}/vergelijken/
        m = re.search(r"tweakers\.net/([^/]+)/vergelijken/?$", loc.text)
        if m and m.group(1) not in seen and m.group(1) not in _SKIP_SLUGS:
            seen.add(m.group(1))
            slugs.append(m.group(1))
    return sorted(slugs)


def scrape_category(session: requests.Session, slug: str) -> dict | None:
    """Visit a category page and extract categoryId + display name."""
    url = f"{_BASE}/{slug}/vergelijken/"
    backoff = _RETRY_BACKOFF

    html = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
            if resp.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    print(f"\n  RETRY {attempt + 1}: 429 for {slug}, waiting {backoff}s...", file=sys.stderr, flush=True)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                print(f"\n  WARN: still 429 after {_MAX_RETRIES} retries: {slug}", file=sys.stderr)
                return None
            resp.raise_for_status()
            html = resp.text
            break
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (404, 410):
                print(f"\n  SKIP: {e.response.status_code} for {slug}", file=sys.stderr)
                return None
            if attempt < _MAX_RETRIES - 1:
                print(f"\n  RETRY {attempt + 1}: {e} for {slug}, waiting {backoff}s...", file=sys.stderr, flush=True)
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"\n  WARN: failed to fetch {slug}: {e}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            if attempt < _MAX_RETRIES - 1:
                print(f"\n  RETRY {attempt + 1}: {e} for {slug}, waiting {backoff}s...", file=sys.stderr, flush=True)
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"\n  WARN: failed to fetch {slug}: {e}", file=sys.stderr)
            return None

    if html is None:
        return None

    # Extract categoryId from tweakersConfig inline JS
    id_m = re.search(r'"categoryId"\s*:\s*(\d+)', html)
    if not id_m:
        print(f"  WARN: no categoryId found for {slug}", file=sys.stderr)
        return None

    # Extract display name from <h1><a>Name</a></h1>
    name_m = re.search(r"<h1>\s*<a[^>]*>([^<]+)</a>\s*</h1>", html)
    name = unescape(name_m.group(1).strip()) if name_m else slug

    return {
        "id": int(id_m.group(1)),
        "name": name,
        "slug": slug,
    }


def scrape_all(
    session: requests.Session, slugs: list[str],
) -> dict[str, dict]:
    """Scrape all categories, returning {slug: {id, name, slug}} dict."""
    categories: dict[str, dict] = {}
    total = len(slugs)

    def _worker(slug: str) -> tuple[str, dict | None]:
        time.sleep(_REQUEST_DELAY)
        return slug, scrape_category(session, slug)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_worker, s): s for s in slugs}
        done = 0
        for future in as_completed(futures):
            done += 1
            slug, result = future.result()
            if result:
                categories[slug] = result
            print(f"\r  [{done}/{total}] scraped {slug:<40}", end="", flush=True)

    print()
    return dict(sorted(categories.items()))


def write_json(categories: dict[str, dict]) -> None:
    """Write categories.json (slug-keyed, without redundant slug field)."""
    # Store compact: {slug: {id, name}}
    compact = {
        slug: {"id": cat["id"], "name": cat["name"]}
        for slug, cat in categories.items()
    }
    _CATEGORIES_JSON.write_text(
        json.dumps(compact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_markdown(categories: dict[str, dict]) -> None:
    """Generate CATEGORIES.md from category data."""
    lines = [
        "# Tweakers Pricewatch Categories",
        "",
        "All categories available for browsing via `client.browse_category()`.",
        "",
        "This file is auto-generated by `python scripts/update_categories.py`.",
        "",
        "| Slug | ID | Name |",
        "|---|---|---|",
    ]
    for slug, cat in categories.items():
        lines.append(f"| `{slug}` | {cat['id']} | {cat['name']} |")

    lines.append("")
    lines.append(f"**{len(categories)} categories total.**")
    lines.append("")

    _CATEGORIES_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("Initializing session...")
    session = _make_session()

    print("Fetching categories sitemap...")
    slugs = fetch_sitemap_slugs(session)
    print(f"  Found {len(slugs)} unique category slugs")

    print(f"Scraping category pages ({_MAX_WORKERS} workers)...")
    categories = scrape_all(session, slugs)
    print(f"  Successfully scraped {len(categories)}/{len(slugs)} categories")

    if not categories:
        print("ERROR: no categories scraped, aborting", file=sys.stderr)
        sys.exit(1)

    print("Writing categories.json...")
    write_json(categories)
    print(f"  {_CATEGORIES_JSON}")

    print("Writing CATEGORIES.md...")
    write_markdown(categories)
    print(f"  {_CATEGORIES_MD}")

    print("Done!")


if __name__ == "__main__":
    main()
