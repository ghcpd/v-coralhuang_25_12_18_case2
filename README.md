# API Migration Compatibility Harness (v1 → v2)

This repository contains a minimal, self-contained harness that demonstrates a regression caused by a breaking API migration and the compatibility layer that fixes it. The goal is to prove, via a **FAIL-THEN-PASS** test gate, that raw v2 responses break legacy expectations but a deterministic compatibility mapper can make v2 responses safe for legacy consumers.

---

## What changed between v1 and v2 (summary)

The `v2` API introduced several schema changes compared to the legacy `v1` shape:

1. **Nested customer object**
   - v1: `customerId` (string), `customerName` (string)
   - v2: `customer{id, name, email}`
2. **Amount type change**
   - v1: `totalPrice` (float)
   - v2: `amount{value, currency}`
3. **Date format**
   - v1: `createdAt` `YYYY-MM-DD`
   - v2: `createdAt` ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`
4. **State/enum**
   - v1: `status` enum (fixed set)
   - v2: `state` (new values exist such as `FULFILLED`)
5. **Items**
   - v1: `items[]{productName, qty}`
   - v2: `lineItems[]{name, quantity, unitPrice, tax}` (may be omitted when `includeItems=false`)
6. **Conditional fields**
   - v2 may include `trackingNumber` when `state=SHIPPED` (legacy clients don't expect it)
7. **Error shape**
   - v1: `{error: string, message: string}`
   - v2: `{errors: [{code, message, field}]}`

Legacy clients assumed a strict shape (flat fields, primitives, non-empty arrays) and the `/api/v1/orders` endpoint must return HTTP 200; non-200 is treated as outage.

---

## Why legacy clients broke

Each of the changes above violates an assumption used by legacy clients:
- Missing `items` or `lineItems` means empty or missing array
- `amount` is an object instead of a numeric value
- `createdAt` is a full timestamp instead of `YYYY-MM-DD`
- New enums mean legacy enum validation would fail
- Error responses moved to an array structure
- `v1` deprecation responses (HTTP 410) would be treated as outage by a monitor that only looked at HTTP status

---

## Compatibility mapping strategy (the *adapter / gateway*)

`e2e_api_regression_harness.py` implements a deterministic mapping `v2_to_legacy()` which implements the following rules:
- **State / enum**: `state -> status` and any unknown state is mapped to a safe legacy value (`PAID` in this implementation)
- **Amount**: `amount{value, currency}` -> `totalPrice` numeric (fallback 0.0)
- **Customer**: flatten `customer{id,name,email}` -> `customerId`, `customerName` (email is ignored)
- **Line items**: `lineItems[]{name, quantity, unitPrice, tax}` -> `items[]{productName, qty}` (extra fields dropped)
- **CreatedAt**: ISO8601 -> `YYYY-MM-DD` (split at `T`)
- **TrackingNumber**: passed through if present (legacy clients can ignore it)
- **Items list**: always ensure `items` exists and is non-empty (insert a placeholder item if missing)

Additional helpers implement:
- `classify_v1_deprecation()` — classifies `410 + API_VERSION_DEPRECATED` as `DEPRECATED` rather than `OUTAGE`.
- `normalize_error_response()` — converts v2 `{errors: [...]}` into v1 `{error, message}` using the first array element.

---

## How to run the tests (one-click)

Two modes of the harness are supported:
- **raw mode** (`MODE=raw`) — uses the embedded v2 test vectors and demonstrates legacy-breaking behavior
- **compat mode** (`MODE=compat`) — runs the same requests through the compatibility mapper and should pass all legacy checks

### Run locally (no real API)

```bash
# on *nix
./run_tests.sh

# on Windows PowerShell
.
```un_tests.ps1

The scripts:
- install a small virtualenvtoring pass is expected)
- run the harness in raw mode (expected to **fail**) — this proves the regression- **Compat mode**: all checks should PASS and the script should exit with status 0
- run the harness in compat mode (expected to **pass**) — this proves the adapter fixes the regression
- exit non‑zero if the raw run did not fail or the compat run did not pass (the fail‑then‑pass gate)If you want to use the harness from code you can `import e2e_api_regression_harness` and then call the check functions directly (they return `CheckResult` objects).


































- `README.md` — this file- `requirements.txt` / `requirements-dev.txt` — pinned dependencies (only `requests`, `pytest` for development)- `run_tests.sh` / `run_tests.ps1` — one-click runners for *nix and PowerShell- `e2e_api_regression_harness.py` — test harness and adapter# Files in this repo---If you want to run the tests against a real API, set the `BASE_URL` environment variable (and the harness will make real HTTP calls to that host).---- `request_json()` supports real HTTP calls if `BASE_URL` is set; otherwise it falls back to an embedded offline test vector set.- `items` is guaranteed to be a non-empty list to satisfy legacy UI expectations.- Mapping is intentionally deterministic — unknown `state` values map to `PAID` so legacy clients see a value they expect.## Notes / design choices---If the raw run **does not fail** or the compat run **does not pass**, the runner exits non-zero so CI can block the change.3. The test runner prints `✅ PASS-THEN-PASS gate satisfied: raw failed and compat passed` — this is the concrete acceptance criteria2. **Compat mode**: the harness will produce `PASS` results for all checks and exit with status 0 — this shows the compatibility layer makes v2 responses safe for legacy consumers1. **Raw mode**: the harness will produce multiple `FAIL` results (missing items, nested customer, amount object, etc.) — this is the expected failing case showing the regressionWhen you run `run_tests.sh` or `run_tests.ps1` the following sequence is expected:## What output indicates the migration is safe---