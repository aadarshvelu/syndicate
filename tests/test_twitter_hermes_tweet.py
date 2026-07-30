from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from pipeline import cli as cli_mod
from pipeline import status as status_mod
from pipeline.ingestion import twitter as twitter_mod
from pipeline.ingestion import twitter_xquik as xquik_mod


def test_fetch_hermes_tweet_account_normalizes_items(monkeypatch):
    monkeypatch.setenv("XQUIK_API_KEY", "xq_test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/x/tweets/search"
        assert request.url.params["q"] == "from:simonw"
        assert request.url.params["queryType"] == "Latest"
        assert request.url.params["replies"] == "exclude"
        assert request.url.params["limit"] == "5"
        since_time = datetime.fromisoformat(request.url.params["sinceTime"])
        expected_since = datetime.now(UTC) - timedelta(days=3650)
        assert abs((since_time - expected_since).total_seconds()) < 5
        assert request.headers["x-api-key"] == "xq_test"
        return httpx.Response(
            200,
            json={
                "tweets": [
                    {
                        "id": "123",
                        "text": "SQLite on the edge is getting interesting",
                        "createdAt": "Sat May 23 08:00:00 +0000 2026",
                        "url": "javascript:alert(1)",
                        "author": {
                            "name": "Simon Willison",
                            "username": "simonw",
                        },
                        "likeCount": 42,
                        "replyCount": False,
                        "retweetCount": 5,
                        "media": [
                            {"mediaUrl": "javascript:alert(1)"},
                            {
                                "mediaUrl": "https://img.example/1.jpg",
                                "url": "https://t.co/example",
                            },
                        ],
                    }
                ],
            },
        )

    async def run() -> list[dict]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="https://xquik.test/api/v1",
            headers=xquik_mod.auth_headers(),
            transport=transport,
        ) as client:
            return await twitter_mod._fetch_hermes_tweet_account(
                client,
                {
                    "id": "simonw",
                    "handle": "simonw",
                    "name": "Simon Willison",
                    "category_hint": "tech_news",
                },
                max_tweets=5,
                lookback_days=3650,
            )

    items = asyncio.run(run())

    assert len(items) == 1
    assert items[0]["source_channel"] == "twitter"
    assert items[0]["source_id"] == "simonw"
    assert items[0]["url"] == "https://x.com/simonw/status/123"
    assert items[0]["author"] == "Simon Willison"
    assert items[0]["date"] == "2026-05-23T08:00:00Z"
    assert items[0]["raw_meta"]["twitter_backend"] == "hermes_tweet"
    assert items[0]["raw_meta"]["author_handle"] == "@simonw"
    assert items[0]["raw_meta"]["public_metrics"] == {
        "likeCount": 42,
        "retweetCount": 5,
    }
    assert items[0]["image_url"] == "https://img.example/1.jpg"


def test_hermes_tweet_item_rejects_records_without_an_id() -> None:
    source = {
        "id": "simonw",
        "handle": "simonw",
        "name": "Simon Willison",
    }

    item = xquik_mod.normalise_tweet(
        {
            "text": "A record without an ID or URL",
            "createdAt": "2026-05-23T08:00:00Z",
        },
        source,
        lookback_days=3650,
    )

    assert item is None


def test_hermes_tweet_item_rejects_replies() -> None:
    source = {
        "id": "simonw",
        "handle": "simonw",
        "name": "Simon Willison",
    }

    item = xquik_mod.normalise_tweet(
        {
            "id": "123",
            "text": "A reply",
            "createdAt": "2026-05-23T08:00:00Z",
            "isReply": True,
        },
        source,
        lookback_days=3650,
    )

    assert item is None


def test_hermes_tweet_request_clamps_limit(monkeypatch) -> None:
    monkeypatch.setenv("XQUIK_API_KEY", "xq_test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "200"
        return httpx.Response(
            200,
            json={"tweets": [], "has_next_page": False, "next_cursor": ""},
        )

    async def run() -> list[dict]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="https://xquik.test/api/v1",
            headers=xquik_mod.auth_headers(),
            transport=transport,
        ) as client:
            return await twitter_mod._fetch_hermes_tweet_account(
                client,
                {
                    "id": "simonw",
                    "handle": "simonw",
                    "name": "Simon Willison",
                },
                max_tweets=500,
                lookback_days=2,
            )

    assert asyncio.run(run()) == []


