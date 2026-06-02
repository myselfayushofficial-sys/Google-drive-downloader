"""Authenticated Google Drive downloads via the Drive REST API.

Used when the user has logged in (see ``gauth`` / ``login.py``). Compared with
anonymous link downloads this can reach private files and enjoys a per-account
quota, so it rarely trips the public download-rate wall.

We talk to the API with plain ``requests`` + a bearer token rather than the
google-api-python-client, which keeps dependencies light and lets us stream to
disk with a progress callback.

Results and exceptions mirror :mod:`gdrive` so the two download paths are
interchangeable from the bot's point of view.
"""

from __future__ import annotations

import os

import requests

import gauth
from gdrive import (
    DownloadResult,
    DriveDownloadError,
    DriveQuotaError,
    extract_file_id,
)

_API = "https://www.googleapis.com/drive/v3/files"

# Google-native docs aren't downloadable as-is; they must be exported. Map each
# editor type to a sensible binary format and file extension.
_EXPORT_FORMATS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _raise_for_quota(response: requests.Response, file_id: str) -> None:
    if response.status_code == 403:
        body = response.text
        if "downloadQuotaExceeded" in body or "userRateLimitExceeded" in body:
            raise DriveQuotaError(
                f"Drive download quota exceeded for file {file_id}; skipping."
            )


def download(url_or_id: str, dest_dir: str, *, progress=None,
             chunk_size: int = 1024 * 256) -> DownloadResult:
    """Download a Drive file using the logged-in account.

    Raises :class:`DriveQuotaError` / :class:`DriveDownloadError` exactly like
    :func:`gdrive.download`.
    """
    creds = gauth.get_credentials(interactive=False)
    if creds is None:
        raise DriveDownloadError("Not logged in to Google.")

    file_id = extract_file_id(url_or_id)
    os.makedirs(dest_dir, exist_ok=True)
    token = gauth.access_token(creds)
    session = _session(token)

    # --- Metadata ---------------------------------------------------------
    meta = session.get(
        f"{_API}/{file_id}",
        params={"fields": "name,size,mimeType", "supportsAllDrives": "true"},
        timeout=60,
    )
    _raise_for_quota(meta, file_id)
    if meta.status_code == 404:
        raise DriveDownloadError(
            f"File {file_id} not found, or your account can't access it."
        )
    if not meta.ok:
        raise DriveDownloadError(
            f"Drive metadata request failed ({meta.status_code}): {meta.text[:200]}"
        )
    info = meta.json()
    name = info.get("name", file_id)
    mime = info.get("mimeType", "")

    # --- Build the download request --------------------------------------
    if mime in _EXPORT_FORMATS:
        export_mime, ext = _EXPORT_FORMATS[mime]
        if not name.lower().endswith(ext):
            name += ext
        url = f"{_API}/{file_id}/export"
        params = {"mimeType": export_mime}
        total = 0  # exports don't report content-length up front
    elif mime.startswith("application/vnd.google-apps"):
        raise DriveDownloadError(
            f"{name!r} is a Google-native file type ({mime}) that can't be exported."
        )
    else:
        url = f"{_API}/{file_id}"
        params = {"alt": "media", "supportsAllDrives": "true"}
        total = int(info.get("size", 0) or 0)

    name = os.path.basename(name)  # defend against path separators in the name
    dest_path = os.path.join(dest_dir, name)

    with session.get(url, params=params, stream=True, timeout=60) as resp:
        _raise_for_quota(resp, file_id)
        if not resp.ok:
            raise DriveDownloadError(
                f"Drive download failed ({resp.status_code}): {resp.text[:200]}"
            )
        if not total:
            total = int(resp.headers.get("content-length", 0) or 0)

        downloaded = 0
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)

    return DownloadResult(path=dest_path, filename=name, size=downloaded)
