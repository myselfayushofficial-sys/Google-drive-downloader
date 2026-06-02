"""Split large files into multi-volume 7-Zip archives.

A 150 GB download is far bigger than anything Telegram will accept in a single
message, so we hand the file to ``7z`` and tell it to produce fixed-size
volumes: ``movie.mkv.7z.001``, ``movie.mkv.7z.002``, ``movie.mkv.7z.003`` …
Each volume is small enough to upload on its own, and the recipient
reassembles them with any 7-Zip client.

By default we use *store* mode (``-mx=0``) — no compression. The goal is to
chunk the file quickly, not to shrink already-compressed media. Set a
compression level via the env if you actually want compression.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import threading
import time

# Binaries that provide the 7-Zip CLI, in order of preference.
_SEVENZIP_BINARIES = ("7z", "7zz", "7za")


class ArchiverError(Exception):
    """Raised when 7-Zip is missing or the split fails."""


def find_7z() -> str:
    """Return the path to a usable 7-Zip binary, or raise."""
    for name in _SEVENZIP_BINARIES:
        path = shutil.which(name)
        if path:
            return path
    raise ArchiverError(
        "7-Zip not found. Install it, e.g. `apt-get install p7zip-full` "
        "(provides `7z`) or `7zip` on other platforms."
    )


def is_available() -> bool:
    try:
        find_7z()
        return True
    except ArchiverError:
        return False


def split_archive(
    file_path: str,
    dest_dir: str,
    *,
    part_size_mb: int = 2000,
    level: int = 0,
    password: str | None = None,
    progress=None,
    poll_interval: float = 1.0,
) -> list[str]:
    """Split ``file_path`` into ``part_size_mb`` MB 7-Zip volumes inside
    ``dest_dir`` and return the volume paths in order.

    ``progress`` is an optional ``(done_bytes, total_bytes)`` callable, invoked
    roughly every ``poll_interval`` seconds based on how much volume data has
    been written so far.
    """
    binary = find_7z()
    os.makedirs(dest_dir, exist_ok=True)

    base = os.path.basename(file_path)
    archive = os.path.join(dest_dir, f"{base}.7z")

    # Clear any leftover volumes from a previous interrupted run so the byte
    # accounting and final glob are accurate.
    for stale in glob.glob(f"{archive}.*"):
        try:
            os.remove(stale)
        except OSError:
            pass

    cmd = [
        binary,
        "a",                      # add to archive
        f"-v{part_size_mb}m",     # split into volumes of this size
        f"-mx={level}",           # compression level (0 = store)
        "-y",                     # assume yes
        "-bso0", "-bse0", "-bsp0",  # silence 7z's own stdout/stderr/progress
        archive,
        file_path,
    ]
    if password:
        cmd.append(f"-p{password}")
        cmd.append("-mhe=on")     # also encrypt the file names / headers

    total = os.path.getsize(file_path)

    stop = threading.Event()

    def _watch():
        # Report progress by summing the sizes of the volumes produced so far.
        while not stop.is_set():
            done = sum(
                os.path.getsize(p)
                for p in glob.glob(f"{archive}.*")
                if os.path.exists(p)
            )
            if progress:
                progress(min(done, total), total)
            stop.wait(poll_interval)

    watcher = threading.Thread(target=_watch, daemon=True)
    if progress:
        watcher.start()

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    finally:
        stop.set()
        if progress:
            watcher.join(timeout=2)

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="ignore").strip()
        raise ArchiverError(f"7z failed (exit {result.returncode}): {err}")

    parts = sorted(glob.glob(f"{archive}.*"))
    if not parts:
        # Single-volume case: 7z may emit just `name.7z` when the file fits in
        # one volume. Normalise to a list so callers always iterate.
        if os.path.exists(archive):
            parts = [archive]
        else:
            raise ArchiverError("7z reported success but produced no output volumes.")

    if progress:
        progress(total, total)
    return parts
