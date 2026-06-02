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
- **Huge files (100–150 GB+)**: anything over the upload limit is split into
  multi-volume 7z archives — `file.7z.001`, `.002`, `.003`, … — and each part
  is uploaded in order. Reassemble with any 7-Zip client.
- Live download, **split**, and upload progress, throttled so Telegram doesn't rate-limit edits.
- Optional 7z password (encrypts file names too) and optional user allow-list.
- Staged files and volumes are deleted as soon as each upload finishes.

## Setup

1. **Get Telegram credentials**
   - `API_ID` and `API_HASH` from <https://my.telegram.org> → *API development tools*.
   - `BOT_TOKEN` from [@BotFather](https://t.me/BotFather).

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   # 7-Zip is required for splitting big files:
   sudo apt-get install -y p7zip-full     # Debian/Ubuntu  (provides `7z`)
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

## Big files & chunked 7z upload

When a downloaded file is larger than `PART_SIZE_MB` (default 2000 MB), the bot
runs `7z` to split it into fixed-size volumes and uploads each one:

```
movie.mkv.7z.001   (2000 MB)
movie.mkv.7z.002   (2000 MB)
movie.mkv.7z.003   (1234 MB)
```

So a 150 GB download arrives as ~75 parts. Download all parts into one folder
and open `.7z.001` with any 7-Zip client to reassemble the original file.

- Default mode is **store** (`SEVENZIP_LEVEL=0`) — it just chunks, no slow
  compression, which is right for already-compressed media. Raise the level if
  you want compression.
- **Disk space:** the server needs room for the full download *plus* its
  volumes while splitting — budget roughly **2× the file size** of free disk
  (e.g. ~300 GB free to handle a 150 GB file). Each volume is deleted right
  after it uploads.

## Upload limits & the local Bot API server

This is the part people get confused about, so to be precise:

- **This bot uses Pyrogram**, which speaks Telegram's **MTProto** protocol
  directly. That gives **2 GB per file** uploads out of the box (4 GB if the
  uploading account has Premium) — **no local server required.** The 50 MB
  Bot-API upload cap does **not** apply here.
- The classic *"host the Bot API locally for 2 GB"* advice only matters if you
  use a **Bot API** library (`python-telegram-bot`, `aiogram`, `telebot`),
  where `api.telegram.org` caps uploads at 50 MB and a self-hosted
  [`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) server raises
  that to 2000 MB.

For that case a ready-to-use local server is included in
[`docker-compose.yml`](docker-compose.yml):

```bash
docker compose up -d telegram-bot-api
# then point your Bot API library at http://localhost:8081/bot<token>/...
```

Either way, the **7z chunking above is what lets you exceed the per-file limit**
and ship 100–150 GB files in parts.

## Notes

- This tool only downloads files **you have permission to access**. It does not
  bypass Drive permissions; the quota error is a temporary rate limit that
  usually clears within 24 hours.
- `DOWNLOAD_DIR` is just a staging area; files (and volumes) are removed once uploaded.

## Project layout

| File              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `bot.py`          | Telegram bot: link parsing, batching, progress, error-skipping |
| `gdrive.py`       | Drive download logic + quota/confirmation handling             |
| `archiver.py`     | Splits big files into multi-volume 7z archives                 |
| `config.py`       | Loads settings from `.env`                                     |
| `docker-compose.yml` | Optional self-hosted Bot API server                         |
| `requirements.txt`| Dependencies                                                   |
