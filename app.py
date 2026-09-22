from __future__ import annotations

import html
import json  # Reads JSON requests sent by the dashboard and snapshot importer.
import re
import sqlite3  # Stores listings and their change history in a local database.
import webbrowser  # Opens the dashboard automatically when the server starts.
from datetime import datetime, timezone
from email import message_from_bytes, message_from_string
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
    # Every imported record gets one timestamp for this import batch. UTC avoids
    # confusing comparisons if the computer's local timezone changes later.
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
        # IF NOT EXISTS makes this safe to call every time start.py runs: existing
        # listings and history stay untouched, while missing tables are created.
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
    # A single normalized shape means JSON imports and email imports follow the
    # same storage and comparison rules below.
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
    # Process one complete snapshot. The function does not erase older rows;
    # it updates the latest listing state and records meaningful changes separately.
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
                # An existing ID means this property appeared in an earlier import.
                # Updating the row preserves the current price and listing details.
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


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_dollars(value: str) -> int:
    match = re.search(r"(\d[\d,]*?(?:\.\d+)?)", value or "")
    if not match:
        return 0
    cleaned = match.group(1).replace(",", "")
    return int(float(cleaned))


def _extract_property_type(text: str) -> str:
    haystack = text.lower()
    for label in ["detached", "semi-detached", "semi", "townhouse", "condo", "apartment", "row"]:
        if label in haystack:
            return label.title().replace("-", "-") if label not in {"detached", "semi-detached"} else (
                "Detached" if label == "detached" else "Semi-detached"
            )
    return "Detached"


def extract_listings_from_email(raw_email: str | bytes) -> list[dict]:
    """Convert a saved alert email into the same listing shape used by the JSON snapshot importer."""
    # Email bodies can arrive as bytes from a file or as text from an HTTP request.
    # Converting bytes to text lets the same parser handle both entry points.
    if isinstance(raw_email, bytes):
        text = raw_email.decode("utf-8", errors="replace")
    else:
        text = raw_email

    message = message_from_bytes(raw_email if isinstance(raw_email, bytes) else raw_email.encode("utf-8", errors="replace"))

    if message.get_content_maintype() == "multipart":
        # Realtor emails often contain both plain text and HTML alternatives.
        # Prefer HTML because it normally preserves the address and listing links.
        html_body = ""
        plain_body = ""
        for part in message.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    plain_body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        body = html_body or plain_body
    else:
        payload = message.get_payload(decode=True)
        if payload:
            body = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
        else:
            body = text

    source_html = (body or text)
    # Quoted-printable encoding can split URLs across lines or encode characters.
    # Decode those pieces before searching for Realtor listing links.
    source_html = source_html.replace("=3D", "=").replace("=\r\n", "").replace("=\n", "")
    source_html = re.sub(r"=([A-Fa-f0-9]{2})", lambda match: chr(int(match.group(1), 16)), source_html)
    source_html = html.unescape(source_html)

    url_matches = re.findall(r"https?://www\.realtor\.ca/real-estate/[^\s\"'<>]+", source_html, flags=re.IGNORECASE)
    if not url_matches:
        return []

    listings: list[dict] = []
    seen: set[str] = set()

    for url in dict.fromkeys(url_matches):
        # A URL is the most stable identifier available in an alert email. The
        # nearby HTML/text contains the address, price, and property details.
        position = source_html.find(url)
        if position < 0:
            continue

        context_start = max(0, position - 500)
        context_end = min(len(source_html), position + 1800)
        context = source_html[context_start:context_end]

        price_match = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", context, flags=re.IGNORECASE)
        price = int(float(price_match.group(1).replace(",", ""))) if price_match else 0
        if price <= 0:
            continue

        address = None
        span_match = re.search(r"<span[^>]*class=[\"']?autolink[\"']?[^>]*>(.*?)</span>", context, flags=re.IGNORECASE | re.DOTALL)
        if span_match:
            candidate = _clean_text(span_match.group(1))
            if re.search(r"\d", candidate):
                address = candidate

        if not address:
            block_match = re.search(r">\s*([^<>]*\d[^<>]*?)\s*<br\s*/?>\s*([^<>]{4,120})\s*</span>", context, flags=re.IGNORECASE | re.DOTALL)
            if block_match:
                first_line = _clean_text(block_match.group(1))
                second_line = _clean_text(block_match.group(2))
                if first_line and second_line:
                    address = f"{first_line}, {second_line}"

        if not address:
            continue

        bedrooms_match = re.search(r"(\d+)\s*Bedroom\(s\)", context, flags=re.IGNORECASE)
        bathrooms_match = re.search(r"(\d+(?:\.\d+)?)\s*Bathroom\(s\)", context, flags=re.IGNORECASE)
        title_match = re.search(r"(Detached|Semi-Detached|Semi|Townhouse|Condo|Apartment|Row|Bungalow|Duplex)", context, flags=re.IGNORECASE)

        listing = {
            "id": re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-") or f"email-{len(listings) + 1}",
            "address": address,
            "city": "Ottawa",
            "province": "ON",
            "price": price,
            "bedrooms": int(bedrooms_match.group(1)) if bedrooms_match else None,
            "bathrooms": float(bathrooms_match.group(1)) if bathrooms_match else None,
            "property_type": ((title_match.group(1).title() if title_match else "Detached").replace("-", "-")),
            "leased_land": False,
            "url": url,
        }

        key = (listing["address"], listing["price"], listing["url"])
        if key in seen:
            continue
        seen.add(key)
        listings.append(listing)

    return listings


