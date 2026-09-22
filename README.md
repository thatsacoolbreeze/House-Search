# House Watch

House Watch is a local Ottawa home-listing monitor. It imports saved listing-alert emails, stores the latest listing state in SQLite, and records new listings and price changes over time. The dashboard runs on your computer at `127.0.0.1`; it does not publish your listing history to the internet.

## Current search

The dashboard currently shows active listings that match all of these rules:

- Ottawa, Ontario
- Detached homes
- Price at or below `$550,000` CAD
- Leased land excluded

The dashboard also shows the 30 most recent history events, including new listings, price reductions, and price increases.

## Requirements

- Windows with Python 3 installed and available through `py -3`
- Saved alert messages in `.eml` format when using the normal import workflow

No third-party Python packages are required. The app uses Python's standard library and SQLite.

## Run the app

From the project folder, use the launcher:

```powershell
py -3 start.py
```

The launcher will:

1. Create `house_watch.db` if it does not exist.
2. Import every `.eml` file in `incoming/`.
3. Stop an older House Watch process using port `8765`.
4. Start the dashboard server.

Open <http://127.0.0.1:8765> if the browser does not open automatically. Press `Ctrl+C` in the terminal to stop the server.

You can also start the server directly with `py -3 app.py`. This starts the dashboard without importing files from `incoming/` first.

## Import alert emails

1. In your email client, save the complete listing alert as an `.eml` file. Saving the original message preserves its HTML and links.
2. Put the file beside the project in the `incoming/` folder, for example:

	```text
	House Watch\incoming\first-alert.eml
	```

3. Run `py -3 start.py` again.

The parser extracts listing links, addresses, prices, bedrooms, bathrooms, and property type from supported Realtor.ca alert emails. Re-importing the same listing updates its current details without duplicating it. A changed price creates a history event, and previously seen listings remain in the database for comparison.

Do not put email passwords, login details, or other secrets in this project. Remove personal information and tracking links from an email before sharing it for parser troubleshooting, while keeping one complete listing card intact.

## JSON test import

The server also exposes a JSON import endpoint for fixtures such as `sample_listings.json`. The payload can be either a listing array or an object with a `listings` array:

```powershell
$body = Get-Content .\sample_listings.json -Raw
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/import -Method Post -ContentType 'application/json' -Body $body
```

Each listing needs an `id` and `price`. Optional fields include `address`, `city`, `province`, `bedrooms`, `bathrooms`, `property_type`, `leased_land`, and `url`.

## Project layout

```text
app.py                 Local HTTP server, parser, database, and API
start.py               Recommended launcher and .eml importer
incoming/              Saved alert emails to import
house_watch.db         Local SQLite database, created at runtime
sample_listings.json   JSON fixture for testing
templates/             Dashboard HTML
static/                Dashboard JavaScript and CSS
test_app.py            Email parser tests
tests/                 Additional application tests
```

## Run tests

```powershell
py -3 -m unittest discover -v
```

House Watch processes alert messages supplied by the user. It does not scrape listing websites; use a permitted alert or provider feed for any production data source.
