# X.com Scraper 🐦‍⬛🔍
**X.com Scraper** is a powerful Python tool that uses a real Chromium browser to extract tweets, profiles, threads, and search results from X.com — then cleans and structures the data into readable output and exportable files (JSON, CSV, TXT). No API key needed.

## ✨ Features

| Feature | Description |
| :--- | :--- |
| **Auto Page Detection** | Paste any X.com URL — the scraper detects if it's a profile, tweet thread, search, or hashtag automatically. |
| **Real Browser Engine** | Uses Playwright (Chromium) to fully render JavaScript-heavy pages that raw HTTP requests can't access. |
| **Rich Terminal Display** | Color-coded tweet output with engagement stats, author info, media flags, and a summary table. |
| **Multi-format Export** | Save results as JSON, CSV, or TXT — or all three at once. |
| **Smart Filtering** | Filter by keyword, minimum likes, media-only, or strip out reposts — before display or export. |
| **Cookie Auth Support** | Load your browser session cookies to access more content and avoid login walls. |
| **Interactive Menu** | Fully guided CLI — no flags to memorize, no config files to edit. |

---

## 🚀 Setup

You need **Python 3.10+** and three packages.

### 1. Install dependencies

```bash
pip install playwright rich questionary
playwright install chromium
```

> `playwright install chromium` downloads the browser engine (~150 MB, one-time only).

### 2. Run the scraper

Place `scraper.py` in any folder and run:

```bash
python scraper.py
```

---

## 🛠️ How to Use

### Step 1 — Paste a URL

The scraper accepts any X.com URL:

| URL type | Example |
| :--- | :--- |
| **Profile** | `x.com/elonmusk` |
| **Tweet / Thread** | `x.com/user/status/123456789` |
| **Search results** | `x.com/search?q=AI` |
| **Hashtag** | `x.com/hashtag/python` |

### Step 2 — Choose your settings

The interactive menu walks you through:

1. **Max tweets** — collect 20, 50, 100, 200, or 500 tweets
2. **Filters** (optional checkboxes):
   - Media only (images or videos)
   - Exclude reposts
   - Keyword match (case-insensitive)
   - Minimum likes threshold
3. **Search tab** *(search URLs only)* — Top / Latest / People / Media
4. **Display mode** — Full output, summary table only, or silent
5. **Export formats** — JSON, CSV, TXT (any combination)
6. **Advanced options** — non-headless browser, cookie file

### Step 3 — Review output

Each tweet is printed with:
- Author name, handle, and timestamp
- Full tweet text (wrapped for readability)
- Engagement stats: 💬 replies · 🔁 reposts · ❤️ likes · 👁 views
- Image/video URLs if present
- Direct link to the tweet

A summary table is shown at the end with totals and the top-performing tweet.

---

## 🔐 Using Cookies (Recommended)

X.com shows less data to logged-out users. For best results, load your own browser session:

1. Install the **EditThisCookie** extension (Chrome) or **Cookie-Editor** (Firefox)
2. Log into X.com in your browser
3. Export cookies as JSON and save the file (e.g. `cookies.json`) in the same folder as `scraper.py`
4. When prompted for advanced options, select **Load cookies from file** and enter the path

> ⚠️ Never share your cookie file — it grants full access to your account.

---

## 📁 Export Files

When you choose to export, files are saved automatically in the same folder as `scraper.py` with a timestamped name like `x_elonmusk_20250313_142301.json`.

| Format | Contents |
| :--- | :--- |
| **JSON** | Full structured data including profile info, all tweet fields, media URLs, and metadata |
| **CSV** | Flat spreadsheet — one row per tweet, easy to open in Excel or Google Sheets |
| **TXT** | Human-readable plain text, ideal for pasting into an LLM chat |

---

## 🤖 Recommended LLM Prompt

Use the TXT export with this prompt for best results in ChatGPT, Claude, or Gemini:

```text
System Instructions:
I am providing a cleaned X.com dataset. Please process it using these rules:

1. Author Context: Each tweet includes an author handle, timestamp, and engagement score.
   Weight highly-liked and highly-reposted tweets as more significant signals.
2. Thread Awareness: If a [Root] tweet is present, treat it as the topic anchor.
   All following tweets are replies or related content in that thread.
3. Repost Handling: Tweets marked [Repost] represent amplified content, not original thoughts.
4. Media Awareness: Tweets flagged with 📷 or 🎥 may have visual context not captured in text.
5. Task: Analyze the provided tweets for key themes, sentiment, notable opinions, and emerging narratives.

User Request: [INSERT YOUR REQUEST HERE — e.g., "What are the most common criticisms mentioned?"]

---
[PASTE CONTENT FROM .TXT EXPORT HERE]
```

---

## ❓ Troubleshooting

| Issue | Solution |
| :--- | :--- |
| **`playwright install` not recognized** | Run `python -m playwright install chromium` instead. |
| **Page loads but no tweets found** | X.com may be showing a login wall. Try loading cookies (see above). |
| **Scrape stops early** | The page may have fewer tweets than your limit, or X.com throttled the scroll. Try reducing the max count. |
| **Browser visible but nothing happens** | Run in non-headless mode (select "Show browser") to watch and debug live. |
| **Encoding errors on Windows** | Run `chcp 65001` in your terminal before executing the script. |
| **`ModuleNotFoundError`** | Re-run `pip install playwright rich questionary` and ensure you're using Python 3.10+. |

---

## ⚠️ Disclaimer

This tool is intended for personal research and data analysis. Use it responsibly and in accordance with [X.com's Terms of Service](https://twitter.com/en/tos). Do not use it to harvest data at scale, build commercial products, or violate user privacy.
