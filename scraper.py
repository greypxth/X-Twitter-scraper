#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║              X.com Scraper — by Greypath                  ║
║  Profiles · Tweets · Threads · Search · Hashtags          ║
╚═══════════════════════════════════════════════════════════╝

SETUP (run once):
    pip install playwright rich questionary
    playwright install chromium

USAGE:
    python x_scraper.py
"""

import json
import re
import sys
import time
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, quote

# ── dependency check ────────────────────────────────────────────────────────
MISSING = []
for pkg, imp in [("playwright", "playwright.sync_api"), ("rich", "rich"), ("questionary", "questionary")]:
    try:
        __import__(imp)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"\n❌  Missing packages: {', '.join(MISSING)}")
    print(f"    Run: pip install {' '.join(MISSING)}")
    if "playwright" in MISSING:
        print("    Then: playwright install chromium")
    sys.exit(1)

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
import questionary

console = Console()

# ── helpers ─────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def parse_count(text: str) -> int:
    """Convert '1.2K', '4.5M' → int"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1_000)
        if text.endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        if text.endswith("B"):
            return int(float(text[:-1]) * 1_000_000_000)
        return int(text)
    except ValueError:
        return 0

def detect_page_type(url: str) -> str:
    """Classify URL into: profile | tweet | search | hashtag | list | unknown"""
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if "search" in parsed.query or "/search" in parsed.path:
        return "search"
    if path.startswith("hashtag/") or path.startswith("explore/search"):
        return "hashtag"
    if "/status/" in parsed.path:
        return "tweet"
    if "/lists/" in parsed.path:
        return "list"
    if path and "/" not in path:
        return "profile"
    if path.startswith("i/"):
        return "explore"
    return "unknown"

def normalize_url(url: str) -> str:
    """Add https:// and convert twitter.com → x.com"""
    if not url.startswith("http"):
        url = "https://" + url
    url = url.replace("twitter.com", "x.com")
    return url

# ── core scraper ─────────────────────────────────────────────────────────────

