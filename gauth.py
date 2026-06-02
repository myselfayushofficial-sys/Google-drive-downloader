"""Google OAuth credential handling for authenticated Drive downloads.

Logging in with a Google account beats anonymous link downloads in two ways:

* you can fetch files that are private to your account (not just "anyone with
  the link" files), and
* authenticated requests get their own, much friendlier quota, so you hit the
  "too many users downloaded this recently" wall far less often.

The OAuth dance needs a browser exactly once. Run ``python login.py`` on a
machine where you can open a browser (or use SSH port-forwarding); it stores a
refresh token in ``token.json`` and the bot reuses it forever after,
refreshing silently.

Google library imports are done lazily so that anonymous-only users don't need
the google-auth packages installed at all.
"""

from __future__ import annotations

import json
import os

import config

# Read-only access to Drive is all a downloader needs.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleAuthError(Exception):
    pass


def _missing_libs_message() -> str:
    return (
        "Google login requires extra packages. Install them with:\n"
        "    pip install google-auth google-auth-oauthlib"
    )


def has_token() -> bool:
    """True if a saved login token exists on disk."""
    return os.path.exists(config.GOOGLE_TOKEN_FILE)


def get_credentials(*, interactive: bool = False):
    """Return valid Google credentials, or ``None`` when not logged in.

    With ``interactive=True`` and no usable token, this launches the one-time
    browser login flow (used by ``login.py``). With ``interactive=False`` (the
    bot's path) it only loads/refreshes an existing token and never blocks.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise GoogleAuthError(_missing_libs_message()) from exc

    creds = None
    if has_token():
        creds = Credentials.from_authorized_user_file(
            config.GOOGLE_TOKEN_FILE, SCOPES
        )

    if creds and creds.valid:
        return creds

    # Try a silent refresh first.
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception:  # noqa: BLE001 - fall through to interactive/None
            creds = None

    if not interactive:
        return None

    # One-time interactive login.
    if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        raise GoogleAuthError(
            f"OAuth client file {config.GOOGLE_CREDENTIALS_FILE!r} not found. "
            "Create an OAuth client ID (type: Desktop app) in Google Cloud "
            "Console, download the JSON, and save it there. See the README."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover
        raise GoogleAuthError(_missing_libs_message()) from exc

    flow = InstalledAppFlow.from_client_secrets_file(
        config.GOOGLE_CREDENTIALS_FILE, SCOPES
    )
    # port=0 picks a free port; opens the browser and captures the redirect.
    creds = flow.run_local_server(port=0)
    _save(creds)
    return creds


def access_token(creds) -> str:
    """Return a fresh bearer token from credentials, refreshing if needed."""
    from google.auth.transport.requests import Request

    if not creds.valid:
        creds.refresh(Request())
        _save(creds)
    return creds.token


def _save(creds) -> None:
    with open(config.GOOGLE_TOKEN_FILE, "w") as fh:
        fh.write(creds.to_json())
    # Token file holds a refresh token — keep it owner-only.
    try:
        os.chmod(config.GOOGLE_TOKEN_FILE, 0o600)
    except OSError:
        pass
