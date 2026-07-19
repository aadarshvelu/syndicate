from __future__ import annotations

from datetime import UTC, datetime

from pipeline.storage import ItemStore, now_iso


def _item(item_id: str, source_channel: str, *, date: str | None, fetched_at: str) -> dict:
    return {
        "id": item_id,
        "dedup_key": f"dedup-{item_id}",
        "source_id": f"source-{item_id}",
        "source_channel": source_channel,
        "title": f"Title {item_id}",
        "desp": "",
        "date": date,
        "content": f"Content {item_id}",
        "is_html": False,
        "url": f"https://example.com/{item_id}",
        "author": "Example Author",
        "fetched_at": fetched_at,
        "raw_meta": {},
    }


def _ids(rows: list) -> set[str]:
    return {row["id"] for row in rows}


def test_empty_dates_fall_back_to_fetched_at_across_window_queries(tmp_path) -> None:
    fetched_at = now_iso()
    old_fetched_at = "2020-01-01T00:00:00Z"

    with ItemStore(tmp_path / "snapshot.db") as store:
        saved, skipped = store.insert_items(
            [
                _item("twitter-current", "twitter", date="", fetched_at=fetched_at),
                _item("rss-current", "rss", date="", fetched_at=fetched_at),
                _item("gmail-current", "gmail", date=None, fetched_at=fetched_at),
                _item("rss-old", "rss", date="", fetched_at=old_fetched_at),
            ]
        )
        store.assign_cluster("twitter-current", "cluster-twitter", 1, "url")
        store.assign_cluster("rss-current", "cluster-rss", 1, "url")
        store.assign_cluster("gmail-current", "cluster-gmail", 1, "url")
        store.assign_cluster("rss-old", "cluster-old", 1, "url")
        store.set_enrichment(
            "rss-current",
            teaser="Current teaser",
            summary="Current summary",
            importance=3,
            category="tech_news",
        )
        store.commit()

        expected_current = {"twitter-current", "rss-current", "gmail-current"}
        assert (saved, skipped) == (4, 0)
        assert _ids(store.items_in_window(days=1)) == expected_current
        assert _ids(store.items_clustered_in_window(days=1)) == expected_current
        assert _ids(store.unlinked_twitter_items(days=1)) == {"twitter-current"}
        assert _ids(store.news_items_in_window(days=1)) == {
            "rss-current",
            "gmail-current",
        }
        assert _ids(store.news_primary_items_in_window(days=1)) == {
            "rss-current",
            "gmail-current",
        }
        export_rows = store.enriched_primary_items_for_date(datetime.now(UTC).date())
        assert _ids(export_rows) == {"rss-current"}
