# Security Policy

AFTERHOURS is a trading terminal that, in Phase 6+, operates with live brokerage credentials and executes real orders. Security issues are taken seriously.

## Scope

The following are in scope:

- Authentication bypass on any gateway route (`/api/halt`, `/api/mode`, `/api/decisions/*`, `/ws`)
- Kill-switch bypass — any path where a halted system can still execute a trade
- Audit trail manipulation — any way to execute an action without producing an event
- Credential exposure — API keys, broker tokens, or session tokens leaked via logs, responses, or storage
- Risk engine bypass — any path where a trade can be filled without passing through `RiskEngine.evaluate()`
- Dependency vulnerabilities with a clear exploitation path in this context

The following are out of scope:

- Issues requiring physical access to the machine running the terminal
- Denial-of-service against a local single-user process
- Theoretical vulnerabilities with no practical exploitation path

## Reporting

Do not open a public GitHub issue for a security vulnerability.

Send a report to **smithproductionsdaily@gmail.com** with:

- A description of the vulnerability and affected component
- Steps to reproduce or a proof-of-concept (redact any real credentials)
- Your assessment of impact and severity

You will receive acknowledgement within 72 hours and a resolution timeline once the report is triaged.

## Disclosure

Fixes will be committed to `main` with a patch note. There is no coordinated embargo process for this project given its single-operator nature, but reporters will be credited in the commit message unless they prefer otherwise.
