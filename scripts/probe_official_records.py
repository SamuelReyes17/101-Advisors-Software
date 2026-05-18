"""
Probe the Miami-Dade Official Records search page to see what form
fields exist and what URL pattern it uses.

Saves:
    - scripts/captures/or_home.png (screenshot)
    - scripts/captures/or_home.html (full HTML)
    - scripts/captures/or_inputs.txt (all input/select/button info)

Usage:
    python3 -m scripts.probe_official_records
"""
from __future__ import annotations
import json
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise SystemExit("pip3 install playwright --break-system-packages")

CAPTURE = Path(__file__).resolve().parent / "captures"
CAPTURE.mkdir(exist_ok=True)

# Try several URL patterns — the Miami-Dade Clerk migrated domains over time
CANDIDATES = [
    # New domain (most likely current)
    "https://onlineservices.miami-dadeclerk.com/officialrecords/StandardSearch.aspx",
    "https://onlineservices.miami-dadeclerk.com/officialrecords/",
    "https://www2.miami-dadeclerk.com/OfficialRecords/StandardSearch.aspx",
    "https://www.miami-dadeclerk.com/officialrecords",
    "https://www.miami-dadeclerk.com/",
    # Old domain (in case it still redirects)
    "https://www2.miamidadeclerk.gov/officialrecords/StandardSearch.aspx",
    "https://onlineservices.miamidadeclerk.gov/officialrecords/StandardSearch.aspx",
    # Discovery — start at the main clerk page and look for "Official Records" link
    "https://www.miami-dadeclerk.com/clerk/Pages/default.aspx",
    "https://miamidadeclerk.com/",
]


def main() -> int:
    print("=" * 70)
    print("PROBE: Miami-Dade Clerk Official Records search page")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        landed_url = None
        for url in CANDIDATES:
            print(f"\nTrying {url} …")
            try:
                page.goto(url, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(2500)
                title = page.title()
                body_len = len(page.content())
                print(f"  → loaded.  title={title!r}   body_size={body_len:,}")
                if "official records" in (title + page.url).lower() or body_len > 1000:
                    landed_url = page.url
                    break
            except Exception as e:
                print(f"  failed: {e}")

        if not landed_url:
            print("\n❌ Could not reach any Official Records URL")
            browser.close()
            return 1

        print(f"\nFinal URL: {landed_url}")
        print(f"Page title: {page.title()!r}")

        # Save artifacts
        page.screenshot(path=str(CAPTURE / "or_home.png"), full_page=True)
        (CAPTURE / "or_home.html").write_text(page.content(), encoding="utf-8")

        # Enumerate all form inputs
        inputs = page.evaluate(
            """
            () => {
                const out = [];
                document.querySelectorAll('input, select, textarea, button').forEach(el => {
                    const labelEl = el.labels && el.labels.length ? el.labels[0] : null;
                    out.push({
                        tag: el.tagName,
                        type: el.type || '',
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        value: (el.value || '').slice(0, 60),
                        ariaLabel: el.getAttribute('aria-label') || '',
                        label: labelEl ? labelEl.innerText.trim().slice(0, 60) : '',
                        visible: el.offsetParent !== null,
                        options: el.tagName === 'SELECT'
                            ? Array.from(el.options).slice(0, 30).map(o => ({
                                value: o.value, text: o.text.slice(0, 40)
                            }))
                            : null,
                    });
                });
                return out;
            }
            """
        )

        # Save full input dump
        with (CAPTURE / "or_inputs.txt").open("w", encoding="utf-8") as f:
            f.write(f"URL: {landed_url}\nTitle: {page.title()}\n\n")
            for inp in inputs:
                f.write(f"{inp['tag']:8s} type={inp['type']:<12s} "
                        f"visible={inp['visible']!s:<5} "
                        f"id={inp['id'][:35]:<35s} "
                        f"name={inp['name'][:25]:<25s} "
                        f"label={inp['label'][:30]:<30s} "
                        f"ph={inp['placeholder'][:25]}\n")
                if inp.get("options"):
                    for opt in inp["options"]:
                        f.write(f"         option: value={opt['value'][:20]:<20s} text={opt['text']}\n")

        # Print summary to stdout
        print(f"\n{'='*70}\nFORM FIELDS DISCOVERED  ({len(inputs)} total)\n{'='*70}")
        visible = [i for i in inputs if i["visible"]]
        print(f"\nVisible: {len(visible)}")
        for inp in visible[:40]:
            ident = inp["id"] or inp["name"] or "(none)"
            extra = ""
            if inp["tag"] == "SELECT" and inp.get("options"):
                opt_texts = [o["text"] for o in inp["options"][:5]]
                extra = f"  options: {opt_texts}"
            print(f"  {inp['tag']:8s} {inp['type']:12s} "
                  f"{ident[:30]:<30s} {inp['label'][:20]:<20s}{extra}")

        # Look for keywords
        print(f"\n{'='*70}\nLOOKING FOR KEYWORDS in inputs:\n{'='*70}")
        for kw in ("document", "doc type", "doctype", "from", "to", "date",
                   "lis pendens", "search", "party"):
            hits = [i for i in inputs
                    if (kw.lower() in (i["id"] + i["name"] + i["placeholder"]
                                        + i["label"] + i["ariaLabel"]).lower())]
            if hits:
                print(f"\n  '{kw}':")
                for h in hits[:5]:
                    ident = h["id"] or h["name"] or "(none)"
                    print(f"    {h['tag']} {ident}  visible={h['visible']}")

        print(f"\nArtifacts saved:")
        print(f"  {CAPTURE/'or_home.png'}")
        print(f"  {CAPTURE/'or_home.html'}")
        print(f"  {CAPTURE/'or_inputs.txt'}")

        print(f"\nBrowser will close in 5 seconds — feel free to inspect it now.")
        page.wait_for_timeout(5000)
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