class XScraper:
    def __init__(self, headless: bool = True, slow_mo: int = 0, cookie_file: Optional[str] = None):
        self.headless = headless
        self.slow_mo = slow_mo
        self.cookie_file = cookie_file
        self.results = []
        self.page_type = "unknown"

    def _load_cookies(self, context):
        """Load cookies from a saved JSON file (from browser extension export)"""
        if not self.cookie_file or not Path(self.cookie_file).exists():
            return
        try:
            with open(self.cookie_file, "r") as f:
                cookies = json.load(f)
            # Normalize cookie format
            cleaned = []
            for c in cookies:
                cleaned.append({
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".x.com"),
                    "path": c.get("path", "/"),
                })
            context.add_cookies(cleaned)
            console.print("[green]✓ Cookies loaded[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not load cookies: {e}[/yellow]")

    def _setup_stealth(self, page):
        """Minimal anti-detection patches"""
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)

    def _wait_for_tweets(self, page, timeout: int = 15000):
        """Wait until tweet articles appear in the DOM"""
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=timeout)
            return True
        except PlaywrightTimeout:
            return False

    def _extract_tweet(self, article) -> Optional[dict]:
        """Parse a single tweet article element into a dict"""
        try:
            tweet = {}

            # ── author ──────────────────────────────────────────────────────
            try:
                tweet["author_name"] = clean_text(
                    article.query_selector('[data-testid="User-Name"] span:first-child').inner_text()
                )
            except:
                tweet["author_name"] = "unknown"

            try:
                handle_el = article.query_selector('[data-testid="User-Name"] a[href*="/"]')
                href = handle_el.get_attribute("href") if handle_el else ""
                tweet["author_handle"] = href.strip("/").split("/")[-1] if href else "unknown"
            except:
                tweet["author_handle"] = "unknown"

            # ── timestamp ───────────────────────────────────────────────────
            try:
                time_el = article.query_selector("time")
                tweet["timestamp"] = time_el.get_attribute("datetime") if time_el else None
                tweet["time_display"] = clean_text(time_el.inner_text()) if time_el else None
            except:
                tweet["timestamp"] = None
                tweet["time_display"] = None

            # ── body text ────────────────────────────────────────────────────
            try:
                text_el = article.query_selector('[data-testid="tweetText"]')
                tweet["text"] = clean_text(text_el.inner_text()) if text_el else ""
            except:
                tweet["text"] = ""

            # ── tweet URL ────────────────────────────────────────────────────
            try:
                link_el = article.query_selector("a[href*='/status/']")
                href = link_el.get_attribute("href") if link_el else ""
                tweet["url"] = f"https://x.com{href}" if href.startswith("/") else href
            except:
                tweet["url"] = ""

            # ── engagement stats ─────────────────────────────────────────────
            for stat, testid in [("replies", "reply"), ("reposts", "retweet"), ("likes", "like"), ("views", "views")]:
                try:
                    el = article.query_selector(f'[data-testid="{testid}"]')
                    if el:
                        raw = clean_text(el.get_attribute("aria-label") or el.inner_text())
                        nums = re.findall(r"[\d,.]+[KMB]?", raw)
                        tweet[stat] = parse_count(nums[0]) if nums else 0
                    else:
                        tweet[stat] = 0
                except:
                    tweet[stat] = 0

            # ── media ────────────────────────────────────────────────────────
            images, videos = [], []
            try:
                for img in article.query_selector_all('img[src*="pbs.twimg.com/media"]'):
                    src = img.get_attribute("src")
                    if src:
                        images.append(re.sub(r"\?.*", "?format=jpg&name=large", src))
            except:
                pass

            try:
                for video in article.query_selector_all("video"):
                    src = video.get_attribute("src")
                    if src:
                        videos.append(src)
            except:
                pass

            tweet["images"] = images
            tweet["videos"] = videos
            tweet["has_media"] = bool(images or videos)

            # ── badges / labels ───────────────────────────────────────────────
            try:
                badge = article.query_selector('[data-testid="icon-verified"]')
                tweet["verified"] = badge is not None
            except:
                tweet["verified"] = False

            # ── retweet / quote detection ─────────────────────────────────────
            try:
                social = article.query_selector('[data-testid="socialContext"]')
                tweet["is_repost"] = social is not None and "Repost" in (social.inner_text() or "")
            except:
                tweet["is_repost"] = False

            return tweet

        except Exception as e:
            return None

    def _scroll_and_collect(self, page, max_tweets: int, stop_on_dupe: bool = True) -> list:
        """Scroll the page and extract tweets, respecting dedup + limits"""
        collected = []
        seen_urls = set()
        prev_height = 0
        stall_count = 0

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            task = progress.add_task(f"Collecting tweets (0 / {max_tweets})…", total=max_tweets)

            while len(collected) < max_tweets:
                articles = page.query_selector_all('article[data-testid="tweet"]')

                for article in articles:
                    if len(collected) >= max_tweets:
                        break
                    tweet = self._extract_tweet(article)
                    if not tweet:
                        continue
                    key = tweet.get("url") or tweet.get("text", "")[:80]
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    collected.append(tweet)
                    progress.update(task, completed=len(collected),
                                    description=f"Collecting tweets ({len(collected)} / {max_tweets})…")

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2.5)

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == prev_height:
                    stall_count += 1
                    if stall_count >= 3:
                        break
                else:
                    stall_count = 0
                    prev_height = new_height

        return collected

    def scrape_profile(self, page, url: str, options: dict) -> dict:
        """Scrape a user profile page"""
        page.goto(url, wait_until="domcontentloaded")

        result = {"type": "profile", "url": url, "scraped_at": datetime.utcnow().isoformat(), "profile": {}, "tweets": []}

        try:
            page.wait_for_selector('[data-testid="primaryColumn"]', timeout=15000)
        except PlaywrightTimeout:
            console.print("[yellow]⚠ Page load timeout — partial data may be extracted[/yellow]")

        # ── profile metadata ──────────────────────────────────────────────────
        prof = {}
        try:
            prof["name"] = clean_text(page.query_selector('[data-testid="UserName"] span').inner_text())
        except: prof["name"] = ""
        try:
            prof["handle"] = "@" + url.rstrip("/").split("/")[-1]
        except: prof["handle"] = ""
        try:
            bio_el = page.query_selector('[data-testid="UserDescription"]')
            prof["bio"] = clean_text(bio_el.inner_text()) if bio_el else ""
        except: prof["bio"] = ""
        try:
            loc_el = page.query_selector('[data-testid="UserLocation"]')
            prof["location"] = clean_text(loc_el.inner_text()) if loc_el else ""
        except: prof["location"] = ""
        try:
            url_el = page.query_selector('[data-testid="UserUrl"]')
            prof["website"] = clean_text(url_el.inner_text()) if url_el else ""
        except: prof["website"] = ""
        try:
            join_el = page.query_selector('[data-testid="UserJoinDate"]')
            prof["joined"] = clean_text(join_el.inner_text()) if join_el else ""
        except: prof["joined"] = ""

        # followers / following
        for stat in ["followers", "following"]:
            try:
                el = page.query_selector(f'a[href*="{stat}"] span span')
                prof[stat] = parse_count(clean_text(el.inner_text())) if el else 0
            except: prof[stat] = 0

        result["profile"] = prof

        # ── tweets ────────────────────────────────────────────────────────────
        if self._wait_for_tweets(page):
            result["tweets"] = self._scroll_and_collect(page, options["max_tweets"])

        return result

    def scrape_tweet_thread(self, page, url: str, options: dict) -> dict:
        """Scrape a single tweet + its reply thread"""
        page.goto(url, wait_until="domcontentloaded")
        result = {"type": "thread", "url": url, "scraped_at": datetime.utcnow().isoformat(), "tweets": []}

        if self._wait_for_tweets(page):
            result["tweets"] = self._scroll_and_collect(page, options["max_tweets"])

        # Mark first tweet as the root
        if result["tweets"]:
            result["tweets"][0]["is_root"] = True

        return result

    def scrape_search(self, page, url: str, options: dict) -> dict:
        """Scrape search results (Top / Latest / People / Media)"""
        page.goto(url, wait_until="domcontentloaded")
        result = {"type": "search", "url": url, "scraped_at": datetime.utcnow().isoformat(), "tweets": []}

        # Apply tab filter
        tab = options.get("search_tab", "Top")
        tab_map = {"Top": "Top", "Latest": "Latest", "People": "People", "Media": "Media", "Lists": "Lists"}
        try:
            tab_el = page.query_selector(f'[role="tab"]:has-text("{tab_map.get(tab, tab)}")')
            if tab_el:
                tab_el.click()
                time.sleep(2)
        except:
            pass

        if self._wait_for_tweets(page):
            result["tweets"] = self._scroll_and_collect(page, options["max_tweets"])

        return result

    def scrape(self, url: str, options: dict) -> dict:
        url = normalize_url(url)
        self.page_type = detect_page_type(url)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            self._load_cookies(context)
            page = context.new_page()
            self._setup_stealth(page)

            try:
                console.print(f"\n[cyan]Page type detected:[/cyan] [bold]{self.page_type}[/bold]")
                console.print(f"[dim]URL: {url}[/dim]\n")

                if self.page_type == "profile":
                    data = self.scrape_profile(page, url, options)
                elif self.page_type == "tweet":
                    data = self.scrape_tweet_thread(page, url, options)
                elif self.page_type in ("search", "hashtag", "explore"):
                    data = self.scrape_search(page, url, options)
                else:
                    # Generic fallback
                    page.goto(url, wait_until="domcontentloaded")
                    self._wait_for_tweets(page)
                    tweets = self._scroll_and_collect(page, options["max_tweets"])
                    data = {"type": "generic", "url": url,
                            "scraped_at": datetime.utcnow().isoformat(), "tweets": tweets}

                # ── apply filters ─────────────────────────────────────────────
                data = self._apply_filters(data, options)

            finally:
                browser.close()

        self.results = data
        return data

    def _apply_filters(self, data: dict, options: dict) -> dict:
        """Post-scrape filtering: min_likes, keyword, media_only, exclude_reposts"""
        tweets = data.get("tweets", [])
        original = len(tweets)

        if options.get("min_likes", 0) > 0:
            tweets = [t for t in tweets if t.get("likes", 0) >= options["min_likes"]]

        if options.get("keyword"):
            kw = options["keyword"].lower()
            tweets = [t for t in tweets if kw in t.get("text", "").lower()]

        if options.get("media_only"):
            tweets = [t for t in tweets if t.get("has_media")]

        if options.get("exclude_reposts"):
            tweets = [t for t in tweets if not t.get("is_repost")]

        filtered = original - len(tweets)
        if filtered:
            console.print(f"[dim]Filtered out {filtered} tweets based on your criteria[/dim]")

        data["tweets"] = tweets
        return data

