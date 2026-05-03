"""Side-by-side benchmark of embedding models for semantic dedup of news.

Two models in scope by default:
  - Qwen/Qwen3-Embedding-0.6B   (Apache-2.0, ~1.2 GB)
  - google/embeddinggemma-300m  (Gemma license, ~600 MB, gated; needs HF auth)

Each model is loaded, every pair from `test_pairs.json` is embedded twice,
cosine similarity computed, and a comparison table emitted.

Usage:
  uv run --group benchmark python -m benchmark.run_bench
  uv run --group benchmark python -m benchmark.run_bench --models qwen
  uv run --group benchmark python -m benchmark.run_bench --models qwen,gemma --pairs benchmark/test_pairs.json
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[1] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

log = logging.getLogger(__name__)

DEFAULT_PAIRS = Path("benchmark") / "test_pairs.json"
DEFAULT_OUT = Path("benchmark") / "results.md"

import os
MODELS = {
    "qwen": {
        "repo": os.environ.get("OLLAMA_MODEL_QWEN_EMBEDDING", "qwen3-embedding:latest"),
        "params": "600M",
        "disk_mb": 1200,
        "license": "Apache-2.0",
        "needs_auth": False,
    },
    "gemma": {
        "repo": os.environ.get("OLLAMA_MODEL_GEMMA_EMBEDDING", "embeddinggemma:latest"),
        "params": "308M",
        "disk_mb": 600,
        "license": "Gemma",
        "needs_auth": False,
    },
}


@dataclass
class PairResult:
    pair_id: str
    kind: str
    expected: str
    cosine: float
    embed_ms_a: float
    embed_ms_b: float


@dataclass
class ModelResult:
    name: str
    repo: str
    load_ms: float
    pairs: list[PairResult] = field(default_factory=list)
    error: str = ""

    @property
    def avg_embed_ms(self) -> float:
        if not self.pairs:
            return 0.0
        all_ms = [p.embed_ms_a for p in self.pairs] + [p.embed_ms_b for p in self.pairs]
        return sum(all_ms) / len(all_ms)


def _embed_one(model_name: str, url: str, text: str) -> tuple[list[float], float]:
    import httpx
    import math
    t0 = time.perf_counter()
    resp = httpx.post(f"{url}/api/embed", json={"model": model_name, "input": [text]}, timeout=60.0)
    resp.raise_for_status()
    data = resp.json()
    vec = data.get("embeddings", [[]])[0]
    norm = math.sqrt(sum(x * x for x in vec))
    vec = [x / norm for x in vec] if norm > 0 else vec
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return vec, elapsed_ms


def _cosine_unit(a: list[float], b: list[float]) -> float:
    # Both already unit-normalized → cosine == dot product.
    return float(sum(x * y for x, y in zip(a, b)))


def run_model(name: str, repo: str, pairs: list[dict]) -> ModelResult:
    import httpx
    import os
    url = (os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    log.info("Benchmarking %s (Ollama model: %s) via %s", name, repo, url)
    
    t0 = time.perf_counter()
    try:
        resp = httpx.post(f"{url}/api/embed", json={"model": repo, "input": ["ok"]}, timeout=60.0)
        resp.raise_for_status()
    except Exception as exc:
        return ModelResult(
            name=name, repo=repo, load_ms=0.0, error=f"Ollama load/ping failed: {exc}"
        )
    load_ms = (time.perf_counter() - t0) * 1000
    log.info("%s ok in %.0f ms", name, load_ms)

    result = ModelResult(name=name, repo=repo, load_ms=load_ms)
    for p in pairs:
        try:
            vec_a, ms_a = _embed_one(repo, url, p["a"])
            vec_b, ms_b = _embed_one(repo, url, p["b"])
            cos = _cosine_unit(vec_a, vec_b)
            result.pairs.append(
                PairResult(
                    pair_id=p["id"],
                    kind=p["kind"],
                    expected=p.get("expected", ""),
                    cosine=cos,
                    embed_ms_a=ms_a,
                    embed_ms_b=ms_b,
                )
            )
        except Exception as exc:
            log.exception("pair %s failed", p["id"])
            result.pairs.append(
                PairResult(
                    pair_id=p["id"],
                    kind=p["kind"],
                    expected=p.get("expected", ""),
                    cosine=float("nan"),
                    embed_ms_a=0.0,
                    embed_ms_b=0.0,
                )
            )

    return result


def render_markdown(model_results: list[ModelResult], pairs: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Embedding model benchmark — news dedup\n")
    lines.append(f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}_\n")

    # Summary table
    lines.append("## Models\n")
    lines.append("| Name | Repo | Params | Disk | License | Load (ms) | Avg embed (ms) |")
    lines.append("|------|------|--------|------|---------|-----------|----------------|")
    for r in model_results:
        info = MODELS.get(r.name, {})
        if r.error:
            lines.append(
                f"| {r.name} | {r.repo} | {info.get('params','?')} | {info.get('disk_mb','?')} MB | "
                f"{info.get('license','?')} | FAIL | FAIL |"
            )
        else:
            lines.append(
                f"| {r.name} | {r.repo} | {info.get('params','?')} | {info.get('disk_mb','?')} MB | "
                f"{info.get('license','?')} | {r.load_ms:.0f} | {r.avg_embed_ms:.1f} |"
            )
    lines.append("")

    # Errors
    for r in model_results:
        if r.error:
            lines.append(f"### Error: {r.name}\n```\n{r.error}\n```\n")

    # Per-pair scores
    ok_results = [r for r in model_results if not r.error]
    if ok_results:
        lines.append("## Per-pair cosine similarity\n")
        header = "| Pair | Kind | Expected | " + " | ".join(r.name for r in ok_results) + " |"
        sep = "|------|------|----------|" + "|".join(["----"] * len(ok_results)) + "|"
        lines.append(header)
        lines.append(sep)
        for p in pairs:
            row = [p["id"], p["kind"], p.get("expected", "")]
            for r in ok_results:
                rec = next((rp for rp in r.pairs if rp.pair_id == p["id"]), None)
                if rec is None or rec.cosine != rec.cosine:  # NaN check
                    row.append("—")
                else:
                    row.append(f"{rec.cosine:.3f}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Bucket means
        lines.append("## Mean cosine by pair kind\n")
        bucket_header = "| Kind | " + " | ".join(r.name for r in ok_results) + " |"
        bucket_sep = "|------|" + "|".join(["----"] * len(ok_results)) + "|"
        lines.append(bucket_header)
        lines.append(bucket_sep)
        kinds = sorted({p["kind"] for p in pairs})
        for kind in kinds:
            row = [kind]
            for r in ok_results:
                vals = [
                    rp.cosine
                    for rp in r.pairs
                    if rp.kind == kind and rp.cosine == rp.cosine
                ]
                row.append(f"{sum(vals)/len(vals):.3f}" if vals else "—")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Pair texts (so reader can sanity-check what scored what)
        lines.append("## Pair texts (for reference)\n")
        for p in pairs:
            lines.append(f"**{p['id']}** ({p['kind']}, expected={p.get('expected', '')})")
            lines.append(f"- A: {p['a']}")
            lines.append(f"- B: {p['b']}")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding model benchmark")
    parser.add_argument(
        "--models",
        default="qwen,gemma",
        help="Comma-separated subset of: " + ",".join(MODELS.keys()),
    )
    parser.add_argument("--pairs", default=str(DEFAULT_PAIRS), help="Path to test pairs JSON")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output Markdown path")
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

    pairs_path = Path(args.pairs)
    pairs = json.loads(pairs_path.read_text(encoding="utf-8")).get("pairs", [])
    log.info("Loaded %d test pairs from %s", len(pairs), pairs_path)

    requested = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in requested if m not in MODELS]
    if unknown:
        log.error("Unknown models: %s. Known: %s", unknown, list(MODELS.keys()))
        return 2

    results: list[ModelResult] = []
    for name in requested:
        info = MODELS[name]
        results.append(run_model(name, info["repo"], pairs))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md = render_markdown(results, pairs)
    out_path.write_text(md, encoding="utf-8")
    log.info("Wrote %s", out_path)

    # Also print summary to stdout
    print("\n" + "=" * 80)
    for r in results:
        if r.error:
            print(f"[{r.name}] ERROR: {r.error}")
        else:
            print(
                f"[{r.name}] load={r.load_ms:.0f}ms  avg_embed={r.avg_embed_ms:.1f}ms  pairs={len(r.pairs)}"
            )
    print("=" * 80)
    print(f"Full results: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
