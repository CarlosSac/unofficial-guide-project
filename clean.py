"""Stage 2 of ingestion: clean the raw text in raw_text/ into cleaned/.

Removes boilerplate that is not substantive content: PDF page numbers and
letter-spaced banners (handled by ingest.clean_text), plus the navigation,
footers, and UI chrome that scraping leaves in the URL sources.

Site chrome ("boilerplate that appears on every page") is detected by
frequency: pages are grouped by domain, and any line that recurs across a large
share of that domain's pages is treated as chrome and dropped. A curated pattern
list catches the rest (skip links, directory nav, RMP controls).

    python clean.py
"""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from ingest import clean_text as clean_local_text

RAW_DIR = Path(__file__).parent / "raw_text"
MANIFEST = RAW_DIR / "manifest.json"
CLEANED_DIR = Path(__file__).parent / "cleaned"

# Lines containing any of these (case-insensitive) are dropped as boilerplate.
BOILERPLATE_PATTERNS = [
    "skip to",
    "jump to ratings",
    "view full directory",
    "view faculty profiles",
    "faculty & staff directory",
    "translation selection",
    "top navigation",
    "back to top",
    "all rights reserved",
    "cookie",
    "read more",
    "share this",
    "request info",
    "apply now",
    "rate my professors",
    "rate compare",
    "i'm professor",
    "similar professors",
    "report this rating",
    "©",
]

# A line must recur in at least this share of a domain's pages to count as chrome.
CHROME_THRESHOLD = 0.5

# RateMyProfessors is cleaned with a targeted rule instead of frequency detection:
# its per-review labels (Quality, Difficulty, Grade, ...) legitimately repeat on
# every page, so frequency removal would wrongly delete the ratings we want to keep.
# Cut the footer (everything from its first marker on) and drop only nav buttons.
RMP_FOOTER_MARKERS = {"Load More Ratings", "Help", "Site Guidelines", "Terms & Conditions"}
RMP_NAV_LINES = {"Jump To Ratings", "Rate", "Compare"}
RMP_NAV_PREFIXES = ("I'm Professor",)


def _is_pattern_boilerplate(line: str) -> bool:
    low = line.lower()
    return any(pattern in low for pattern in BOILERPLATE_PATTERNS)


def build_chrome_lines(url_records: list[dict]) -> set[str]:
    """Find lines that repeat across many pages of the same domain (site chrome)."""
    by_domain: dict[str, list[list[str]]] = {}
    for record in url_records:
        domain = urlparse(record["source"]).netloc
        text = (RAW_DIR / f"{record['slug']}.txt").read_text(encoding="utf-8")
        lines = {ln.strip() for ln in text.splitlines() if ln.strip()}
        by_domain.setdefault(domain, []).append(list(lines))

    chrome: set[str] = set()
    for pages in by_domain.values():
        counts: Counter[str] = Counter()
        for page_lines in pages:
            counts.update(page_lines)
        cutoff = max(2, int(len(pages) * CHROME_THRESHOLD))
        for line, count in counts.items():
            if count >= cutoff:
                chrome.add(line)
    return chrome


def clean_rmp_text(text: str) -> str:
    """Cut the RMP footer and nav buttons, keeping all review text, ratings, and metadata."""
    kept = []
    skipping_similar = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in RMP_FOOTER_MARKERS:
            break  # footer starts here; drop it and everything after
        # Drop the "Similar Professors" block (other professors -- off-domain noise),
        # which runs from that heading until the "Student Ratings" section begins.
        if stripped == "Similar Professors":
            skipping_similar = True
            continue
        if skipping_similar:
            if "Student Ratings" in stripped:
                skipping_similar = False
                kept.append(stripped)
            continue
        if not stripped or stripped in RMP_NAV_LINES:
            continue
        if stripped.startswith(RMP_NAV_PREFIXES):
            continue
        kept.append(stripped)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def clean_url_text(text: str, chrome: set[str]) -> str:
    """Drop chrome lines and pattern-matched boilerplate, then normalize whitespace."""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in chrome:
            continue
        if _is_pattern_boilerplate(stripped):
            continue
        kept.append(stripped)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    CLEANED_DIR.mkdir(exist_ok=True)

    # Build site-chrome only from the UDC pages; RMP is handled separately so its
    # repeated review labels are not mistaken for chrome.
    udc_records = [
        m for m in manifest
        if m["type"] == "url" and m["chars"] > 0 and not m["slug"].startswith("rmp-")
    ]
    chrome = build_chrome_lines(udc_records)
    print(f"Detected {len(chrome)} repeated site-chrome lines to remove.\n")

    for record in manifest:
        if record["chars"] == 0:
            continue
        raw = (RAW_DIR / f"{record['slug']}.txt").read_text(encoding="utf-8")
        raw = raw.replace("\xa0", " ").replace("​", "")  # nbsp / zero-width

        if record["slug"].startswith("rmp-"):
            cleaned = clean_rmp_text(raw)
        elif record["type"] == "url":
            cleaned = clean_url_text(raw, chrome)
        else:
            cleaned = clean_local_text(raw)

        (CLEANED_DIR / f"{record['slug']}.txt").write_text(cleaned, encoding="utf-8")
        removed = len(raw) - len(cleaned)
        pct = (removed / len(raw) * 100) if raw else 0
        print(f"  {record['slug']:24.24s} {len(raw):7d} -> {len(cleaned):7d}  (-{pct:4.1f}%)")

    print(f"\nWrote cleaned text to {CLEANED_DIR.name}/")


if __name__ == "__main__":
    main()
