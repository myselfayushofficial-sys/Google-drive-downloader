"""Chooses the best available Drive download path.

If the user has logged in with Google (a ``token.json`` exists and is usable),
downloads go through the authenticated Drive API for better access and quota.
Otherwise it falls back to the anonymous public-link downloader.
"""

from __future__ import annotations

import config
import gdrive

# gauth pulls in google libs lazily, so importing it is cheap and safe even
# when those libs aren't installed.
import gauth


def login_active() -> bool:
    """True if Google login is enabled and a usable token is present."""
    if not config.USE_GOOGLE_AUTH:
        return False
    if not gauth.has_token():
        return False
    try:
        return gauth.get_credentials(interactive=False) is not None
    except gauth.GoogleAuthError:
        return False


def download(url_or_id: str, dest_dir: str, *, progress=None) -> gdrive.DownloadResult:
    """Download via the authenticated API when logged in, else anonymously.

    Raises the same :class:`gdrive.DriveQuotaError` / ``DriveDownloadError`` as
    the underlying downloaders, so callers handle both paths identically.
    """
    if login_active():
        # Imported here so anonymous-only deployments never need google libs.
        import gdrive_api

        return gdrive_api.download(url_or_id, dest_dir, progress=progress)
    return gdrive.download(url_or_id, dest_dir, progress=progress)
