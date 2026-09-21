// Format a number as Canadian dollars before showing it on the page.
const money = value => new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 }).format(value);
// Convert an ISO timestamp from SQLite into a readable local date and time.
const dateLabel = value => value ? new Date(value).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

async function loadDashboard() {
  // Ask the Python server for the two datasets the dashboard needs.
  // Promise.all sends both requests together instead of waiting for one before starting the other.
  const [listingsResponse, changesResponse] = await Promise.all([fetch('/api/listings'), fetch('/api/changes')]);
  // Convert each HTTP response from JSON text into a JavaScript array.
  const listings = await listingsResponse.json();
  const changes = await changesResponse.json();
  // Separate change events so the summary counters can show useful totals.
  const newChanges = changes.filter(change => change.kind === 'new');
  const priceChanges = changes.filter(change => change.kind.startsWith('price_'));

  // Put the summary values into the matching HTML elements using their IDs.
  document.querySelector('#listing-count').textContent = listings.length;
  document.querySelector('#new-count').textContent = newChanges.length;
  document.querySelector('#change-count').textContent = priceChanges.length;
  document.querySelector('#checked-at').textContent = new Date().toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit' });
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

// Clicking the visible button opens the hidden file picker.
document.querySelector('#import-button').addEventListener('click', () => document.querySelector('#file-input').click());
document.querySelector('#file-input').addEventListener('change', async event => {
  // Stop if the user opened the picker but cancelled without choosing a file.
  const file = event.target.files[0];
  if (!file) return;
  // Read the selected JSON file as text and send it to POST /api/import.
  const payload = await file.text();
  const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload });
  if (!response.ok) alert('The import could not be read. Check the JSON format.');
  await loadDashboard();
  event.target.value = '';
});

// Load saved data as soon as the page finishes loading.
loadDashboard();
