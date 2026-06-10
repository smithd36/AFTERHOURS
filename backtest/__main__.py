"""
Backtest CLI.

    python -m backtest                                  # full history, replay LLM
    python -m backtest --from 2026-06-01 --to 2026-06-08
    python -m backtest --db captured.db --llm live      # real LLM calls, recorded
    python -m backtest --mode observe                   # shadow decisions only

`--llm replay` (default) serves recorded responses from the LLM cache —
deterministic and free; prompts without a recorded response are skipped.
`--llm live` calls the configured provider (LLM_PROVIDER) and records
every response into the cache for future replays.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from core.bus.store import SqliteEventStore
from core.db import open_db
from core.logging import configure_logging
from core.schemas.events import AutonomyMode, EventEnvelope
from reasoning.llm import CachingProvider, JsonFileLLMCache, LLMSettings, create_provider

from .runner import SOURCE_TOPICS, BacktestRunner, write_artifact


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backtest", description=__doc__)
    parser.add_argument("--db", default="afterhours.db", help="source event database")
    parser.add_argument("--from", dest="start", type=_parse_ts, default=None,
                        help="window start (ISO date/datetime, UTC)")
    parser.add_argument("--to", dest="end", type=_parse_ts, default=None,
                        help="window end (ISO date/datetime, UTC)")
    parser.add_argument("--llm", choices=("replay", "live"), default="replay",
                        help="replay = recorded responses only (default); live = call provider + record")
    parser.add_argument("--mode", choices=("paper", "observe"), default="paper",
                        help="autonomy mode under test (default: paper)")
    parser.add_argument("--out", default="backtest_runs", help="artifact output directory")
    return parser


async def _load_source_events(
    db_path: str, start: datetime | None, end: datetime | None
) -> list[EventEnvelope]:
    conn = await open_db(db_path)
    try:
        return await SqliteEventStore(conn).range(list(SOURCE_TOPICS), start, end)
    finally:
        await conn.close()


async def _run(args: argparse.Namespace) -> int:
    events = await _load_source_events(args.db, args.start, args.end)
    if not events:
        print(f"No source events found in {args.db} for the given window.")
        return 1

    llm_settings = LLMSettings()
    cache = JsonFileLLMCache(llm_settings.cache_path)
    inner = create_provider(llm_settings) if args.llm == "live" else None
    provider = CachingProvider(cache, inner=inner)

    runner = BacktestRunner(
        source_events=events,
        provider=provider,
        mode=AutonomyMode(args.mode),
    )
    report = await runner.run()
    report["source_db"] = args.db
    report["llm_mode"] = args.llm
    report["llm_cache"] = {"hits": provider.hits, "misses": provider.misses}
    path = write_artifact(report, args.out)

    calib = report["calibration"]["overall"]
    print(f"\nBacktest complete — {path}")
    print(f"  window     {report['window']['from']} → {report['window']['to']}")
    print(f"  replayed   {report['replayed']}")
    print(f"  generated  {report['generated']}")
    print(f"  llm cache  {provider.hits} hits / {provider.misses} misses")
    print(f"  calibration n={calib['n']} ece={calib['ece']}")
    print(f"  unresolved {report['unresolved_decisions']}")
    print(f"  portfolio  total={report['portfolio']['total_value']} "
          f"cash={report['portfolio']['cash']}")
    return 0


def main() -> int:
    configure_logging()
    args = _build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
