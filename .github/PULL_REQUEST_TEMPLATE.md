## Summary

<!-- What does this PR do and why? Link the issue it closes. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] Feature / enhancement
- [ ] Refactor (no behavior change)
- [ ] Tests only
- [ ] Docs / config

## Checklist

- [ ] I have starred the [AFTERHOURS repository](https://github.com/smithd36/AFTERHOURS) ★
- [ ] Tests added or updated for the changed behavior
- [ ] Full test suite passes (`pytest`)
- [ ] No new `TODO`/`FIXME` without a linked issue

### If this touches the risk engine, executor, or ledger

- [ ] Regression tests assert on financial math (not just "no exception")
- [ ] Two-clock discipline respected (`event_time` for financial logic, wall clock only for I/O)
- [ ] Kill switch still effective — pending decisions cannot survive a halt
- [ ] Every operator action and fill still produces an audit event
- [ ] No LLM output reaches the ledger without passing through the risk engine

## Testing notes

<!-- How did you verify this? Include pytest output or manual steps. -->
