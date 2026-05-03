from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

from pipeline.dedup.runner import DEFAULT_T3_MAX_HAMMING, DEFAULT_T4_THRESHOLD, DedupPipeline
from pipeline.ingestion.gmail import GmailPipeline
from pipeline.ingestion.rss import RssPipeline
from pipeline.storage import DEFAULT_DB_PATH, ItemStore

log = logging.getLogger(__name__)

_DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _item_day(item: dict) -> str | None:
    raw = item.get("date") or item.get("fetched_at") or ""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        return None


def _wipe_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM items")
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('runs')")
    conn.commit()
    conn.close()
    log.info("DB wiped: %s", db_path)


def _parse_tiers(s: str) -> tuple[int, ...]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            v = int(p)
        except ValueError:
            raise SystemExit(f"Bad --tiers value: {p!r}")
        if v not in (1, 2, 3, 4):
            raise SystemExit(f"Bad tier {v}; valid 1..4")
        out.append(v)
    if not out:
        raise SystemExit("--tiers must list at least one tier")
    return tuple(sorted(set(out)))


def _fmt_ms(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _collect_all(
    *,
    db_path: Path,
    fetch_days: int,
    skip_gmail: bool,
    skip_rss: bool,
    gmail_folder: str,
    rss_do_fetch: bool,
) -> list[dict]:
    items: list[dict] = []
    if not skip_gmail:
        log.info("Collecting Gmail (days=%d)...", fetch_days)
        t0 = time.perf_counter()
        gmail_items = GmailPipeline(db_path=db_path).collect(days=fetch_days, folder=gmail_folder)
        log.info("Gmail: %d items in %.1fs", len(gmail_items), time.perf_counter() - t0)
        items.extend(gmail_items)
    if not skip_rss:
        log.info("Collecting RSS (days=%d)...", fetch_days)
        t0 = time.perf_counter()
        rss_items = RssPipeline(db_path=db_path).collect(days=fetch_days, do_fetch=rss_do_fetch)
        log.info("RSS: %d items in %.1fs", len(rss_items), time.perf_counter() - t0)
        items.extend(rss_items)
    return items


def simulate(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    fetch_days: int = 30,
    dedup_window: int = 10,
    skip_gmail: bool = False,
    skip_rss: bool = False,
    gmail_folder: str = "INBOX",
    rss_do_fetch: bool = True,
    tiers: tuple[int, ...] = (1, 2, 3, 4),
    t3_max_hamming: int = DEFAULT_T3_MAX_HAMMING,
    t4_threshold: float = DEFAULT_T4_THRESHOLD,
) -> None:
    sim_wall_start = time.perf_counter()

    all_items = _collect_all(
        db_path=db_path, fetch_days=fetch_days, skip_gmail=skip_gmail,
        skip_rss=skip_rss, gmail_folder=gmail_folder, rss_do_fetch=rss_do_fetch,
    )
    log.info("Total collected: %d items", len(all_items))

    today = date.today()
    today_str = today.isoformat()
    items_by_day: dict[str, list[dict]] = defaultdict(list)
    undated = 0
    for item in all_items:
        day = _item_day(item)
        if day:
            items_by_day[day].append(item)
        else:
            items_by_day[today_str].append(item)
            undated += 1
    if undated:
        log.warning("%d undated items assigned to %s", undated, today_str)

    start = today - timedelta(days=fetch_days - 1)
    num_days = (today - start).days + 1
    sim_days = [start + timedelta(days=i) for i in range(num_days)]
    gmail_n = sum(1 for i in all_items if i.get("source_channel") == "gmail")
    rss_n = sum(1 for i in all_items if i.get("source_channel") == "rss")
    print(f"\nSimulation: {sim_days[0]} -> {sim_days[-1]}  ({len(sim_days)} days)")
    print(f"Collected:  {len(all_items)} items  (gmail={gmail_n}  rss={rss_n})")
    print(f"Tiers: T{',T'.join(str(t) for t in tiers)}  dedup_window={dedup_window}d\n")

    _wipe_db(db_path)

    col = "{:<12} {:>4} {:>3} {:>3} {:>6} {:>5} {:>6} {:>4} {:>7}  {}"
    hdr = col.format("Date", "New", "G", "R", "Saved", "Skip", "Clust", "Dem", "Time", "Methods")
    print(hdr)
    print("-" * len(hdr))

    day_stats: list[dict] = []

    for sim_day in sim_days:
        day_str = sim_day.isoformat()
        day_items = items_by_day.get(day_str, [])
        day_gmail = sum(1 for it in day_items if it.get("source_channel") == "gmail")
        day_rss = sum(1 for it in day_items if it.get("source_channel") == "rss")

        t_day = time.perf_counter()

        saved = skipped = 0
        if day_items:
            with ItemStore(db_path) as store:
                saved, skipped = store.insert_items(day_items)

        t_insert = time.perf_counter()

        as_of = datetime.combine(sim_day, dtime.max, tzinfo=timezone.utc)
        dedup = DedupPipeline(db_path=db_path).run(
            window_days=dedup_window, tiers=tiers,
            t3_max_hamming=t3_max_hamming, t4_threshold=t4_threshold, as_of=as_of,
        )

        t_done = time.perf_counter()
        insert_ms = (t_insert - t_day) * 1000
        dedup_ms = (t_done - t_insert) * 1000
        total_ms = (t_done - t_day) * 1000

        methods_str = " ".join(f"{k}:{v}" for k, v in sorted(dedup.method_counts.items())) or "-"

        print(col.format(
            day_str, len(day_items), day_gmail, day_rss,
            saved, skipped, dedup.new_clusters, dedup.items_demoted,
            _fmt_ms(total_ms), methods_str,
        ))

        day_stats.append({
            "day": day_str, "weekday": sim_day.weekday(),
            "new_gmail": day_gmail, "new_rss": day_rss, "new_total": len(day_items),
            "saved": saved, "skipped": skipped,
            "insert_ms": insert_ms, "dedup_ms": dedup_ms, "total_ms": total_ms,
            "dedup": asdict(dedup),
        })

    total_wall_ms = (time.perf_counter() - sim_wall_start) * 1000
    print(f"\nTotal wall time: {_fmt_ms(total_wall_ms)}")

    _print_quality_report(db_path, day_stats, tiers)


def _print_quality_report(db_path: Path, day_stats: list[dict], tiers: tuple[int, ...]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    total_primary = conn.execute("SELECT COUNT(*) FROM items WHERE is_primary=1").fetchone()[0]
    total_demoted = total - total_primary
    total_clusters = conn.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM items WHERE cluster_id IS NOT NULL"
    ).fetchone()[0]
    cross_clusters = conn.execute("""
        SELECT COUNT(DISTINCT cluster_id) FROM (
          SELECT cluster_id FROM items WHERE cluster_id IS NOT NULL
          GROUP BY cluster_id HAVING COUNT(DISTINCT source_channel) > 1
        )
    """).fetchone()[0]
    empty_days = sum(1 for d in day_stats if d["new_total"] == 0)
    dedup_rate = total_demoted / total * 100 if total else 0.0

    size_rows = conn.execute("""
        SELECT members, COUNT(*) as n FROM (
          SELECT cluster_id, COUNT(*) as members FROM items
          WHERE cluster_id IS NOT NULL GROUP BY cluster_id
        ) GROUP BY members ORDER BY members
    """).fetchall()

    method_cluster_rows = conn.execute("""
        SELECT cluster_method, COUNT(DISTINCT cluster_id) as clusters,
               SUM(CASE WHEN is_primary=0 THEN 1 ELSE 0 END) as demoted_items
        FROM items WHERE cluster_id IS NOT NULL
        GROUP BY cluster_method ORDER BY demoted_items DESC
    """).fetchall()

    source_rows = conn.execute("""
        SELECT source_channel, source_id, COUNT(*) as n,
               SUM(CASE WHEN is_primary=1 THEN 1 ELSE 0 END) as primaries,
               SUM(CASE WHEN is_primary=0 THEN 1 ELSE 0 END) as dupes,
               MIN(date) as first_date, MAX(date) as last_date
        FROM items
        GROUP BY source_channel, source_id ORDER BY source_channel, n DESC
    """).fetchall()

    pair_rows = conn.execute("""
        SELECT a.source_id as src_a, b.source_id as src_b,
               COUNT(DISTINCT a.cluster_id) as shared
        FROM items a
        JOIN items b ON a.cluster_id = b.cluster_id
          AND a.source_id < b.source_id
          AND a.cluster_id IS NOT NULL
        GROUP BY src_a, src_b ORDER BY shared DESC LIMIT 12
    """).fetchall()

    dow_counts: dict[int, list[int]] = defaultdict(list)
    for d in day_stats:
        dow_counts[d["weekday"]].append(d["new_total"])
    dow_avgs = {wd: sum(v) / len(v) for wd, v in dow_counts.items()}

    conn.close()

    W = 62
    print("\n" + "=" * W)
    print("QUALITY REPORT")
    print("=" * W)
    print(f"Items ingested:       {total}")
    print(f"Unique clusters:      {total_clusters}")
    print(f"Primary (survived):   {total_primary}  ({total_primary/total*100:.1f}%)" if total else "")
    print(f"Demoted (duplicates): {total_demoted}  ({dedup_rate:.1f}%)")
    print(f"Cross-channel dupes:  {cross_clusters} clusters (rss + gmail overlap)")
    print(f"Empty days:           {empty_days} / {len(day_stats)}")

    total_wall = sum(d["total_ms"] for d in day_stats)
    total_dedup_ms = sum(d["dedup_ms"] for d in day_stats)
    total_insert_ms = sum(d["insert_ms"] for d in day_stats)
    avg_dedup_ms = total_dedup_ms / len(day_stats) if day_stats else 0
    slowest = max(day_stats, key=lambda d: d["dedup_ms"]) if day_stats else None
    print(f"\n--- Timing ---")
    print(f"Total sim time:       {_fmt_ms(total_wall)}")
    print(f"  Insert (total):     {_fmt_ms(total_insert_ms)}")
    print(f"  Dedup  (total):     {_fmt_ms(total_dedup_ms)}  avg/day={_fmt_ms(avg_dedup_ms)}")
    if slowest:
        print(f"  Slowest dedup day:  {slowest['day']} ({_fmt_ms(slowest['dedup_ms'])})")

    print(f"\n--- Cluster size distribution ---")
    print(f"  {'Size':>4}  {'Clusters':>8}  {'Items':>6}  Bar")
    max_c = max((r["n"] for r in size_rows), default=1)
    for row in size_rows:
        bar = "#" * max(1, int(row["n"] / max_c * 20))
        items_in_bucket = row["members"] * row["n"]
        print(f"  {row['members']:>4}  {row['n']:>8}  {items_in_bucket:>6}  {bar}")

    print(f"\n--- Tier effectiveness  (tiers active: T{',T'.join(str(t) for t in tiers)}) ---")
    print(f"  {'Method':<20}  {'Clusters':>8}  {'Demoted items':>13}  {'Items elim %':>12}")
    for row in method_cluster_rows:
        method = row["cluster_method"] or "none"
        pct = row["demoted_items"] / total_demoted * 100 if total_demoted else 0
        bar = "#" * int(pct / 5)
        print(f"  {method:<20}  {row['clusters']:>8}  {row['demoted_items']:>13}  {pct:>11.1f}%  {bar}")

    print(f"\n--- Source overview ---")
    print(f"  {'[ch] source':<32}  {'Items':>5}  {'Primary':>7}  {'Dupes':>5}  {'Dup%':>5}  Coverage")
    for row in source_rows:
        dup_pct = row["dupes"] / row["n"] * 100 if row["n"] else 0
        first = (row["first_date"] or "")[:10]
        last = (row["last_date"] or "")[:10]
        coverage = f"{first} -> {last}" if first else "—"
        label = f"[{row['source_channel']}] {row['source_id']}"
        print(f"  {label:<32}  {row['n']:>5}  {row['primaries']:>7}  {row['dupes']:>5}  {dup_pct:>4.0f}%  {coverage}")

    if pair_rows:
        print(f"\n--- Source-pair overlap (shared clusters) ---")
        for row in pair_rows:
            print(f"  {row['src_a']:<25}  x  {row['src_b']:<25}  -> {row['shared']} shared")

    print(f"\n--- Day-of-week ingestion pattern ---")
    max_avg = max(dow_avgs.values(), default=1)
    for wd in range(7):
        avg = dow_avgs.get(wd, 0)
        bar = "#" * int(avg / max_avg * 20)
        print(f"  {_DAYS_OF_WEEK[wd]}  {avg:5.1f} avg/day  {bar}")

    print(f"\n--- Dedup rate trend (examined vs demoted per day's dedup run) ---")
    print(f"  {'Date':<12}  {'Examined':>8}  {'Demoted':>7}  {'Rate%':>6}  {'P1/P2':>8}  Bar")
    for d in day_stats:
        dd = d["dedup"]
        examined = dd["examined"]
        demoted = dd["items_demoted"]
        rate = demoted / examined * 100 if examined else 0
        p1p2 = f"{dd['matched_phase1']}/{dd['matched_phase2']}"
        bar = "#" * int(rate / 5)
        print(f"  {d['day']:<12}  {examined:>8}  {demoted:>7}  {rate:>5.1f}%  {p1p2:>8}  {bar}")

    totals_by_day = [d["new_total"] for d in day_stats]
    if totals_by_day:
        max_v = max(totals_by_day) or 1
        bars = "".join(_spark(v, max_v) for v in totals_by_day)
        print(f"\nIngestion sparkline ({day_stats[0]['day']} -> {day_stats[-1]['day']}):")
        print(f"  {bars}  max={max_v}")


def _spark(v: int, max_v: int) -> str:
    chars = " ▁▂▃▄▅▆▇█"
    return chars[int(v / max_v * (len(chars) - 1))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Day-by-day pipeline simulation")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--fetch-days", type=int, default=30)
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--skip-gmail", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--folder", default="INBOX")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--tiers", default="1,2,3,4")
    parser.add_argument("--t3-hamming", type=int, default=DEFAULT_T3_MAX_HAMMING)
    parser.add_argument("--t4-threshold", type=float, default=DEFAULT_T4_THRESHOLD)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stderr,
    )

    if not args.confirm:
        print("ERROR: --confirm required. This will wipe the DB and replay from scratch.", file=sys.stderr)
        return 2

    simulate(
        db_path=Path(args.db), fetch_days=args.fetch_days, dedup_window=args.window,
        skip_gmail=args.skip_gmail, skip_rss=args.skip_rss,
        gmail_folder=args.folder, rss_do_fetch=not args.no_fetch,
        tiers=_parse_tiers(args.tiers), t3_max_hamming=args.t3_hamming, t4_threshold=args.t4_threshold,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
