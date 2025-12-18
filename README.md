API Migration Compatibility Harness

This repository contains a small harness that demonstrates how API v2 breaks legacy v1 consumers and provides a deterministic compatibility mapping that restores legacy-safe responses.

What changed (v1 -> v2)
- customer flat fields (customerId, customerName) became nested: customer { id, name, email }
- totalPrice (float) was replaced by amount { value, currency }
- createdAt changed from YYYY-MM-DD to ISO 8601 timestamp (YYYY-MM-DDTHH:MM:SSZ)
- status renamed to state and introduces new enum values (e.g. FULFILLED)
- items[] renamed/enhanced to lineItems[] (added unitPrice, tax)
- Error format: v1 used {error, message}; v2 uses {errors: [{code, message, field}, ...]}
- /api/v1 may return 410 with API_VERSION_DEPRECATED (should be monitored as DEPRECATED, not OUTAGE)

Compatibility mapping (deterministic rules)
- customer -> customerId, customerName: flatten nested customer dict; missing fields default to empty strings
- amount -> totalPrice: take amount.value as float (fallback to 0.0); currency is ignored (USD assumed)
- createdAt: parse ISO 8601 and emit YYYY-MM-DD (fallback uses prefix or 1970-01-01)
- lineItems -> items: map each lineItem {name, quantity} -> {productName, qty}; drop extra fields; guarantee a non-empty items list by inserting a placeholder if needed
- state -> status: if state is one of legacy enum (PAID, CANCELLED, SHIPPED) keep it; otherwise deterministically downgrade to "PAID"
- trackingNumber: passed through when present
- errors normalization: if v2 returns errors array, take the first element and map {code, message} -> {error, message}

What the tests do
- Mode RAW (MODE=RAW): talks to the service (or canned responses) and verifies that raw v2 responses break legacy assumptions. This mode is expected to PASS (it proves the breakage scenarios are present).
- Mode COMPAT (MODE=COMPAT): runs the same scenarios through the compatibility layer (mapping + normalization) and verifies all legacy expectations are satisfied. This mode must PASS for migration safety.

One-click test runner
- POSIX: ./run_tests.sh
- PowerShell (Windows): ./run_tests.ps1

Both scripts create a virtualenv, install pinned dependencies (requirements.txt + requirements-dev.txt), run RAW then COMPAT phases, and exit non-zero if the required FAIL-then-PASS gate is not satisfied.

Files added
- e2e_api_regression_harness.py: harness + compatibility mapping (implements TODOs)
- requirements.txt / requirements-dev.txt: pinned deps
- run_tests.sh / run_tests.ps1: one-click runners
- README.md: this file

Interpretation of results
- The migration is "safe for legacy consumers" when:
  1) RAW mode demonstrates the listed breaks (proof that v2 diverges), and
  2) COMPAT mode passes all legacy safety checks (compatibility layer correctly restores legacy shape and monitoring semantics).

If either phase fails, the scripts exit non-zero and the migration needs further work.
