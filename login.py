"""One-time Google login.

Run this once on a machine where you can open a browser:

    python login.py

It opens Google's consent screen, then saves a reusable token to
``token.json`` (path configurable via GOOGLE_TOKEN_FILE). The bot picks it up
automatically and refreshes it silently from then on.

If you're on a headless server, forward the local port over SSH, e.g.:
    ssh -L 8080:localhost:8080 user@server
and complete the consent in your local browser.
"""

from __future__ import annotations

import sys

import config
import gauth


def main() -> int:
    try:
        creds = gauth.get_credentials(interactive=True)
    except gauth.GoogleAuthError as exc:
        print(f"Login failed: {exc}")
        return 1

    if creds is None:
        print("Login did not complete.")
        return 1

    print(f"✅ Logged in. Token saved to {config.GOOGLE_TOKEN_FILE}.")
    print("The bot will now download via your Google account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
