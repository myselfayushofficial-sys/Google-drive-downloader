# Google Drive → Telegram Downloader Bot

A Telegram bot that takes Google Drive share links, downloads each file, and
uploads it straight into your Telegram chat.

It is built to survive Google Drive's most annoying failure mode:

> **Sorry, you can't view or download this file at this time.**
> Too many users have viewed or downloaded this file recently…

When a file hits that download-quota wall (or any other per-file error), the
bot **skips it and keeps going** with the rest of your links instead of
crashing the whole batch.

## Features

- Send one or many Drive links (one per line or space-separated) — processed in order.
- Handles every common link shape: `/file/d/<id>/view`, `?id=<id>`, `/d/<id>`, or a bare file id.
- Follows Drive's large-file "virus scan" confirmation page automatically.
- Detects the quota / "can't download right now" error page and **skips** it
  cleanly (no half-written HTML error files).
- Live download **and** upload progress, throttled so Telegram doesn't rate-limit edits.
- Optional user allow-list.
- Staged files are deleted after upload.

## Setup

1. **Get Telegram credentials**
   - `API_ID` and `API_HASH` from <https://my.telegram.org> → *API development tools*.
   - `BOT_TOKEN` from [@BotFather](https://t.me/BotFather).

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure**

   ```bash
   cp .env.example .env
   # then edit .env and fill in API_ID, API_HASH, BOT_TOKEN
   ```

4. **Run**

   ```bash
   python bot.py
   ```

## Usage

Open a chat with your bot and send it Drive links:

```
https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view
https://drive.google.com/file/d/2ZyXwVuTsRqPoNmLkJiHgFeDcBa/view
```

The bot downloads each file and uploads it back. If link #1 is quota-blocked,
you'll see a `⏭️ Skipped` notice and it will still upload link #2.

## Notes & limits

- Telegram bots can upload files up to **2 GB** (4 GB with a Premium account
  on the uploading session). Larger files will fail to upload — that file is
  skipped, the batch continues.
- This tool only downloads files **you have permission to access**. It does not
  bypass Drive permissions; the quota error is a temporary rate limit that
  usually clears within 24 hours.
- `DOWNLOAD_DIR` is just a staging area; files are removed once uploaded.

## Project layout

| File              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `bot.py`          | Telegram bot: link parsing, batching, progress, error-skipping |
| `gdrive.py`       | Drive download logic + quota/confirmation handling             |
| `config.py`       | Loads settings from `.env`                                     |
| `requirements.txt`| Dependencies                                                   |
