from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from pipeline.dedup.canon import canonicalize_url, normalize_title
from pipeline.dedup.priority import pick_primary
from pipeline.dedup.simhash import is_near_duplicate, simhash
from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)

FUZZY_TITLE_THRESHOLD = 88
FUZZY_DATE_WINDOW_HOURS = 24
DEFAULT_T3_MAX_HAMMING = 3
DEFAULT_T4_THRESHOLD = 0.60

_METHOD_PRECEDENCE = {
    "singleton": 0,
    "preexisting": 1,
    "t4_semantic": 2,
    "t3_simhash": 3,
    "t2_fuzzy": 4,
    "t1_exact": 5,
}


def _better_method(current: str | None, candidate: str | None) -> str:
    if not current:
        return candidate or ""
    if not candidate:
        return current
    return candidate if _METHOD_PRECEDENCE.get(candidate, 0) > _METHOD_PRECEDENCE.get(current, 0) else current


@dataclass
class DedupResult:
    channel: str
    started_at: str
    finished_at: str
    examined: int
    new_clusters: int
    items_demoted: int
    matched_phase1: int
    matched_phase2: int
    method_counts: dict[str, int] = field(default_factory=dict)
    ok: bool = True
    errors: list[str] = field(default_factory=list)


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_apart(a: str | None, b: str | None) -> float:
    da = _parse_dt(a)
    db = _parse_dt(b)
    if da is None or db is None:
        return float("inf")
    return abs((da - db).total_seconds()) / 3600.0


def _tier1_match(item: dict, candidate: dict) -> bool:
    iu = canonicalize_url(item.get("url") or "")
    cu = canonicalize_url(candidate.get("url") or "")
    if iu and cu and iu == cu:
        return True
    it = normalize_title(item.get("title") or "")
    ct = normalize_title(candidate.get("title") or "")
    if it and ct and it == ct and len(it) >= 8:
        return True
    return False


def _tier2_match(item: dict, candidate: dict) -> bool:
    it = normalize_title(item.get("title") or "")
    ct = normalize_title(candidate.get("title") or "")
    if not it or not ct or len(it) < 8 or len(ct) < 8:
        return False
    if fuzz.token_set_ratio(it, ct) < FUZZY_TITLE_THRESHOLD:
        return False
    if _hours_apart(item.get("date"), candidate.get("date")) > FUZZY_DATE_WINDOW_HOURS:
        return False
    return True


def _tier3_match(item: dict, candidate: dict, sh_cache: dict[str, int], max_hamming: int) -> bool:
    sa = sh_cache.get(item["id"])
    sb = sh_cache.get(candidate["id"])
    if sa is None or sb is None:
        return False
    return is_near_duplicate(sa, sb, max_distance=max_hamming)


def _tier4_match(item: dict, candidate: dict, emb_cache: dict[str, np.ndarray], threshold: float) -> bool:
    va = emb_cache.get(item["id"])
    vb = emb_cache.get(candidate["id"])
    if va is None or vb is None:
        return False
    from pipeline.dedup.semantic import cosine
    return cosine(va, vb) >= threshold


