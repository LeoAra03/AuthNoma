# arena/diagnostico.py
from playwright.sync_api import sync_playwright
import json
with sync_playwright() as pw:
    nav = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    pg = [p for p in nav.contexts[0].pages if "arena" in p.url][-1]
    print("URL:", pg.url)
    for sel in ["div[contenteditable='true']", "textarea", "button[type='submit']",
                "button[aria-label]", "[data-testid]"]:
        loc = pg.locator(sel)
        print(f"\n{sel} -> {loc.count()} nodos")
        for i in range(min(loc.count(), 6)):
            try:
                print("   ", repr(loc.nth(i).inner_text()[:60]),
                      loc.nth(i).get_attribute("aria-label"),
                      loc.nth(i).get_attribute("data-testid"))
            except Exception: pass
    print("\nBody (primeros 400):", pg.locator("body").inner_text()[:400])