# ── display layer ─────────────────────────────────────────────────────────────

def display_profile(data: dict):
    prof = data.get("profile", {})
    if not prof:
        return

    lines = [
        f"[bold cyan]{prof.get('name', 'Unknown')}[/bold cyan]  [dim]{prof.get('handle', '')}[/dim]",
    ]
    if prof.get("verified"):
        lines[0] += "  ✓"
    if prof.get("bio"):
        lines.append(f"\n{prof['bio']}")
    if prof.get("location"):
        lines.append(f"\n📍 {prof['location']}")
    if prof.get("website"):
        lines.append(f"🔗 {prof['website']}")
    if prof.get("joined"):
        lines.append(f"📅 {prof['joined']}")

    followers = prof.get("followers", 0)
    following = prof.get("following", 0)
    lines.append(f"\n[bold]{followers:,}[/bold] followers  ·  [bold]{following:,}[/bold] following")

    console.print(Panel("\n".join(lines), title="Profile", border_style="cyan"))

def display_tweets(tweets: list, page_type: str = ""):
    if not tweets:
        console.print("[yellow]No tweets to display.[/yellow]")
        return

    console.print(f"\n[bold green]═══ {len(tweets)} tweets extracted ═══[/bold green]\n")

    for i, t in enumerate(tweets, 1):
        # header
        author = f"[bold]{t.get('author_name', 'unknown')}[/bold]"
        handle = f"[dim]@{t.get('author_handle', 'unknown')}[/dim]"
        ts     = f"[dim]{t.get('time_display') or t.get('timestamp', '')[:10]}[/dim]"
        verified = " ✓" if t.get("verified") else ""
        repost = " [yellow][Repost][/yellow]" if t.get("is_repost") else ""
        root   = " [cyan][Root][/cyan]" if t.get("is_root") else ""

        console.print(f"[{i:>3}] {author}{verified}  {handle}  {ts}{repost}{root}")

        # text body
        text = t.get("text", "").strip()
        if text:
            # Wrap long lines for readability
            words = text.split()
            lines, line = [], []
            for w in words:
                line.append(w)
                if len(" ".join(line)) > 90:
                    lines.append(" ".join(line))
                    line = []
            if line:
                lines.append(" ".join(line))
            for l in lines:
                console.print(f"     {l}")

        # stats row
        stats = []
        for emoji, key in [("💬", "replies"), ("🔁", "reposts"), ("❤️ ", "likes"), ("👁 ", "views")]:
            val = t.get(key, 0)
            if val:
                stats.append(f"{emoji} {val:,}")
        if stats:
            console.print(f"     [dim]{' · '.join(stats)}[/dim]")

        # media
        if t.get("images"):
            console.print(f"     [magenta]📷 {len(t['images'])} image(s)[/magenta]: {t['images'][0]}")
        if t.get("videos"):
            console.print(f"     [magenta]🎥 video[/magenta]")

        # link
        if t.get("url"):
            console.print(f"     [blue underline]{t['url']}[/blue underline]")

        console.print()

