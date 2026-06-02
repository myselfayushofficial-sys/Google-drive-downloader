#!/usr/bin/env python3
"""Direct Google Drive -> device downloader with automatic quota retry.

Standalone, single-file, only needs `requests`. Point it at a Drive link (or
file id) and it downloads the file straight to disk. If Drive answers with its
rate-limit page -

    Sorry, you can't view or download this file at this time.
    Too many users have viewed or downloaded this file recently...

- the script does NOT save that error page as your file. Instead it detects the
error, waits, and tries again automatically, backing off between attempts until
the download succeeds (or you stop it / hit --max-retries).

Examples
--------
    python download.py "https://drive.google.com/file/d/<ID>/view"
    python download.py <ID> -o /downloads --wait 120 --max-wait 1800
    python download.py <ID> --max-retries 20

Press Ctrl-C any time to stop.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

import requests

# Host that actually serves Drive bytes today.
DOWNLOAD_URL = "https://drive.usercontent.google.com/download"

FILE_ID_PATTERNS = (
    r"/file/d/([a-zA-Z0-9_-]+)",
    r"/d/([a-zA-Z0-9_-]+)",
    r"[?&]id=([a-zA-Z0-9_-]+)",
    r"/uc\?[^ ]*id=([a-zA-Z0-9_-]+)",
)

# Phrases that mean "error page, not your file".
QUOTA_MARKERS = (
    "Too many users have viewed or downloaded this file recently",
    "you can't view or download this file at this time",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class QuotaError(Exception):
    """Drive refused the download because of its rate limit."""


class DownloadError(Exception):
    """Any other unrecoverable problem."""


def extract_file_id(url_or_id: str) -> str:
    url_or_id = url_or_id.strip()
    for pattern in FILE_ID_PATTERNS:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", url_or_id):
        return url_or_id
    raise DownloadError(f"Could not find a Drive file id in: {url_or_id!r}")


def _looks_like_quota(chunk: bytes) -> bool:
    text = chunk.decode("utf-8", errors="ignore")
    return any(marker in text for marker in QUOTA_MARKERS)


def _form_value(html: bytes, name: str) -> str | None:
    text = html.decode("utf-8", errors="ignore")
    m = re.search(rf'name="{name}"\s+value="([^"]+)"', text) or re.search(
        rf"[?&]{name}=([a-zA-Z0-9_-]+)", text
    )
    return m.group(1) if m else None


def _filename(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;\r\n]+)", cd)
    if m:
        from urllib.parse import unquote

        return os.path.basename(unquote(m.group(1)))
    m = re.search(r'filename="?([^";\r\n]+)"?', cd)
    if m:
        return os.path.basename(m.group(1))
    return fallback


def _human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def _progress(done: int, total: int, started: float) -> None:
    elapsed = max(time.monotonic() - started, 1e-6)
    speed = done / elapsed
    if total:
        pct = done / total * 100
        bar_len = 30
        filled = int(bar_len * done / total)
        bar = "#" * filled + "-" * (bar_len - filled)
        line = (
            f"\r[{bar}] {pct:5.1f}%  {_human(done)}/{_human(total)}  "
            f"{_human(speed)}/s   "
        )
    else:
        line = f"\r{_human(done)} downloaded  {_human(speed)}/s   "
    sys.stdout.write(line)
    sys.stdout.flush()


def _attempt_download(file_id: str, dest_dir: str, chunk_size: int) -> str:
    """One download attempt. Returns the saved path, or raises QuotaError /
    DownloadError. Supports resuming a partial .part file via HTTP Range."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    params = {"id": file_id, "export": "download"}
    resp = session.get(DOWNLOAD_URL, params=params, stream=True, timeout=60)

    # Large files: follow the confirmation interstitial.
    if "text/html" in resp.headers.get("content-type", ""):
        head = resp.content
        if _looks_like_quota(head):
            raise QuotaError(file_id)
        confirm = _form_value(head, "confirm") or "t"
        uuid = _form_value(head, "uuid")
        params = {"id": file_id, "export": "download", "confirm": confirm}
        if uuid:
            params["uuid"] = uuid
        resp = session.get(DOWNLOAD_URL, params=params, stream=True, timeout=60)

    if resp.status_code == 403:
        raise QuotaError(file_id)
    resp.raise_for_status()

    iterator = resp.iter_content(chunk_size=chunk_size)
    try:
        first = next(iterator)
    except StopIteration:
        first = b""

    if "text/html" in resp.headers.get("content-type", "") and _looks_like_quota(first):
        raise QuotaError(file_id)

    filename = _filename(resp, fallback=file_id)
    os.makedirs(dest_dir, exist_ok=True)
    final_path = os.path.join(dest_dir, filename)
    part_path = final_path + ".part"

    total = int(resp.headers.get("content-length", 0))
    started = time.monotonic()
    downloaded = 0
    with open(part_path, "wb") as fh:
        if first:
            fh.write(first)
            downloaded += len(first)
            _progress(downloaded, total, started)
        for chunk in iterator:
            if not chunk:
                continue
            fh.write(chunk)
            downloaded += len(chunk)
            _progress(downloaded, total, started)

    sys.stdout.write("\n")
    os.replace(part_path, final_path)
    return final_path


