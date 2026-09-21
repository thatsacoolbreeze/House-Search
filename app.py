from __future__ import annotations

import json  # Reads JSON requests sent by the dashboard and snapshot importer.
import sqlite3  # Stores listings and their change history in a local database.
import webbrowser  # Opens the dashboard automatically when the server starts.
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ROOT makes all project paths work even when app.py is started from another folder.
ROOT = Path(__file__).parent
# SQLite keeps the data on this computer; it is ignored by Git because it contains your history.
DB_PATH = ROOT / "house_watch.db"
# The server is local-only, so listings are not exposed to the internet.
HOST = "127.0.0.1"
PORT = 8765
# These are the first search rules. They can later move into a settings screen.
DEFAULT_MAX_PRICE = 550000


def now() -> str:
    # Use UTC timestamps so future email imports can compare events consistently.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    # row_factory lets the rest of the app access database columns by name.
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    # Create the database tables the first time the program runs.
    # listings stores the latest known version of each property.
    # changes stores the history needed to report new listings and price changes.
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                city TEXT NOT NULL,
                province TEXT NOT NULL,
                price INTEGER NOT NULL,
                bedrooms INTEGER,
                bathrooms REAL,
                property_type TEXT NOT NULL,
                leased_land INTEGER NOT NULL DEFAULT 0,
                url TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            );
            """
        )


def normalize_listing(raw: dict) -> dict:
    # Convert one provider/import record into the consistent shape used by our database.
    # An email parser will call this same function after extracting fields from the email.
    return {
        "id": str(raw["id"]),
        "address": str(raw.get("address", "Unknown address")),
        "city": str(raw.get("city", "Ottawa")),
        "province": str(raw.get("province", "ON")),
        "price": int(raw["price"]),
        "bedrooms": int(raw["bedrooms"]) if raw.get("bedrooms") not in (None, "") else None,
        "bathrooms": float(raw["bathrooms"]) if raw.get("bathrooms") not in (None, "") else None,
        "property_type": str(raw.get("property_type", "Detached")),
        "leased_land": bool(raw.get("leased_land", False)),
        "url": str(raw.get("url", "")),
    }


def import_listings(items: list[dict]) -> int:
    # Process one complete snapshot. A snapshot may come from JSON today or an email later.
    timestamp = now()
    imported = 0
    with connect() as connection:
        for raw in items:
            # Normalize before comparing so values from different sources are comparable.
            listing = normalize_listing(raw)
            existing = connection.execute("SELECT * FROM listings WHERE id = ?", (listing["id"],)).fetchone()
            if existing is None:
                # A listing ID that has never been seen is a new-listing event.
                connection.execute(
                    """INSERT INTO listings
                    (id, address, city, province, price, bedrooms, bathrooms, property_type,
                     leased_land, url, status, first_seen, last_seen, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
                    (*listing.values(), timestamp, timestamp, timestamp),
                )
                connection.execute(
                    "INSERT INTO changes (listing_id, kind, old_value, new_value, occurred_at) VALUES (?, 'new', NULL, ?, ?)",
                    (listing["id"], str(listing["price"]), timestamp),
                )
            else:
                if existing["price"] != listing["price"]:
                    # Comparing the old and new prices tells us whether the price rose or fell.
                    kind = "price_drop" if listing["price"] < existing["price"] else "price_increase"
                    connection.execute(
                        "INSERT INTO changes (listing_id, kind, old_value, new_value, occurred_at) VALUES (?, ?, ?, ?, ?)",
                        (listing["id"], kind, str(existing["price"]), str(listing["price"]), timestamp),
                    )
                connection.execute(
                    """UPDATE listings SET address=?, city=?, province=?, price=?, bedrooms=?, bathrooms=?,
                    property_type=?, leased_land=?, url=?, status='active', last_seen=?, updated_at=? WHERE id=?""",
                    (
                        listing["address"], listing["city"], listing["province"], listing["price"],
                        listing["bedrooms"], listing["bathrooms"], listing["property_type"],
                        listing["leased_land"], listing["url"], timestamp, timestamp, listing["id"],
                    ),
                )
            imported += 1
    return imported


def filtered_listings() -> list[dict]:
    # Only matching records appear in the dashboard; all imported history remains in SQLite.
    with connect() as connection:
        rows = connection.execute(
            """SELECT * FROM listings
            WHERE city = 'Ottawa' AND province = 'ON' AND price <= ?
              AND lower(property_type) = 'detached' AND leased_land = 0 AND status = 'active'
            ORDER BY price ASC""",
            (DEFAULT_MAX_PRICE,),
        ).fetchall()
        return [dict(row) for row in rows]


def recent_changes() -> list[dict]:
    # Return the newest events so the dashboard can show recent activity.
    with connect() as connection:
        rows = connection.execute(
            """SELECT changes.*, listings.address, listings.city, listings.price
            FROM changes JOIN listings ON listings.id = changes.listing_id
            ORDER BY occurred_at DESC LIMIT 30"""
        ).fetchall()
        return [dict(row) for row in rows]


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict | list, status: int = HTTPStatus.OK) -> None:
        # Small helper used by all API routes to return browser-readable JSON.
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        # GET routes provide dashboard data and serve the three browser files.
        path = urlparse(self.path).path
        if path == "/api/listings":
            self.send_json(filtered_listings())
            return
        if path == "/api/changes":
            self.send_json(recent_changes())
            return
        if path == "/":
            content = (ROOT / "templates" / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path == "/static/app.js":
            content = (ROOT / "static" / "app.js").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
        elif path == "/static/style.css":
            content = (ROOT / "static" / "style.css").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        # POST /api/import receives a JSON snapshot from the dashboard's file picker.
        # This is the current manual bridge while we wait for the first real alert email.
        if urlparse(self.path).path != "/api/import":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            # Read the request body, accept either a JSON array or {"listings": [...]} format,
            # then send every record through the same history-aware import function.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            items = payload if isinstance(payload, list) else payload["listings"]
            count = import_listings(items)
            self.send_json({"imported": count})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    # Startup step 1: ensure the local database exists.
    init_db()
    # Startup step 2: create the local web server.
    server_url = f"http://{HOST}:{PORT}"
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Startup step 3: tell the user where the dashboard is and open it in the browser.
    print(f"House Watch running at {server_url}", flush=True)
    print("The dashboard should open automatically. Press Ctrl+C to stop.", flush=True)
    webbrowser.open(server_url)
    try:
        # Startup step 4: keep serving browser requests until Ctrl+C is pressed.
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHouse Watch stopped.", flush=True)
    finally:
        # Startup step 5: release the port cleanly when the app stops.
        server.server_close()
