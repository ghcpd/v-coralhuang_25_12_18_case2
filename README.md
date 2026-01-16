# API Migration Compatibility Layer (v2 → legacy)

## What changed (v1 → v2)
- customer flat fields (`customerId`, `customerName`) became nested: `customer: {id, name, email}`
- `totalPrice` (float) became `amount: {value, currency}`
- `createdAt` was upgraded from `YYYY-MM-DD` to ISO 8601 timestamps `YYYY-MM-DDTHH:MM:SSZ`
- `status` was renamed `state` and new enum values may appear (e.g., `FULFILLED`)
- `items[]` became `lineItems[]` with richer fields (`unitPrice`, `tax`)
- Error shape changed from `{error, message}` to `{errors: [{code, message, field}]}`
- `/api/v1/orders` may return `410` + `{error: "API_VERSION_DEPRECATED"}`

## What broke and why
Legacy consumers assume top-level primitive fields and stable enums. v2 introduced nested structures, type changes, ISO timestamps, and conditional fields, which cause the legacy UI to fail or produce incorrect values unless a compatibility layer transforms v2 responses.

## Compatibility mapping strategy
Deterministic mapping rules implemented in `v2_to_legacy(order_v2)`:
- Flatten `customer` → `customerId`, `customerName` (email optional, ignored)
- `amount{value,currency}` → `totalPrice` (float). If missing or unparsable, fallback to `0.0`.
- `createdAt` ISO 8601 → `YYYY-MM-DD` by taking the date component.
- `lineItems[]` → `items[]` mapping:
  - `name` -> `productName`
  - `quantity` -> `qty`
  - drop `unitPrice` and `tax`
  - If `lineItems` missing or empty, inject a deterministic placeholder: `[{productName: "MISSING_ITEM", qty: 0}]` so legacy UI always sees a non-empty list.
- `state` -> `status`: if the v2 `state` is not a legacy enum value, deterministically map to `PAID` as a safe fallback.
- `trackingNumber` passed through when present.

Error normalization (`normalize_error_response(status, body)`):
- If v2 `errors` array exists, take the first element and return `{error: code, message: message}`.
- If already v1 format, pass through.
- Fallback to `{error: "HTTP_<status>", message: <json-of-body>}`.

Monitoring classification (`classify_v1_deprecation(status, body)`):
- `200` -> `OK`
- `410` with `error=="API_VERSION_DEPRECATED"` -> `DEPRECATED` (not an outage)
- Anything else -> `OUTAGE`

## How to run tests
There are two modes demonstrated using the provided test harness `e2e_api_regression_harness.py`:

- Mode A (*RAW_V2*): run without compatibility mapping to demonstrate legacy breakages. This run is expected to show **FAIL** (at least one legacy assumption fails).
- Mode B (*COMPAT*): run with the compatibility mapping enabled so all checks pass.

One-click runners:
- Unix: `./run_tests.sh`
- Windows PowerShell: `.









If both conditions are satisfied, the gateway/adapter ensures legacy consumers continue to operate correctly even as the API evolves.- Mode B shows ALL checks pass after applying the compatibility mapping.- Mode A demonstrates breakage (legacy assumptions fail against raw v2).## What indicates migration is safe for legacy consumersThe scripts will create a `.venv`, install dependencies, run Mode A (expecting it to fail), then Mode B (expecting it to pass). The overall script exits non-zero if the expected FAIL-THEN-PASS gate is not satisfied.un_tests.ps1`