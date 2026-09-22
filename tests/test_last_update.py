from __future__ import annotations

import app as house_watch


def test_latest_update_tracks_latest_listing_change(tmp_path):
    db_path = tmp_path / "house_watch.db"
    house_watch.DB_PATH = db_path
    house_watch.init_db()

    house_watch.import_listings([
        {
            "id": "listing-1",
            "address": "123 Main St",
            "city": "Ottawa",
            "province": "ON",
            "price": 420000,
            "bedrooms": 3,
            "bathrooms": 2,
            "property_type": "Detached",
            "leased_land": False,
            "url": "https://example.com/1",
        }
    ])

    status = house_watch.latest_update()
    assert status["last_updated"] is not None
    assert status["last_updated"] == house_watch.recent_changes()[0]["occurred_at"]
