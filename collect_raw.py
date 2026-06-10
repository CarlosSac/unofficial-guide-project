"""Stage 1 of ingestion: collect raw text from every source into raw_text/.

Loads each document and saves its raw, uncleaned text to a consistent format
(one .txt per source) plus a manifest.json. Local files are read from disk with
the loaders in ingest.py; URL sources (faculty profiles, RateMyProfessors,
program pages) are fetched and reduced to text. Cleaning and chunking happen
later in ingest.py.

    python collect_raw.py
"""

import json
import time
from pathlib import Path

from ingest import DOCUMENTS_DIR, SKIP_FILES, load_docx, load_pdf, load_text

RAW_DIR = Path(__file__).parent / "raw_text"
MANIFEST = RAW_DIR / "manifest.json"

LOCAL_LOADERS = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".md": load_text,
    ".txt": load_text,
}

# URL sources from the Documents table in planning.md.
# (slug, person, url) -- person is None for non-faculty pages.
URL_SOURCES = [
    # Program / department pages
    ("dept-main", None, "https://www.udc.edu/seas/computer-science/"),
    ("program-bscs", None, "https://www.udc.edu/seas/computer-science/bs-in-computer-science"),
    ("program-bs-cyber", None, "https://www.udc.edu/seas/computer-science/bs-cybersecurity"),
    ("program-mscs", None, "https://www.udc.edu/seas/computer-science/ms-in-computer-science"),
    ("program-ms-cyber", None, "https://www.udc.edu/seas/computer-science/ms-in-cybersecurity"),
    ("program-abm-cs", None, "https://www.udc.edu/seas/computer-science/abm-cs"),
    ("prerequisite-map", None, "https://www.udc.edu/seas/computer-science/prerequisite"),
    # Faculty profiles
    ("faculty-fanid", "Amir Alipour-Fanid", "https://www.udc.edu/directory/profiles/seas/amir-alipour-fanid"),
    ("faculty-amir", "Uzma Amir", "https://www.udc.edu/directory/profiles/seas/uzma-amir"),
    ("faculty-brooks", "Sandra Brooks", "https://www.udc.edu/directory/profiles/seas/sandra-brooks"),
    ("faculty-chen", "Li Chen", "https://www.udc.edu/directory/profiles/seas/li-chen"),
    ("faculty-girma", "Anteneh Girma", "https://www.udc.edu/directory/profiles/seas/anteneh-girma"),
    ("faculty-jeong", "Dong Hyun Jeong", "https://www.udc.edu/directory/profiles/seas/dong-jeong"),
    ("faculty-kacem", "Thabet Kacem", "https://www.udc.edu/directory/profiles/seas/thabet-kacem"),
    ("faculty-kim", "Justin Kim", "https://www.udc.edu/directory/profiles/seas/justin-kim"),
    ("faculty-liang", "Lily Liang", "https://www.udc.edu/directory/profiles/seas/lily-liang"),
    ("faculty-shaban", "Hanney Shaban", "https://www.udc.edu/directory/profiles/seas/hanney-shaban"),
    ("faculty-wellman", "Briana Wellman", "https://www.udc.edu/directory/profiles/seas/briana-wellman"),
    ("faculty-yu", "Byunggu Yu", "https://www.udc.edu/directory/profiles/seas/byunggu-yu"),
    ("faculty-zewdie", "Temechu Zewdie", "https://www.udc.edu/directory/profiles/seas/temechu-zewdie"),
    # RateMyProfessors reviews
    ("rmp-amir", "Uzma Amir", "https://www.ratemyprofessors.com/professor/2187367"),
    ("rmp-chen", "Li Chen", "https://www.ratemyprofessors.com/professor/782290"),
    ("rmp-girma", "Anteneh Girma", "https://www.ratemyprofessors.com/professor/3066315"),
    ("rmp-jeong", "Dong Hyun Jeong", "https://www.ratemyprofessors.com/professor/2190879"),
    ("rmp-kacem", "Thabet Kacem", "https://www.ratemyprofessors.com/professor/2774154"),
    ("rmp-kim", "Junwhan Kim", "https://www.ratemyprofessors.com/professor/1929211"),
    ("rmp-liang", "Lily Liang", "https://www.ratemyprofessors.com/professor/782307"),
    ("rmp-shaban", "Hanney Shaban", "https://www.ratemyprofessors.com/professor/1812839"),
    ("rmp-zewdie", "Temechu Zewdie", "https://www.ratemyprofessors.com/professor/2941232"),
]

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


BLOCK_TAGS = {
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "blockquote", "dt", "dd", "figcaption", "div",
}


def _extract_blocks(soup) -> str:
    """Extract text block-by-block, rejoining inline fragments within each block.

    Some pages wrap word-fragments in separate inline elements; a blanket newline
    separator would split words ("Multi-robot / s / ystems"). Pulling each leaf
    block's text with no separator rejoins them ("Multi-robot systems").
    """
    root = soup.body or soup
    parts = []
    for element in root.find_all(BLOCK_TAGS):
        if element.find(BLOCK_TAGS):
            continue  # container, not a leaf block -- skip to avoid duplicate text
        text = element.get_text(separator="").strip()
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else root.get_text(separator="\n")


def fetch_url(url: str) -> str:
    """Fetch a page and reduce it to visible text (no cleaning yet)."""
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()

    # RateMyProfessors cleans best with one element per line; other sites wrap
    # word-fragments inline, so they need block-aware extraction.
    if "ratemyprofessors.com" in url:
        text = soup.get_text(separator="\n")
    else:
        text = _extract_blocks(soup)
    return text.replace("\xa0", " ")


def main() -> None:
    RAW_DIR.mkdir(exist_ok=True)
    manifest = []

    # --- Local files ---
    print("Local files:")
    for path in sorted(DOCUMENTS_DIR.iterdir()):
        if path.name in SKIP_FILES:
            continue
        loader = LOCAL_LOADERS.get(path.suffix.lower())
        if loader is None:
            continue
        try:
            text = loader(path)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - record any loader failure
            text, status = "", f"error: {type(exc).__name__}: {exc}"

        (RAW_DIR / f"{path.stem}.txt").write_text(text, encoding="utf-8")
        manifest.append({
            "slug": path.stem, "type": "file", "source": path.name,
            "person": None, "chars": len(text), "status": status,
        })
        print(f"  [{status:5.5s}] {len(text):7d} chars  {path.name}")

    # --- URL sources ---
    print("\nURL sources:")
    for slug, person, url in URL_SOURCES:
        try:
            text = fetch_url(url)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - record fetch/parse failures
            text, status = "", f"error: {type(exc).__name__}"

        (RAW_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")
        manifest.append({
            "slug": slug, "type": "url", "source": url,
            "person": person, "chars": len(text), "status": status,
        })
        print(f"  [{status:5.5s}] {len(text):7d} chars  {slug}")
        time.sleep(1)  # be polite to the servers

    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ok = sum(1 for m in manifest if m["status"] == "ok" and m["chars"] > 0)
    print(f"\nSaved raw text for {ok}/{len(manifest)} sources to {RAW_DIR.name}/")
    print(f"Manifest: {MANIFEST.name}")


if __name__ == "__main__":
    main()