class DedupPipeline:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def run(
        self,
        *,
        window_days: int = 10,
        tiers: tuple[int, ...] = (1, 2, 3, 4),
        t3_max_hamming: int = DEFAULT_T3_MAX_HAMMING,
        t4_threshold: float = DEFAULT_T4_THRESHOLD,
        as_of: "datetime | None" = None,
    ) -> DedupResult:
        started = now_iso()
        errors: list[str] = []
        examined = 0
        new_clusters = 0
        items_demoted = 0
        matched_phase1 = 0
        matched_phase2 = 0
        method_counts: dict[str, int] = {}

        try:
            with ItemStore(self.db_path) as store:
                rows = store.items_in_window(days=window_days, as_of=as_of)
                examined = len(rows)
                items = [_row_to_dict(r) for r in rows]
                items_by_id = {it["id"]: it for it in items}

                sh_cache: dict[str, int] = {}
                if 3 in tiers:
                    for it in items:
                        text = (it.get("title") or "") + "\n" + (it.get("content") or "")
                        sh_cache[it["id"]] = simhash(text)

                emb_cache: dict[str, np.ndarray] = {}
                if 4 in tiers:
                    from pipeline.dedup import semantic
                    needs_embed: list[tuple[str, str]] = []
                    for it in items:
                        blob = it.get("embedding")
                        if blob:
                            emb_cache[it["id"]] = semantic.deserialize(blob)
                        else:
                            needs_embed.append((it["id"], semantic.text_for_embedding(it)))
                    if needs_embed:
                        log.info("T4: encoding %d items lacking cached embeddings", len(needs_embed))
                        ids = [iid for iid, _ in needs_embed]
                        texts = [t for _, t in needs_embed]
                        vecs = semantic.embed_texts(texts)
                        for iid, vec in zip(ids, vecs):
                            emb_cache[iid] = vec
                            store.set_embedding(iid, semantic.serialize(vec))
                        store.commit()

                clusters: dict[str, list[dict]] = {}
                cluster_method: dict[str, str] = {}
                preexisting_cids: set[str] = set()

                for it in items:
                    cid = it.get("cluster_id")
                    if cid:
                        clusters.setdefault(cid, []).append(it)
                        preexisting_cids.add(cid)
                        if cid not in cluster_method:
                            cluster_method[cid] = it.get("cluster_method") or "preexisting"

                unclustered = [it for it in items if not it.get("cluster_id")]
                unclustered.sort(key=lambda r: r.get("date") or r.get("fetched_at") or "")
                seen_in_phase: dict[str, str] = {}

                for item in unclustered:
                    matched_cid: str | None = None
                    matched_method: str | None = None
                    for prior_id, prior_cid in seen_in_phase.items():
                        prior = items_by_id.get(prior_id)
                        if prior is None:
                            continue
                        if 1 in tiers and _tier1_match(item, prior):
                            matched_cid, matched_method = prior_cid, "t1_exact"
                            break
                        if 2 in tiers and _tier2_match(item, prior):
                            matched_cid, matched_method = prior_cid, "t2_fuzzy"
                            break
                        if 3 in tiers and _tier3_match(item, prior, sh_cache, t3_max_hamming):
                            matched_cid, matched_method = prior_cid, "t3_simhash"
                            break
                        if 4 in tiers and _tier4_match(item, prior, emb_cache, t4_threshold):
                            matched_cid, matched_method = prior_cid, "t4_semantic"
                            break

                    if matched_cid is None:
                        matched_cid = str(uuid.uuid4())
                        new_clusters += 1
                        clusters.setdefault(matched_cid, []).append(item)
                        cluster_method[matched_cid] = "singleton"
                    else:
                        clusters.setdefault(matched_cid, []).append(item)
                        if matched_method:
                            cluster_method[matched_cid] = _better_method(cluster_method.get(matched_cid), matched_method)
                        matched_phase1 += 1
                    seen_in_phase[item["id"]] = matched_cid

                fresh_singletons = [
                    cid for cid in clusters
                    if cid not in preexisting_cids and len(clusters[cid]) == 1
                ]
                for cid in fresh_singletons:
                    item = clusters[cid][0]
                    target_cid: str | None = None
                    target_method: str | None = None
                    for ex_cid in preexisting_cids:
                        for cand in clusters.get(ex_cid, []):
                            if 1 in tiers and _tier1_match(item, cand):
                                target_cid, target_method = ex_cid, "t1_exact"
                                break
                            if 2 in tiers and _tier2_match(item, cand):
                                target_cid, target_method = ex_cid, "t2_fuzzy"
                                break
                            if 3 in tiers and _tier3_match(item, cand, sh_cache, t3_max_hamming):
                                target_cid, target_method = ex_cid, "t3_simhash"
                                break
                            if 4 in tiers and _tier4_match(item, cand, emb_cache, t4_threshold):
                                target_cid, target_method = ex_cid, "t4_semantic"
                                break
                        if target_cid:
                            break
                    if target_cid:
                        clusters[target_cid].append(item)
                        clusters.pop(cid, None)
                        cluster_method.pop(cid, None)
                        new_clusters -= 1
                        matched_phase2 += 1
                        if target_method:
                            cluster_method[target_cid] = _better_method(cluster_method.get(target_cid), target_method)

                for cid, members in clusters.items():
                    primary_id = pick_primary(members)
                    method = cluster_method.get(cid) or "singleton"
                    method_counts[method] = method_counts.get(method, 0) + 1
                    for m in members:
                        is_primary = 1 if m["id"] == primary_id else 0
                        if is_primary == 0:
                            items_demoted += 1
                        store.assign_cluster(m["id"], cluster_id=cid, is_primary=is_primary, cluster_method=method)
                store.commit()

        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            log.exception("Dedup run failed")

        finished = now_iso()
        return DedupResult(
            channel="dedup", started_at=started, finished_at=finished,
            examined=examined, new_clusters=new_clusters, items_demoted=items_demoted,
            matched_phase1=matched_phase1, matched_phase2=matched_phase2,
            method_counts=method_counts, ok=not errors, errors=errors,
        )


def _print_result(result: DedupResult) -> None:
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


def _parse_tiers(s: str) -> tuple[int, ...]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            v = int(p)
        except ValueError:
            raise SystemExit(f"Bad --tiers value: {p!r}; expected comma-separated 1..4")
        if v not in (1, 2, 3, 4):
            raise SystemExit(f"Bad tier {v}; valid range is 1..4")
        out.append(v)
    if not out:
        raise SystemExit("--tiers must list at least one tier")
    return tuple(sorted(set(out)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedup pipeline (T1+T2+T3+T4)")
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--tiers", default="1,2,3,4")
    parser.add_argument("--t3-hamming", type=int, default=DEFAULT_T3_MAX_HAMMING)
    parser.add_argument("--t4-threshold", type=float, default=DEFAULT_T4_THRESHOLD)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
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

    pipeline = DedupPipeline(db_path=args.db)
    result = pipeline.run(
        window_days=args.window,
        tiers=_parse_tiers(args.tiers),
        t3_max_hamming=args.t3_hamming,
        t4_threshold=args.t4_threshold,
    )
    _print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