def display_summary_table(data: dict):
    tweets = data.get("tweets", [])
    if not tweets:
        return

    total_likes   = sum(t.get("likes",   0) for t in tweets)
    total_reposts = sum(t.get("reposts", 0) for t in tweets)
    total_replies = sum(t.get("replies", 0) for t in tweets)
    total_views   = sum(t.get("views",   0) for t in tweets)
    with_media    = sum(1 for t in tweets if t.get("has_media"))

    top = sorted(tweets, key=lambda t: t.get("likes", 0), reverse=True)

    table = Table(title="📊 Scrape Summary", box=box.ROUNDED, border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Tweets collected",    str(len(tweets)))
    table.add_row("Total likes",         f"{total_likes:,}")
    table.add_row("Total reposts",       f"{total_reposts:,}")
    table.add_row("Total replies",       f"{total_replies:,}")
    table.add_row("Total views",         f"{total_views:,}")
    table.add_row("Tweets with media",   str(with_media))
    if top:
        table.add_row("Top tweet likes",
                      f"{top[0].get('likes',0):,} — {top[0].get('text','')[:40]}…")

    console.print(table)

# ── export layer ──────────────────────────────────────────────────────────────

def save_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓ JSON saved → {path}[/green]")

def save_csv(data: dict, path: str):
    tweets = data.get("tweets", [])
    if not tweets:
        console.print("[yellow]No tweets to save.[/yellow]")
        return
    fields = ["author_name", "author_handle", "timestamp", "text",
              "likes", "reposts", "replies", "views", "url", "has_media", "verified", "is_repost"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(tweets)
    console.print(f"[green]✓ CSV saved → {path}[/green]")

def save_txt(data: dict, path: str):
    tweets = data.get("tweets", [])
    lines = [
        f"X.com Scrape — {data.get('url', '')}",
        f"Date: {data.get('scraped_at', '')}",
        f"Type: {data.get('type', '')}",
        f"Tweets: {len(tweets)}",
        "=" * 60,
    ]
    prof = data.get("profile", {})
    if prof:
        lines += [
            f"Profile: {prof.get('name','')} ({prof.get('handle','')})",
            f"Bio: {prof.get('bio','')}",
            f"Followers: {prof.get('followers',0):,}",
            "=" * 60,
        ]
    for i, t in enumerate(tweets, 1):
        lines.append(f"\n[{i}] @{t.get('author_handle','')} — {t.get('time_display','')}")
        lines.append(t.get("text", ""))
        lines.append(f"❤️  {t.get('likes',0):,}  🔁 {t.get('reposts',0):,}  💬 {t.get('replies',0):,}  👁 {t.get('views',0):,}")
        if t.get("url"):
            lines.append(t["url"])
        lines.append("-" * 40)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    console.print(f"[green]✓ TXT saved → {path}[/green]")

# ── interactive menu ───────────────────────────────────────────────────────────

def main():
    console.print(Panel.fit(
        "[bold cyan]X.com Scraper[/bold cyan]\n"
        "[dim]Profiles · Threads · Search · Hashtags[/dim]",
        border_style="cyan"
    ))

    # ── 1. URL ──────────────────────────────────────────────────────────────
    url = questionary.text(
        "Enter X.com URL:",
        instruction="(profile, tweet, search, hashtag, or list)"
    ).ask()

    if not url:
        sys.exit()

    url = normalize_url(url)
    page_type = detect_page_type(url)
    console.print(f"[dim]→ Detected as:[/dim] [bold]{page_type}[/bold]")

    # ── 2. How many tweets ────────────────────────────────────────────────────
    max_tweets = int(questionary.select(
        "Max tweets to collect:",
        choices=["20", "50", "100", "200", "500"]
    ).ask())

    # ── 3. Filters ────────────────────────────────────────────────────────────
    filters = questionary.checkbox(
        "Optional filters:",
        choices=[
            questionary.Choice("Media only (images/videos)", "media_only"),
            questionary.Choice("Exclude reposts",            "exclude_reposts"),
            questionary.Choice("Keyword filter",             "keyword"),
            questionary.Choice("Minimum likes threshold",    "min_likes"),
        ]
    ).ask() or []

    options = {"max_tweets": max_tweets, "media_only": False, "exclude_reposts": False,
               "keyword": "", "min_likes": 0}

    if "media_only" in filters:
        options["media_only"] = True

    if "exclude_reposts" in filters:
        options["exclude_reposts"] = True

    if "keyword" in filters:
        options["keyword"] = questionary.text("Filter keyword:").ask() or ""

    if "min_likes" in filters:
        options["min_likes"] = int(questionary.text("Minimum likes:", default="10").ask() or 0)

    if page_type == "search":
        options["search_tab"] = questionary.select(
            "Which search tab?",
            choices=["Top", "Latest", "People", "Media"]
        ).ask()

    # ── 4. Display options ────────────────────────────────────────────────────
    display_mode = questionary.select(
        "Display mode:",
        choices=[
            "Full (all tweets + summary)",
            "Summary only (table)",
            "No display (save only)"
        ]
    ).ask()

    # ── 5. Export ─────────────────────────────────────────────────────────────
    export_formats = questionary.checkbox(
        "Export formats:",
        choices=["JSON", "CSV", "TXT"]
    ).ask() or []

    export_name = None
    if export_formats:
        slug = re.sub(r"[^\w]", "_", url.split("x.com/")[-1].strip("/"))[:40]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"x_{slug}_{ts}"

    # ── 6. Advanced options ───────────────────────────────────────────────────
    advanced = questionary.checkbox(
        "Advanced options:",
        choices=[
            questionary.Choice("Show browser (non-headless)", "show_browser"),
            questionary.Choice("Load cookies from file",       "cookies"),
        ]
    ).ask() or []

    headless = "show_browser" not in advanced
    cookie_file = None
    if "cookies" in advanced:
        cookie_file = questionary.text(
            "Cookie file path:",
            instruction="JSON export from a browser extension like 'EditThisCookie'"
        ).ask()

    # ── 7. Scrape ─────────────────────────────────────────────────────────────
    console.print("\n[bold cyan]Starting scrape…[/bold cyan]")
    scraper = XScraper(headless=headless, cookie_file=cookie_file)

    try:
        data = scraper.scrape(url, options)
    except Exception as e:
        console.print(f"\n[bold red]❌ Scrape failed:[/bold red] {e}")
        console.print("[dim]Tips: Try non-headless mode, or load auth cookies for better access.[/dim]")
        sys.exit(1)

    tweets = data.get("tweets", [])
    console.print(f"\n[bold green]✓ Done — {len(tweets)} tweets collected[/bold green]")

    # ── 8. Display ────────────────────────────────────────────────────────────
    if display_mode != "No display (save only)":
        if page_type == "profile":
            display_profile(data)

        if display_mode == "Full (all tweets + summary)":
            display_tweets(tweets, page_type)

        display_summary_table(data)

    # ── 9. Export ─────────────────────────────────────────────────────────────
    if "JSON" in export_formats:
        save_json(data, f"{export_name}.json")
    if "CSV" in export_formats:
        save_csv(data, f"{export_name}.csv")
    if "TXT" in export_formats:
        save_txt(data, f"{export_name}.txt")

    # ── 10. Quick re-run or exit ───────────────────────────────────────────────
    if questionary.confirm("Scrape another URL?", default=False).ask():
        main()

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Aborted.[/dim]")
