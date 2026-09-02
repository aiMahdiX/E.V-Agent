"""Browser automation tool (Phase 3 — Playwright + system Chrome).

Uses Playwright to drive the system-installed Google Chrome
(``/usr/bin/google-chrome-stable``) as a fallback channel. Provides a
small stable surface: open a URL, click a selector, type text, read the
page text, and capture a screenshot.

Imports are lazy so E.V. keeps working even if playwright is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from tools.base import Tool

# Path to the system Chrome; used as a fallback when Playwright's own
# Chromium build is not downloaded.
CHROME_PATHS = ("/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser")

_browser = None  # lazily launched Playwright browser

# Global headless toggle. Defaults to headless (safe for servers); set
# EV_HEADLESS=0 to open visible windows on a desktop session.
HEADLESS = os.environ.get("EV_HEADLESS", "1").lower() not in ("0", "false", "no")


def _launch():
    """Launch Chrome (headless unless EV_HEADLESS=0). Returns page."""
    global _browser
    from playwright.sync_api import sync_playwright

    kwargs = {"headless": HEADLESS}
    for path in CHROME_PATHS:
        if __import__("os").path.exists(path):
            kwargs["executable_path"] = path
            break
    else:
        kwargs["channel"] = "chrome"  # rely on Playwright's channel fallback

    pw = sync_playwright().start()
    _browser = pw.chromium.launch(**kwargs)
    context = _browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"),
        locale="en-US")
    page = context.new_page()
    return page


def _ensure_page():
    if _browser is None:
        page = _launch()
    else:
        # reuse first page if it exists, else create one
        page = _browser.contexts[0].pages[0] if _browser.contexts and \
            _browser.contexts[0].pages else _browser.new_context(
                viewport={"width": 1280, "height": 800}).new_page()
    return page


def _cleanup():
    """Close the browser to free resources (called on shutdown)."""
    global _browser
    if _browser is not None:
        try:
            _browser.close()
        finally:
            _browser = None


def open_page(url: str, workspace=None) -> dict:
    """Open a URL in the headless browser and return the page title/URL."""
    try:
        page = _ensure_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        return {"ok": True, "title": page.title(), "url": page.url}
    except Exception as e:  # noqa: BLE001
        return {"error": f"open_page: {type(e).__name__}: {e}"}


def click_selector(selector: str, workspace=None) -> dict:
    """Click an element matched by a CSS selector."""
    try:
        page = _ensure_page()
        page.click(selector, timeout=10000)
        return {"ok": True, "url": page.url}
    except Exception as e:  # noqa: BLE001
        return {"error": f"click_selector: {type(e).__name__}: {e}"}


def type_text(text: str, selector: str = "//body", workspace=None) -> dict:
    """Type ``text`` into the given selector (default: body)."""
    try:
        page = _ensure_page()
        if selector and selector != "//body":
            page.fill(selector, text, timeout=10000)
        else:
            page.keyboard.type(text)
        return {"ok": True, "url": page.url}
    except Exception as e:  # noqa: BLE001
        return {"error": f"type_text: {type(e).__name__}: {e}"}


def page_text(url: str | None = None, workspace=None) -> dict:
    """Return the *visible* text of the current (or given) page.

    Uses ``document.body.innerText`` so <script>/<style> blobs are
    excluded. Detects bot-challenge pages and says so instead of
    returning their JS garbage.
    """
    try:
        page = _ensure_page()
        if url:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(800)   # let late JS render
        # innerText = rendered text only (no script/style contents)
        text = page.evaluate("() => document.body.innerText") or ""
        low = text.lower()
        bot_markers = ("bgchallenge", "guided_help", "recaptcha",
                       "captcha-delivery", "enable javascript",
                       "are you a robot", "unusual traffic")
        if len(text.strip()) < 40 or any(m in low for m in bot_markers):
            return {"ok": False,
                    "note": ("page is a bot-challenge/JS shell — "
                             "use browser_launch to open it visibly "
                             "for the user instead"),
                    "text": text[:400]}
        return {"ok": True, "text": text[:8000]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"page_text: {type(e).__name__}: {e}"}


def screenshot(path: str = "data/screenshots/browser.png", workspace=None) -> dict:
    """Capture a screenshot of the current browser page to ``path``."""
    try:
        page = _ensure_page()
        import os
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=path)
        return {"ok": True, "path": path,
                "size": os.path.getsize(path) if os.path.exists(path) else 0}
    except Exception as e:  # noqa: BLE001
        return {"error": f"screenshot: {type(e).__name__}: {e}"}


def browser_scroll(amount: str = "600", workspace=None) -> dict:
    """Scroll the current page.

    ``amount`` is pixels (e.g. "600", "-400" to scroll up) or
    "top" / "bottom". Returns the new scroll position.
    """
    try:
        page = _ensure_page()
        a = str(amount).strip().lower()
        if a == "top":
            page.evaluate("() => window.scrollTo(0, 0)")
        elif a == "bottom":
            page.evaluate(
                "() => window.scrollTo(0, document.body.scrollHeight)")
        else:
            px = int(float(a))
            page.evaluate(f"() => window.scrollBy(0, {px})")
        pos = page.evaluate(
            "() => ({scroll_y: Math.round(window.scrollY),"
            " page_height: document.body.scrollHeight})")
        return {"ok": True, **pos}
    except Exception as e:  # noqa: BLE001
        return {"error": f"browser_scroll: {type(e).__name__}: {e}"}


def browser_links(limit: int = 15, workspace=None) -> dict:
    """List visible links (text + href) on the current page.

    Gives the agent a navigation map so it can 'browse around' by
    picking URLs to open next.
    """
    try:
        page = _ensure_page()
        links = page.evaluate(
            """(limit) => Array.from(document.querySelectorAll('a[href]'))
               .filter(a => a.innerText && a.innerText.trim().length > 1)
               .slice(0, limit)
               .map(a => ({text: a.innerText.trim().slice(0, 80),
                           href: a.href}))""",
            max(1, min(int(limit), 50)))
        return {"ok": True, "count": len(links), "links": links}
    except Exception as e:  # noqa: BLE001
        return {"error": f"browser_links: {type(e).__name__}: {e}"}


def browser_launch(url: str, workspace=None) -> dict:
    """Open ``url`` in a visible system browser window (Google Chrome).

    Uses the OS directly (``google-chrome``/``firefox``), so it works even
    when Playwright isn't available. Only succeeds on a desktop session
    with a display; otherwise returns a clear error.
    """
    try:
        exe = (shutil.which("google-chrome-stable") or shutil.which("google-chrome")
               or shutil.which("firefox"))
        if not exe:
            return {"error": "browser_launch: no chrome/firefox binary found"}
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return {"error": "browser_launch: no display session available"}
        subprocess.Popen([exe, "--new-window", url],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "url": url, "browser": os.path.basename(exe)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"browser_launch: {type(e).__name__}: {e}"}


BROWSER_TOOLS = [
    Tool(name="browser_open",
         description=("Load a URL in the internal headless browser for "
                      "scraping/automation. Shows NO window to the user. "
                      "For 'open <site> for me' requests use browser_launch."),
         parameters={"type": "object",
                     "properties": {"url": {"type": "string", "description": "URL to open"}}},
         required=["url"],
         fn=open_page,
         level=1),
    Tool(name="browser_launch",
         description=("Open a URL in a REAL visible browser window on the "
                      "user's desktop. Use this whenever the user says "
                      "'open/show <site>' — e.g. opening YouTube."),
         parameters={"type": "object",
                     "properties": {"url": {"type": "string"}}},
         required=["url"],
         fn=browser_launch,
         level=1),
    Tool(name="browser_click",
         description="Click an element in the browser by CSS selector.",
         parameters={"type": "object",
                     "properties": {"selector": {"type": "string"}}},
         required=["selector"],
         fn=click_selector,
         level=1),
    Tool(name="browser_type",
         description="Type text into the page (optionally into a selector).",
         parameters={"type": "object",
                     "properties": {"text": {"type": "string"},
                                    "selector": {"type": "string"}}},
         required=["text"],
         fn=type_text,
         level=1),
    Tool(name="browser_read",
         description=("Extract the visible text of a page (after "
                      "browser_open). Returns clean rendered text; flags "
                      "bot-challenge pages."),
         parameters={"type": "object",
                     "properties": {"url": {"type": "string"}}},
         required=[],
         fn=page_text,
         level=1),
    Tool(name="browser_scroll",
         description=("Scroll the current browser page. amount = pixels "
                      "(e.g. '600', '-400') or 'top'/'bottom'."),
         parameters={"type": "object",
                     "properties": {"amount": {"type": "string"}}},
         required=[],
         fn=browser_scroll,
         level=1),
    Tool(name="browser_links",
         description=("List visible links (text + href) on the current "
                      "page — use to navigate/browse further."),
         parameters={"type": "object",
                     "properties": {"limit": {"type": "integer"}}},
         required=[],
         fn=browser_links,
         level=1),
    Tool(name="browser_screenshot",
         description="Capture a screenshot of the current browser page.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"}}},
         required=[],
         fn=screenshot,
         level=1),
]
