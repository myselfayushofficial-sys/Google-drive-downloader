"""Telegram bot: send it Google Drive links, it downloads each file and
uploads it back to the chat.

Key behaviour: if a file hits Drive's "Too many users have viewed or
downloaded this file recently" quota wall (or any other per-file error), the
bot reports it and *moves on* to the next link instead of aborting the whole
batch.
"""

from __future__ import annotations

import asyncio
import os
import time

from pyrogram import Client, filters
from pyrogram.types import Message

import config
import gdrive

app = Client(
    "gdrive-downloader",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def _is_allowed(message: Message) -> bool:
    if not config.ALLOWED_USERS:
        return True
    return message.from_user and message.from_user.id in config.ALLOWED_USERS


def _extract_links(text: str) -> list[str]:
    """Pull every whitespace-separated token that looks like a Drive link/id."""
    tokens = text.split()
    links = []
    for token in tokens:
        if "drive.google" in token or "usercontent.google" in token or "/d/" in token:
            links.append(token)
    return links


class _Throttle:
    """Limit how often we edit the Telegram status message (Telegram rate-limits
    edits, and editing on every chunk is wasteful)."""

    def __init__(self, interval: float = 4.0):
        self.interval = interval
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False


@app.on_message(filters.command("start"))
async def start(_: Client, message: Message):
    await message.reply_text(
        "👋 Send me one or more Google Drive links and I'll download each file "
        "and upload it here.\n\n"
        "• Multiple links (one per line or space separated) are processed in order.\n"
        "• Files blocked by Drive's download-quota error are skipped automatically, "
        "and I'll keep going with the rest."
    )


@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def handle_links(client: Client, message: Message):
    if not _is_allowed(message):
        await message.reply_text("⛔ You are not authorised to use this bot.")
        return

    links = _extract_links(message.text)
    if not links:
        await message.reply_text(
            "I didn't find any Google Drive links in that message. "
            "Send a link like https://drive.google.com/file/d/<id>/view"
        )
        return

    total = len(links)
    skipped: list[str] = []
    succeeded = 0

    for index, link in enumerate(links, start=1):
        status = await message.reply_text(f"[{index}/{total}] Starting…")
        try:
            await _process_one(client, message, status, link)
            succeeded += 1
        except gdrive.DriveQuotaError:
            skipped.append(link)
            await status.edit_text(
                f"[{index}/{total}] ⏭️ Skipped — Drive download quota exceeded "
                f"for this file (too many recent downloads). Try again later.\n{link}"
            )
        except gdrive.DriveDownloadError as exc:
            skipped.append(link)
            await status.edit_text(f"[{index}/{total}] ⚠️ Skipped — {exc}\n{link}")
        except Exception as exc:  # noqa: BLE001 - keep batch alive on any error
            skipped.append(link)
            await status.edit_text(
                f"[{index}/{total}] ⚠️ Skipped — unexpected error: {exc}\n{link}"
            )

    if total > 1:
        summary = [f"✅ Done. {succeeded}/{total} uploaded."]
        if skipped:
            summary.append(f"⏭️ {len(skipped)} skipped:")
            summary.extend(f"  • {url}" for url in skipped)
        await message.reply_text("\n".join(summary))


async def _process_one(
    client: Client, message: Message, status: Message, link: str
) -> None:
    loop = asyncio.get_running_loop()
    throttle = _Throttle()

    # --- Download phase ---------------------------------------------------
    def on_progress(done: int, total: int):
        if not throttle.ready():
            return
        if total:
            pct = done / total * 100
            text = (
                f"⬇️ Downloading… {pct:.0f}% "
                f"({_human_size(done)}/{_human_size(total)})"
            )
        else:
            text = f"⬇️ Downloading… {_human_size(done)}"
        # Schedule the edit on the event loop from this worker thread.
        asyncio.run_coroutine_threadsafe(_safe_edit(status, text), loop)

    await status.edit_text("⬇️ Downloading…")
    result = await loop.run_in_executor(
        None,
        lambda: gdrive.download(link, config.DOWNLOAD_DIR, progress=on_progress),
    )

    # --- Upload phase -----------------------------------------------------
    await _safe_edit(status, f"⬆️ Uploading {result.filename}…")
    up_throttle = _Throttle()

    async def upload_progress(current: int, total: int):
        if not up_throttle.ready():
            return
        pct = current / total * 100 if total else 0
        await _safe_edit(
            status,
            f"⬆️ Uploading {result.filename}… {pct:.0f}% "
            f"({_human_size(current)}/{_human_size(total)})",
        )

    try:
        await client.send_document(
            chat_id=message.chat.id,
            document=result.path,
            file_name=result.filename,
            caption=f"📁 {result.filename}\n💾 {_human_size(result.size)}",
            progress=upload_progress,
        )
        await status.edit_text(f"✅ Uploaded {result.filename}")
    finally:
        # Clean up the staged file whether or not the upload succeeded.
        try:
            os.remove(result.path)
        except OSError:
            pass


async def _safe_edit(status: Message, text: str) -> None:
    """Edit a status message, swallowing the harmless 'message not modified'
    and flood-wait noise so progress updates never crash the handler."""
    try:
        await status.edit_text(text)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    print("Starting Google Drive → Telegram bot…")
    app.run()
