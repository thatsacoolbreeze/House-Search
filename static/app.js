// Format a number as Canadian dollars before showing it on the page.
const money = value => new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 }).format(value);
// Convert an ISO timestamp from SQLite into a readable local date and time.
const dateLabel = value => value ? new Date(value).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

async function loadDashboard() {
  // The page loads data once when it opens. The normal workflow updates the data
  // only when the user runs start.py again.
  // Promise.all makes the three independent requests at the same time.
  const [listingsResponse, changesResponse, statusResponse] = await Promise.all([
    fetch('/api/listings'),
    fetch('/api/changes'),
    fetch('/api/status')
  ]);
  const listings = await listingsResponse.json();
  const changes = await changesResponse.json();
  const status = await statusResponse.json();
  // The server returns the newest 30 changes. From those, count today's new
  // listings and all recent price changes for the summary row.
  const today = new Date().toLocaleDateString('en-CA');
  const newChanges = changes.filter(change => change.kind === 'new' && new Date(change.occurred_at).toLocaleDateString('en-CA') === today);
  const priceChanges = changes.filter(change => change.kind.startsWith('price_'));
  const lastUpdated = status.last_updated || null;

  // IDs connect the JSON values to the matching elements in index.html.
  document.querySelector('#listing-count').textContent = listings.length;
  document.querySelector('#new-count').textContent = newChanges.length;
  document.querySelector('#change-count').textContent = priceChanges.length;
  document.querySelector('#checked-at').textContent = lastUpdated ? dateLabel(lastUpdated) : '—';
  renderListings(listings);
  renderChanges(changes);
}

function renderListings(listings) {
  // Find the empty container that will receive the generated listing cards.
  const target = document.querySelector('#listings');
  if (!listings.length) {
    // Show a friendly message instead of trying to create cards from an empty array.
    target.innerHTML = '<p class="empty">No matching homes in the current snapshot.</p>';
    return;
  }
  // map creates one HTML card per listing; join combines the cards into one string.
  // The URL is opened in a new tab so the dashboard remains available.
  target.innerHTML = listings.map(listing => `
    <article class="listing">
      <div class="listing-main">
        <div class="listing-mark">${listing.bedrooms ?? '·'}<small>BD</small></div>
        <div><h4>${listing.address}</h4><p>${listing.city}, ${listing.province} · ${listing.bathrooms ?? '—'} baths</p></div>
      </div>
      <div class="listing-meta"><strong>${money(listing.price)}</strong>${listing.url ? `<a href="${listing.url}" target="_blank" rel="noreferrer">View listing ↗</a>` : '<span>Imported</span>'}</div>
    </article>`).join('');
}

function renderChanges(changes) {
  // The change history uses the same pattern as the listing renderer above.
  // Each event was created by import_listings when a new home or price change was found.
  const target = document.querySelector('#changes');
  if (!changes.length) {
    target.innerHTML = '<p class="empty">No changes recorded yet.</p>';
    return;
  }
  target.innerHTML = changes.map(change => {
    // Choose the label and color based on the event saved by the Python server.
    const isNew = change.kind === 'new';
    const isDrop = change.kind === 'price_drop';
    const label = isNew ? 'New listing' : isDrop ? 'Price reduced' : 'Price increased';
    const value = isNew ? money(change.new_value) : `${money(change.old_value)} → ${money(change.new_value)}`;
    return `<div class="change"><span class="change-dot ${isNew ? 'new' : isDrop ? 'drop' : 'up'}"></span><div><strong>${label}</strong><p>${change.address}</p><b>${value}</b><time>${dateLabel(change.occurred_at)}</time></div></div>`;
  }).join('');
}

// Manual import buttons were removed so start.py is the one clear import path.
// Calling this at the bottom waits until the page elements above already exist.
loadDashboard();
