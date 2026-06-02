"""Runtime configuration, loaded from environment / .env file."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# Telegram credentials. api_id / api_hash come from https://my.telegram.org,
# the bot token from @BotFather.
API_ID = int(_require("API_ID"))
API_HASH = _require("API_HASH")
BOT_TOKEN = _require("BOT_TOKEN")

# Where downloads are staged before being uploaded to Telegram.
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")

# Optional whitelist of Telegram user ids allowed to use the bot (comma
# separated). Empty means "anyone".
_allowed = os.getenv("ALLOWED_USERS", "").strip()
ALLOWED_USERS = {int(x) for x in _allowed.split(",") if x.strip()} if _allowed else set()

# --- Large-file / 7z splitting ------------------------------------------
# Files larger than this are split into multi-volume 7z archives before
# upload. Also the size of each volume. Keep it under your Telegram upload
# limit (2000 MB for a normal account, up to 4000 MB for Premium).
PART_SIZE_MB = int(os.getenv("PART_SIZE_MB", "2000"))

# 7z compression level: 0 = store (fast, just chunks), up to 9 = max.
# Store is the sensible default for already-compressed media.
SEVENZIP_LEVEL = int(os.getenv("SEVENZIP_LEVEL", "0"))

# Optional password for the produced 7z volumes (also encrypts file names).
SEVENZIP_PASSWORD = os.getenv("SEVENZIP_PASSWORD", "").strip() or None
