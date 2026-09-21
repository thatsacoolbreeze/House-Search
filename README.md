# House Watch

A local Ottawa home-listing monitor. The first version uses JSON snapshots so it can track real changes without scraping a site whose terms prohibit automated collection.

The program is intentionally split into two stages:

1. **Collect:** obtain listing information through a permitted source. Today this is a JSON snapshot; the next collector will read your alert email.
2. **Compare:** send the listings through `import_listings()` in `app.py`. SQLite remembers what was seen before and records new listings and price changes.

## Current search

- Ottawa, Ontario
- Detached homes
- Price at or below $550,000 CAD
- Leased land excluded
- New listings and price changes recorded in SQLite

## Run

From this folder:

```powershell
py -3 app.py
```

Open http://127.0.0.1:8765 in your browser.

Click **Import snapshot** and select `sample_listings.json`. Import it again after changing a listing price to see a price-change event.

## When the first email arrives

Do not send passwords or email login information. First, save one complete alert email so its real structure can be inspected:

1. Open the listing alert email.
2. Use your email program's **Save as** or **Download message** option and save it as an `.eml` file. Saving the original message is better than copying visible text because it preserves links and headers.
3. Create an `incoming` folder beside `app.py` and place the file there:

```text
House Watch\incoming\first-alert.eml
```

4. Open the `.eml` file in a text editor and remove your name, email address, tracking links, or other personal information if necessary. Keep the listing cards, prices, addresses, IDs, and listing URLs intact.
5. Share the sanitized email file or its relevant contents in the coding session. The important parts are the subject, one complete listing card, and any text that identifies a price change.

After the first email is available, the next implementation steps are:

1. Inspect the email's HTML/text structure and identify stable listing fields.
2. Add an `.eml` parser that extracts each listing into the existing normalized format.
3. Reuse `import_listings()` so the existing database automatically detects new listings and price changes.
4. Add an **Import email** button to the dashboard for testing.
5. Test repeated imports, price reductions, price increases, removed listings, and duplicate emails.
6. Only after manual email import works, connect automatic mailbox reading using Gmail OAuth or Outlook OAuth. Credentials stay on your computer and are never placed in source code.

The first email is needed before writing the parser because email providers use different HTML layouts. Building selectors before seeing the actual message would make the importer unnecessarily fragile.

## Snapshot format

The importer accepts a JSON array, or an object with a `listings` array. Each listing needs an `id` and `price`; the other fields are shown above in `sample_listings.json`.

The current JSON importer is a safe test adapter. The next integration is the permitted alert-email importer described above. Do not scrape the listing website; process only alert messages delivered to your own mailbox.