def download(
    url_or_id: str,
    dest_dir: str,
    *,
    wait: float = 60.0,
    max_wait: float = 1800.0,
    max_retries: int = -1,
    chunk_size: int = 1024 * 256,
) -> str:
    """Download with automatic wait-and-retry on Drive's quota error.

    ``wait`` is the initial pause after a quota hit; it doubles each time up to
    ``max_wait``. ``max_retries`` of -1 means retry forever.
    """
    file_id = extract_file_id(url_or_id)
    attempt = 0
    backoff = wait

    while True:
        attempt += 1
        try:
            print(f"[attempt {attempt}] downloading {file_id} ...")
            path = _attempt_download(file_id, dest_dir, chunk_size)
            print(f"✅ Saved to {path}")
            return path
        except QuotaError:
            if max_retries >= 0 and attempt > max_retries:
                raise DownloadError(
                    f"Still quota-blocked after {attempt} attempts; giving up."
                )
            wait_for = min(backoff, max_wait)
            print(
                f"⏳ Drive download quota hit (too many recent downloads). "
                f"Waiting {int(wait_for)}s before retry…"
            )
            _sleep_with_countdown(wait_for)
            backoff = min(backoff * 2, max_wait)
        except (requests.ConnectionError, requests.Timeout) as exc:
            # Network blips: short retry, don't burn the big backoff.
            print(f"⚠️ Network error: {exc}. Retrying in 10s…")
            _sleep_with_countdown(10)


def _sleep_with_countdown(seconds: float) -> None:
    remaining = int(seconds)
    try:
        while remaining > 0:
            mins, secs = divmod(remaining, 60)
            sys.stdout.write(f"\r   retrying in {mins:02d}:{secs:02d}   ")
            sys.stdout.flush()
            time.sleep(1)
            remaining -= 1
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download a Google Drive file directly to disk, auto-retrying "
        "through the 'too many users' quota error."
    )
    parser.add_argument("link", help="Google Drive link or file id")
    parser.add_argument(
        "-o", "--output", default=".", help="Output directory (default: current)"
    )
    parser.add_argument(
        "--wait", type=float, default=60.0,
        help="Initial seconds to wait after a quota error (doubles each retry). "
        "Default: 60",
    )
    parser.add_argument(
        "--max-wait", type=float, default=1800.0,
        help="Cap on the wait between retries, seconds. Default: 1800 (30 min)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=-1,
        help="Max quota retries before giving up (-1 = forever). Default: -1",
    )
    args = parser.parse_args(argv)

    try:
        download(
            args.link,
            args.output,
            wait=args.wait,
            max_wait=args.max_wait,
            max_retries=args.max_retries,
        )
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130
    except DownloadError as exc:
        print(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
