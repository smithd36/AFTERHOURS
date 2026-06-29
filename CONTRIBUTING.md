# Contributing to AFTERHOURS

AFTERHOURS is a single-operator AI trading terminal licensed under the [Elastic License 2.0](LICENSE). It is source-available, not open-source in the traditional sense - the license prohibits offering the software as a managed service. Contributions are welcome within those terms.

---

## Star the Repo

Before contributing in any form - opening an issue, submitting a PR, or requesting a feature - please star the repository on GitHub. It is the simplest way to support the project and helps surface it for others building in the same space.

[github.com/smithd36/AFTERHOURS](https://github.com/smithd36/AFTERHOURS) → Star

---

## Before You Start

Open an issue or comment on an existing one before writing code for anything non-trivial. This project has a strict phase-gated roadmap and a set of non-negotiables around the risk engine, kill switch, and audit trail. A PR that conflicts with those constraints won't land, regardless of quality.

Non-negotiables (from `planning.md §12`):
- The risk engine is the deterministic, authoritative gatekeeper. No LLM output bypasses it.
- The kill switch must always be effective. Pending decisions must not survive a halt.
- Every operator action and every fill must appear in the audit trail.
- Calibration data must not be corrupted by invalid LLM output.
- Position sizing must never exceed what the ledger can actually afford.

---

## Development Setup

**Python backend**

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

**Run tests**

```bash
pytest                          # all tests
pytest tests/unit/              # unit only
pytest -k "watchlist"           # filter by name
```

The test suite must stay green before any PR is opened. The current baseline is 247 passed, 5 skipped.

---

## Code Style

- Python: formatted with `black`, imports sorted with `isort`. Run both before committing.
- TypeScript/React: `eslint` + `prettier` via the frontend config.
- No `# type: ignore` without an inline explanation.
- Two-clock discipline: use `event_time` for all financial logic; `wall_clock` only for I/O and logging. See `planning.md §9`.
- Persist-before-fanout: the bus contract in `core/bus/in_process.py` must be respected by all new event publishers.

---

## Commit Messages

```
<area>: <short imperative summary>

Optional longer explanation of why, not what. Reference the planning.md
section or issue number if the change is non-obvious.
```

Areas: `risk`, `portfolio`, `gateway`, `ingestion`, `reasoning`, `core`, `frontend`, `tests`, `docs`.

---

## Pull Requests

Use the PR template. Every PR must:

1. Have a linked issue (or be a direct fix for a tracked bug).
2. Include tests that cover the changed behavior - especially for anything touching the risk engine, ledger, or executor.
3. Pass the full test suite.
4. Not introduce new `TODO`/`FIXME` markers without an accompanying issue.

For changes to the risk engine, executor, or ledger: add or update regression tests with explicit assertions on the financial math, not just "it didn't raise."

---

## Reporting Issues

Use the issue templates. For security vulnerabilities, see [SECURITY.md](SECURITY.md).
