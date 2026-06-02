# Direct Drive Downloader (auto-retry on quota error)

A standalone script that downloads a Google Drive file **straight to your
device** and automatically works around Drive's rate-limit page:

> **Sorry, you can't view or download this file at this time.**
> Too many users have viewed or downloaded this file recently…

When it sees that page it does **not** save it as your file. It detects the
error, **waits, and retries automatically** with increasing back-off until the
download succeeds (or you stop it).

## Requirements

```bash
pip install requests
```

(That's the only dependency — the script is otherwise self-contained.)

## Usage

```bash
# Basic — download to the current folder
python download.py "https://drive.google.com/file/d/<FILE_ID>/view"

# Choose an output folder
python download.py <FILE_ID> -o /path/to/downloads

# Tune the waiting: start at 2 min, cap retries at 30 min apart
python download.py <FILE_ID> --wait 120 --max-wait 1800

# Give up after 20 quota retries instead of trying forever
python download.py <FILE_ID> --max-retries 20
```

Press **Ctrl-C** any time to stop.

## How the retry works

| Option         | Meaning                                                        | Default      |
| -------------- | -------------------------------------------------------------- | ------------ |
| `--wait`       | Seconds to wait after the first quota hit (doubles each retry) | `60`         |
| `--max-wait`   | Upper cap on the wait between retries                          | `1800` (30m) |
| `--max-retries`| Quota retries before giving up (`-1` = forever)                | `-1`         |

- The wait grows `60 → 120 → 240 → …` up to `--max-wait`, so it backs off
  politely instead of hammering Drive.
- Drive's quota typically clears within a few hours (sometimes up to 24h for
  very popular files), so leaving it running with the default settings will
  usually pick the file up automatically once the limit resets.
- Transient network errors retry quickly (10s) without consuming the quota
  back-off.

## Notes

- Handles all common link shapes (`/file/d/<id>`, `?id=<id>`, `/d/<id>`, bare id)
  and follows Drive's large-file confirmation page automatically.
- Downloads to a `.part` file and renames it on success, so you never end up
  with a half-written file that looks complete.
- Only downloads files you have permission to access; it does not bypass Drive
  permissions.
