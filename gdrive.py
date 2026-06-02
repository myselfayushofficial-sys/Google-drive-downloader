"""Google Drive download helpers.

Handles the awkward parts of pulling files off Google Drive without the
official API:

* extracting a file id from any of the common share-link shapes
* following the "virus scan / can't be scanned" confirmation page that
  Drive shows for large files
* detecting the quota page ("Too many users have viewed or downloaded this
  file recently") so the caller can *skip* it instead of saving an HTML
  error page as if it were the real file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

# drive.usercontent.google.com is the host that actually serves bytes today;
# the older /uc?export=download endpoint still works and redirects here.
_DOWNLOAD_URL = "https://drive.usercontent.google.com/download"

_FILE_ID_PATTERNS = (
    r"/file/d/([a-zA-Z0-9_-]+)",          # .../file/d/<id>/view
    r"/d/([a-zA-Z0-9_-]+)",               # .../d/<id>
    r"[?&]id=([a-zA-Z0-9_-]+)",           # ...?id=<id>
    r"/uc\?[^ ]*id=([a-zA-Z0-9_-]+)",     # uc?export=download&id=<id>
)

# Phrases that mean "this is an error page, not your file".
_QUOTA_MARKERS = (
    "Too many users have viewed or downloaded this file recently",
    "you can't view or download this file at this time",
)


class DriveQuotaError(Exception):
    """Raised when Drive refuses the download because of its rate limit.

    The caller is expected to catch this and skip the file rather than
    treating it as a hard failure.
    """


class DriveDownloadError(Exception):
    """Raised for any other unrecoverable download problem."""


@dataclass
class DownloadResult:
    path: str
    filename: str
    size: int


def extract_file_id(url_or_id: str) -> str:
    """Return the Drive file id from a share link, or the input if it already
    looks like a bare id."""
    url_or_id = url_or_id.strip()
    for pattern in _FILE_ID_PATTERNS:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    # No URL structure found - assume the user pasted a raw id.
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", url_or_id):
        return url_or_id
    raise DriveDownloadError(f"Could not find a Google Drive file id in: {url_or_id!r}")


def _looks_like_quota_page(chunk: bytes) -> bool:
    text = chunk.decode("utf-8", errors="ignore")
    return any(marker in text for marker in _QUOTA_MARKERS)


def _filename_from_headers(response: requests.Response, fallback: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    # Prefer the RFC 5987 filename*=UTF-8'' form, fall back to plain filename=.
    match = re.search(r"filename\*=UTF-8''([^;\r\n]+)", disposition)
    if match:
        from urllib.parse import unquote

        return unquote(match.group(1))
    match = re.search(r'filename="?([^";\r\n]+)"?', disposition)
    if match:
        return match.group(1)
    return fallback


def download(
    url_or_id: str,
    dest_dir: str,
    *,
    progress=None,
    chunk_size: int = 1024 * 256,
) -> DownloadResult:
    """Download a single Google Drive file into ``dest_dir``.

    ``progress`` is an optional callable ``(downloaded_bytes, total_bytes)``
    invoked as data arrives; ``total_bytes`` is 0 when Drive does not report
    a length.

    Raises :class:`DriveQuotaError` on the rate-limit page and
    :class:`DriveDownloadError` for other failures.
    """
    file_id = extract_file_id(url_or_id)
    os.makedirs(dest_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
    )

    params = {"id": file_id, "export": "download"}
    response = session.get(_DOWNLOAD_URL, params=params, stream=True, timeout=60)

    # Large files return an interstitial HTML page with a confirm token and,
    # nowadays, a uuid. Re-request with those to get the actual bytes.
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        head = response.content  # small HTML page, safe to buffer fully
        if _looks_like_quota_page(head):
            raise DriveQuotaError(
                f"Drive download quota exceeded for file {file_id}; skipping."
            )
        confirm = _parse_form_value(head, "confirm") or "t"
        uuid = _parse_form_value(head, "uuid")
        params = {"id": file_id, "export": "download", "confirm": confirm}
        if uuid:
            params["uuid"] = uuid
        response = session.get(
            _DOWNLOAD_URL, params=params, stream=True, timeout=60
        )

    response.raise_for_status()

    # Final guard: even after confirming we might still land on the quota page.
    iterator = response.iter_content(chunk_size=chunk_size)
    try:
        first_chunk = next(iterator)
    except StopIteration:
        first_chunk = b""

    if "text/html" in response.headers.get("content-type", "") and _looks_like_quota_page(
        first_chunk
    ):
        raise DriveQuotaError(
            f"Drive download quota exceeded for file {file_id}; skipping."
        )

    filename = _filename_from_headers(response, fallback=file_id)
    # Strip any path separators a malicious filename might carry.
    filename = os.path.basename(filename)
    dest_path = os.path.join(dest_dir, filename)

    total = int(response.headers.get("content-length", 0))
    downloaded = 0
    with open(dest_path, "wb") as fh:
        if first_chunk:
            fh.write(first_chunk)
            downloaded += len(first_chunk)
            if progress:
                progress(downloaded, total)
        for chunk in iterator:
            if not chunk:
                continue
            fh.write(chunk)
            downloaded += len(chunk)
            if progress:
                progress(downloaded, total)

    return DownloadResult(path=dest_path, filename=filename, size=downloaded)


def _parse_form_value(html_bytes: bytes, name: str) -> str | None:
    text = html_bytes.decode("utf-8", errors="ignore")
    # Works for both <input name="confirm" value="t"> and ?confirm=t links.
    match = re.search(
        rf'name="{name}"\s+value="([^"]+)"', text
    ) or re.search(rf'[?&]{name}=([a-zA-Z0-9_-]+)', text)
    return match.group(1) if match else None