def parse_email_file(path: str | Path) -> list[dict]:
    return extract_listings_from_email(Path(path).read_bytes())


def filtered_listings() -> list[dict]:
    # This is the current search view. It intentionally filters the latest state,
    # while the changes table keeps the complete historical record separately.
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
    # LIMIT keeps the panel readable; older events remain in SQLite.
    with connect() as connection:
        rows = connection.execute(
            """SELECT changes.*, listings.address, listings.city, listings.price
            FROM changes JOIN listings ON listings.id = changes.listing_id
            ORDER BY occurred_at DESC LIMIT 30"""
        ).fetchall()
        return [dict(row) for row in rows]


def latest_update() -> dict:
    """Return the newest import or listing-change timestamp currently stored."""
    with connect() as connection:
        row = connection.execute("SELECT MAX(updated_at) AS last_updated FROM listings").fetchone()
        last_updated = row["last_updated"] if row else None
        if last_updated is None:
            row = connection.execute("SELECT MAX(occurred_at) AS last_updated FROM changes").fetchone()
            last_updated = row["last_updated"] if row else None
        return {"last_updated": last_updated}


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
        # The browser makes three read requests when it opens:
        # listings, change history, and the timestamp of the latest import.
        path = urlparse(self.path).path
        if path == "/api/listings":
            self.send_json(filtered_listings())
            return
        if path == "/api/changes":
            self.send_json(recent_changes())
            return
        if path == "/api/status":
            self.send_json(latest_update())
            return
        if path == "/":
            # HTML is the page shell. JavaScript fills its empty placeholders later.
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
        # These import routes remain available for future integrations, although
        # the normal user workflow imports files through start.py instead.
        path = urlparse(self.path).path
        if path == "/api/import":
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
            return

        if path == "/api/import-email":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                text = raw.decode("utf-8", errors="replace")
                items = extract_listings_from_email(text)
                if not items:
                    raise ValueError("No listings could be extracted from the email payload")
                count = import_listings(items)
                self.send_json({"imported": count})
            except (TypeError, ValueError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    # app.py can also be run directly. It still makes sure the database exists,
    # then creates a local-only server and keeps it alive until Ctrl+C.
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