def test_twitter_backend_rejects_unknown_values(monkeypatch) -> None:
    monkeypatch.setenv("TWITTER_BACKEND", "typo")

    with pytest.raises(RuntimeError) as exc_info:
        twitter_mod._twitter_backend()

    assert str(exc_info.value) == (
        "Unsupported TWITTER_BACKEND='typo'. Use playwright or hermes_tweet."
    )


def test_status_reports_the_selected_twitter_backend(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TWITTER_BACKEND", "hermes-tweet")
    snapshot = status_mod.StatusSnapshot(
        db_path=str(tmp_path / "snapshot.db"),
        db_exists=False,
    )

    status_mod._check_env(snapshot)

    assert snapshot.twitter_backend == "hermes_tweet"
    assert snapshot.env_present["TWITTER_BACKEND"] is True

    monkeypatch.setenv("TWITTER_BACKEND", " ")
    status_mod._check_env(snapshot)

    assert snapshot.twitter_backend == "playwright"
    assert snapshot.env_present["TWITTER_BACKEND"] is False


def test_hermes_tweet_backend_inserts_without_importing_playwright(monkeypatch):
    item = twitter_mod._tweet_to_item(
        "https://x.com/sama/status/1",
        "ship it",
        "2026-05-23T08:00:00Z",
        "Sam Altman",
        {"id": "sama", "handle": "sama", "name": "Sam Altman"},
    )

    class Store:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def insert_items(self, items: list[dict]) -> tuple[int, int]:
            self.items.extend(items)
            return len(items), 0

    async def fake_fetch(client, source, max_tweets, lookback_days):
        assert source["handle"] == "sama"
        assert max_tweets == 3
        assert lookback_days == 2
        return [item]

    store = Store()
    pipeline = twitter_mod.TwitterPipeline.__new__(twitter_mod.TwitterPipeline)
    pipeline._store = store

    monkeypatch.setenv("TWITTER_BACKEND", "xquik")
    monkeypatch.setenv("TWITTER_MAX_TWEETS", "3")
    monkeypatch.setenv("XQUIK_API_KEY", "xq_test")
    monkeypatch.setattr(
        twitter_mod,
        "_load_sources",
        lambda: [{"id": "sama", "handle": "sama", "name": "Sam Altman"}],
    )
    monkeypatch.setattr(twitter_mod, "_fetch_hermes_tweet_account", fake_fetch)

    result = asyncio.run(pipeline._run_async(days=2))

    assert result.ok is True
    assert result.fetched == 1
    assert result.saved == 1
    assert result.failed == 0
    assert store.items == [item]


def test_cli_ingest_twitter_calls_pipeline_run(monkeypatch, tmp_path):
    calls: list[tuple[str | None, int]] = []

    def fake_init(self, db_path=None) -> None:
        self.db_path = db_path

    def fake_run(self, days: int):
        calls.append((self.db_path, days))
        return twitter_mod.TwitterResult(ok=True, fetched=2, saved=2)

    monkeypatch.setattr(twitter_mod.TwitterPipeline, "__init__", fake_init)
    monkeypatch.setattr(twitter_mod.TwitterPipeline, "run", fake_run)

    args = argparse.Namespace(
        cmd="ingest-twitter",
        db=str(tmp_path / "snapshot.db"),
        days=4,
        headless=True,
    )

    result = cli_mod._cmd_ingest_twitter(args)

    assert isinstance(result, twitter_mod.TwitterResult)
    assert result.fetched == 2
    assert calls == [(str(tmp_path / "snapshot.db"), 4)]
    assert os.environ["TWITTER_HEADLESS"] == "true"


def test_cli_missing_xquik_key_keeps_stdout_as_json(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("TWITTER_BACKEND", "hermes_tweet")
    monkeypatch.delenv("XQUIK_API_KEY", raising=False)

    exit_code = cli_mod.main(
        [
            "--db",
            str(tmp_path / "snapshot.db"),
            "ingest-twitter",
            "--days",
            "1",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["result"]["errors"] == [
        "hermes_tweet crash: XQUIK_API_KEY is required when TWITTER_BACKEND=hermes_tweet"
    ]
    assert "Twitter pipeline" in captured.err
