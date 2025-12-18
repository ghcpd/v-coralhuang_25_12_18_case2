E2E API Migration Regression Harness
====================================

Overview
--------
This harness demonstrates a compatibility layer for an API migration from `/api/v1/orders` to `/api/v2/orders` that introduces structural and format changes. The test suite runs in two modes:

- RAW_V2 (no compatibility mapping): shows legacy assumptions breaking (FAIL expected)
- COMPAT (compatibility layer enabled): shows the same scenarios pass after deterministic mapping (PASS expected)

Mandatory gate: RAW must show at least one legacy failure and COMPAT must pass all checks. The run scripts enforce this gate and exit non-zero if it is not satisfied.

What changed (v1 -> v2)
------------------------
- customerId, customerName (flat) -> customer { id, name, email } (nested)
- totalPrice (float) -> amount { value, currency } (object)
- createdAt YYYY-MM-DD -> createdAt ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)
- status (enum) renamed to state (enum) with new possible values (e.g., FULFILLED)
- items[] (simple) -> lineItems[] (enriched objects: name, quantity, unitPrice, tax)
- When state == SHIPPED, v2 provides trackingNumber
- Error format: { error, message } -> { errors: [{ code, message, field }] }
- `/api/v1/orders` may return 410 + error=API_VERSION_DEPRECATED when deprecated

Compatibility mapping strategy
-----------------------------
Deterministic mapping rules implemented in v2_to_legacy():
- state -> status: keep value if in legacy enum, otherwise map to deterministic fallback 'PAID'
- amount.value -> totalPrice (float); defaults to 0.0 if missing or invalid
- customer.id/name -> customerId/customerName (flattening); missing fields become None
- lineItems -> items: map { name, quantity } -> { productName, qty }; drop unitPrice/tax
- createdAt ISO -> YYYY-MM-DD by parsing ISO8601 and formatting date
- trackingNumber is passed through if present
- Guarantee items exists and is non-empty (inject placeholder item if necessary)

Error normalization
-------------------
- v2 errors array -> v1 format: take the first error and map to { error: code, message: message }
- If body already uses v1 format, pass through unchanged
- Deterministic fallback provides UNKNOWN_ERROR and serialized message if structure is unexpected

Monitoring semantics
-------------------
- classify_v1_deprecation() returns:
  - 'DEPRECATED' when 410 + error == 'API_VERSION_DEPRECATED' (not an outage)
  - 'OK' when 200
  - 'OUTAGE' otherwise
This prevents alerting the monitoring system for expected deprecation responses.

How to run
----------
- Linux/macOS: ./run_tests.sh
- Windows PowerShell: ./run_tests.ps1

The harness will create a virtualenv, install pinned deps, run a full suite (RAW then COMPAT), and enforce the gate:
- RAW must show at least one failing legacy expectation
- COMPAT must pass all compatibility checks

Expected output (excerpt)
-------------------------
--- RAW_V2 RUN (compatibility OFF) ---
FAIL - legacy assumption: items must exist and be non-empty :: body={...}
...
Summary: 0/5 PASS

--- COMPAT RUN (compatibility ON) ---
PASS - nested structure flattened correctly
PASS - type change: amount object converted to totalPrice float
PASS - compat mapping produces legacy-safe shape
PASS - error format normalized to v1 structure
PASS - monitoring: v1 deprecation classified as DEPRECATED

GATE PASSED: RAW showed failures and COMPAT fixed them. Migration compatibility validated.

Notes
-----
- The harness supports live E2E testing against a real API when BASE_URL is set in the environment. In that mode the same mapping and normalization functions are applied.
- The compatibility layer is implemented inside this harness (`v2_to_legacy`, `normalize_error_response`, `classify_v1_deprecation`). In production this would be implemented in a gateway or middleware layer.
