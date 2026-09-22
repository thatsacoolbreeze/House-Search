from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import app as house_watch

ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"
# All saved Realtor email files go in this folder. The launcher reads them before
# it starts the browser, so the dashboard always opens with the newest database data.
INCOMING_DIR = ROOT / "incoming"


def stop_existing_server() -> None:
    """Release the app port when an older local House Watch process is still running."""
    # netstat tells us which process owns the local web port. This prevents a stale
    # copy of app.py from continuing to serve an older version of the dashboard.
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        # A typical matching line contains the local address, state, and process ID.
        # Only terminate a process that is listening on House Watch's known port.
        if len(fields) >= 5 and fields[1].endswith(":8765") and fields[3] == "LISTENING":
            subprocess.run(["taskkill", "/PID", fields[4], "/F"], capture_output=True, check=False)


def import_incoming_emails() -> list[str]:
    """Import all saved .eml files before launching the browser."""
    imported: list[str] = []
    # These checks produce friendly startup messages instead of an exception when
    # the user has not created the Incoming folder or added an email yet.
    if not INCOMING_DIR.exists():
        print("No incoming folder found yet. Add .eml files there before starting the app.")
        return imported

    email_files = sorted(INCOMING_DIR.glob("*.eml"))
    if not email_files:
        print("No .eml files found in incoming/.")
        return imported

    for file_path in email_files:
        try:
            # Parsing turns the raw email into ordinary listing dictionaries.
            # import_listings then compares each dictionary with SQLite history.
            items = house_watch.parse_email_file(file_path)
            if not items:
                print(f"Skipped {file_path.name}: no listings found in the email.")
                continue

            count = house_watch.import_listings(items)
            imported.append(f"{file_path.name}: {count} listings")
            print(f"Imported {count} listings from {file_path.name}")
        except Exception as exc:  # pragma: no cover - user-facing startup safety
            print(f"Failed to import {file_path.name}: {exc}")

    return imported


if __name__ == "__main__":
    # This is the complete one-command workflow:
    # 1. Create the database if needed.
    # 2. Import every saved email once.
    # 3. Replace any stale local server.
    # 4. Start the current web app, which opens the browser.
    print("House Watch is checking the saved email files...")
    house_watch.init_db()
    import_incoming_emails()
    stop_existing_server()
    print("Starting the app server...")
    print(f"Launching {APP_FILE}")
    print("Open http://127.0.0.1:8765 after the server starts.")
    subprocess.run([sys.executable, str(APP_FILE)], cwd=str(ROOT))
