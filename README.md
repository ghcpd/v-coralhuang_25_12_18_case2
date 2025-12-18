# E2E API Migration Regression Harness

## Overview

This regression test harness validates a critical API migration from **v1 to v2** with a compatibility layer that transforms v2 responses into legacy-safe shapes. The harness ensures that:

1. **Raw v2 breaks legacy assumptions** (documented failures in MODE A)
2. **Compatibility mapping fixes all issues** (all tests pass in MODE B)
3. **Monitoring semantics are correct** (deprecation != outage)

## Schema Changes: v1 → v2

### 1. **Nested Structure: Customer Object**

**v1 (Legacy):** Flat fields
```json
{
  "customerId": "C123",
  "customerName": "Alice"
}
```

**v2 (New):** Nested object with optional email
```json
{
  "customer": {
    "id": "C123",
    "name": "Alice",
    "email": "alice@example.com"  // optional
  }
}
```

**Issue:** Legacy clients expect `customerId` and `customerName` as top-level strings. Direct consumption causes `KeyError` or `TypeError`.

---

### 2. **Type Change: Amount**

**v1:** Simple float
```json
{
  "totalPrice": 199.99
}
```

**v2:** Structured object
```json
{
  "amount": {
    "value": 199.99,
    "currency": "USD"
  }
}
```

**Issue:** Legacy code calling `total = response['totalPrice']` breaks. Code expecting numeric type gets a dict.

---

### 3. **Date Format Change**

**v1:** Simple date string
```json
{
  "createdAt": "2024-12-18"
}
```

**v2:** ISO 8601 with time
```json
{
  "createdAt": "2024-12-18T10:30:00Z"
}
```

**Issue:** Legacy UI expecting "YYYY-MM-DD" may display full timestamp or fail date parsing. Comparisons and sorting break.

---

### 4. **Field Rename + Enum Changes**

**v1:** `status` with fixed enum
```json
{
  "status": "PAID"  // enum: {PAID, CANCELLED, SHIPPED}
}
```

**v2:** `state` with new values
```json
{
  "state": "FULFILLED"  // new value, not in legacy enum
}
```

**Issue:** Legacy strict enum validation crashes. New state `FULFILLED` is unrecognized.

---

### 5. **Array Element Structure**

**v1:** Simple items
```json
{
  "items": [
    {"productName": "Pen", "qty": 3},
    {"productName": "Notebook", "qty": 2}
  ]
}
```

**v2:** Enriched lineItems
```json
{
  "lineItems": [
    {"name": "Pen", "quantity": 3, "unitPrice": 5.5, "tax": 0.8},
    {"name": "Notebook", "quantity": 2, "unitPrice": 15.0, "tax": 2.0}
  ]
}
```

**Issue:** Legacy UI assumes field names `productName`/`qty`. v2 uses `name`/`quantity`. Field mapping breaks.

---

### 6. **Missing Optional Fields**

**v2 Behavior:**
- When `includeItems=false` (default), `lineItems` is completely omitted.
- When `state != SHIPPED`, `trackingNumber` is omitted.

**Issue:** Legacy assumes `items` always exists (non-empty list). Missing field causes `KeyError`.

---

### 7. **Error Response Format**

**v1 Error:**
```json
{
  "error": "INVALID_USER_ID",
  "message": "User ID must be numeric"
}
```

**v2 Error:**
```json
{
  "errors": [
    {"code": "INVALID_USER_ID", "message": "User ID must be numeric", "field": "userId"},
    {"code": "RATE_LIMIT", "message": "Too many requests", "field": null}
  ]
}
```

**Issue:** Legacy error handlers look for `response['error']`, not `response['errors'][0]['code']`. Monitoring fails.

---

## What Broke: Root Causes

| Issue | Why | Impact |
|-------|-----|--------|
| Missing `items` | v2 omits `lineItems` when not requested | `KeyError` in legacy code expecting non-empty list |
| Nested `customer` | Flattened → nested object | Type mismatch: `customerId` missing, `customer` is dict |
| `amount` as object | Simple float → structured object | Legacy code expecting float receives dict; arithmetic fails |
| ISO 8601 dates | "YYYY-MM-DD" → "2024-12-18T10:30:00Z" | Date parsing breaks; display shows full timestamp |
| New `state` enum | `FULFILLED` is unknown | Legacy strict enum validation crashes |
| `lineItems` vs `items` | Field rename + structure change | Missing expected field names; iteration fails |
| v2 error arrays | Single error → array of errors | Legacy error handler looks for `error`, not `errors[0]` |

---

## Compatibility Mapping Strategy

### Core Transformations

The `v2_to_legacy()` function applies **deterministic, stable** transformations:

```python
def v2_to_legacy(order_v2: Dict[str, Any]) -> Dict[str, Any]:
    legacy = {}
    
    # 1. Flatten nested customer object
    customer = order_v2.get("customer", {})
    legacy["customerId"] = customer.get("id", "")
    legacy["customerName"] = customer.get("name", "")
    
    # 2. Convert amount object to totalPrice float
    amount = order_v2.get("amount", {})
    legacy["totalPrice"] = float(amount.get("value", 0.0))
    
    # 3. Downgrade new state enum to legacy-safe status
    state = order_v2.get("state", "UNKNOWN")
    if state in {"PAID", "CANCELLED", "SHIPPED"}:
        legacy["status"] = state
    else:
        # Deterministic downgrade: FULFILLED → PAID
        downgrade_map = {"FULFILLED": "PAID"}
        legacy["status"] = downgrade_map.get(state, "PAID")
    
    # 4. Convert lineItems to items with remapped fields
    line_items = order_v2.get("lineItems", [])
    items = [{"productName": li.get("name", ""), "qty": li.get("quantity", 0)} 
             for li in line_items]
    
    # 5. Guarantee non-empty items list (legacy safety)
    if not items:
        items = [{"productName": "Unknown", "qty": 0}]
    legacy["items"] = items
    
    # 6. Convert createdAt date format
    created_at = order_v2.get("createdAt", "")
    legacy["createdAt"] = created_at[:10] if created_at else "1970-01-01"
    
    # 7. Pass through optional trackingNumber if present
    if "trackingNumber" in order_v2:
        legacy["trackingNumber"] = order_v2["trackingNumber"]
    
    return legacy
```

### Error Response Normalization

The `normalize_error_response()` function converts v2 error arrays to v1 format:

```python
def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    # If already v1 format, pass through
    if "error" in body and "message" in body:
        return body
    
    # Convert v2 errors array to v1 format (take first error)
    if "errors" in body and isinstance(body["errors"], list):
        first_error = body["errors"][0]
        return {
            "error": first_error.get("code", "UNKNOWN_ERROR"),
            "message": first_error.get("message", "An error occurred")
        }
    
    # Fallback
    return {"error": "UNKNOWN_ERROR", "message": "An error occurred"}
```

### Monitoring: Deprecation vs Outage

The `classify_v1_deprecation()` function correctly classifies v1 responses:

```python
def classify_v1_deprecation(status_code: int, body: Dict[str, Any]) -> str:
    if status_code == 200:
        return "OK"
    
    if status_code == 410:
        # 410 + API_VERSION_DEPRECATED marker → DEPRECATED (not outage)
        error = body.get("error", "")
        if error == "API_VERSION_DEPRECATED":
            return "DEPRECATED"
    
    # Anything else → OUTAGE
    return "OUTAGE"
```

**Why this matters:** Legacy monitoring systems misclassify v1 deprecation (410) as outage. This rule ensures v1 deprecation is properly flagged as `DEPRECATED`, not triggering false incident alerts.

---

## Test Structure: FAIL-THEN-PASS Gate

The harness runs **one test suite** that validates both MODE A (raw failures) and MODE B (compat fixes):

### MODE A: Raw v2 Breaks Legacy

These checks **MUST demonstrate failures** for raw v2 consumption:

1. **`check_raw_v2_breaks_legacy_items_missing()`**
   - Validates that raw v2 omits `items` field
   - Legacy code expecting non-empty `items` list would crash

2. **`check_raw_v2_breaks_legacy_enum_on_new_state()`**
   - Validates that raw v2 contains new `FULFILLED` state
   - Legacy strict enum validation would reject this value

3. **`check_nested_structure_flattened()`**
   - Validates that v2 has nested `customer{id, name, email}`
   - Legacy code expecting flat `customerId`/`customerName` would fail

4. **`check_type_change_amount_object()`**
   - Validates that v2 has `amount` as object
   - Legacy code expecting numeric `totalPrice` would fail

### MODE B: Compatibility Mapping Fixes All

These checks **MUST ALL PASS** after applying compatibility mapping:

1. **`check_compat_mapping_produces_legacy_shape()`**
   - Validates that `v2_to_legacy()` produces legacy-safe shape
   - Checks: `status` is enum-safe, `totalPrice` is float, `items` is non-empty list, `customerId`/`customerName` are flat strings, `createdAt` is "YYYY-MM-DD"

2. **`check_error_format_normalized()`**
   - Validates that v2 error array converts to v1 format
   - Checks: normalized response has `error` and `message` (not `errors`)

3. **`check_v1_deprecation_classified_not_outage()`**
   - Validates that 410 + `API_VERSION_DEPRECATED` is classified as `DEPRECATED`
   - Ensures legacy monitoring doesn't false-alarm

---

## Running the Tests

### Windows (PowerShell)

```powershell
.\run_tests.ps1
```

This script:
1. Creates/activates a virtual environment (`./venv`)
2. Installs dependencies from `requirements.txt`
3. Runs tests in **OFFLINE MODE** (no real API calls)
4. Prints PASS/FAIL summary

**Expected Output:**
```
=== E2E API Regression Harness Test Runner ===
Platform: Windows (PowerShell)

[1/4] Checking Python availability...
  Found Python: C:\Python310\python.exe

[2/4] Setting up virtual environment...
  Activated: .\venv

[3/4] Installing dependencies...
  Dependencies installed

[4/4] Running regression tests (OFFLINE MODE)...
--- TEST OUTPUT ---
PASS - raw v2 breaks legacy: items missing as expected
PASS - raw v2 breaks legacy enum: new state detected :: state=FULFILLED
PASS - nested structure flattened correctly
PASS - type change: amount object converted to totalPrice float
PASS - compat mapping produces legacy-safe shape
PASS - error format normalized to v1 structure
PASS - monitoring: v1 deprecation classified as DEPRECATED

Summary: 7/7 PASS
--- END TEST OUTPUT ---

RESULT: All tests PASSED
```

### Linux/macOS (Bash)

```bash
chmod +x run_tests.sh
./run_tests.sh
```

Same behavior and output as PowerShell version.

---

## Running Against a Real API

To run against a real `/api/v2/orders` endpoint:

```bash
# PowerShell
$env:BASE_URL = "https://api.example.com"
python e2e_api_regression_harness.py

# Bash
export BASE_URL="https://api.example.com"
python e2e_api_regression_harness.py
```

The harness will:
1. Call the real endpoint if `BASE_URL` is set
2. Fall back to embedded test cases if `BASE_URL` is empty/unset

---

## Test Results Interpretation

### ✅ Safe for Legacy Consumers

All 7 tests PASS:
- Raw v2 failures are documented (MODE A checks)
- Compatibility mapping fixes all issues (MODE B checks)
- Monitoring classifies deprecation correctly

**Actions:**
- Deploy compatibility layer (gateway/adapter) to production
- Legacy clients can safely consume v2 responses through the layer
- v1 deprecation alarms are suppressed (DEPRECATED, not OUTAGE)

### ❌ Not Safe for Legacy Consumers

Any test FAILS:
- Compatibility mapping is incomplete or incorrect
- Monitoring rule needs adjustment

**Actions:**
- Review failed test details
- Update `v2_to_legacy()` or normalization logic
- Re-run tests until all pass

---

## Files

| File | Purpose |
|------|---------|
| `e2e_api_regression_harness.py` | Test harness with embedded test cases and checks |
| `run_tests.ps1` | PowerShell test runner (Windows) |
| `run_tests.sh` | Bash test runner (Linux/macOS) |
| `requirements.txt` | Runtime dependencies (requests library) |
| `requirements-dev.txt` | Development dependencies (pytest, etc.) |
| `README.md` | This file |

---

## Dependencies

- **Python 3.7+**
- **requests 2.31.0** (for real API calls; optional in offline mode)

Install with:
```bash
pip install -r requirements.txt
```

---

## Implementation Details

### HTTP Client (`request_json()`)

- **Offline mode** (default): Uses embedded test cases in `CASES` JSON
- **E2E mode** (with `BASE_URL`): Calls real API via `requests.request()`
- Raises `RuntimeError` if response is not valid JSON
- Returns `(status_code, json_body_dict)` tuple

### Compatibility Mapping (`v2_to_legacy()`)

- **Deterministic:** Same v2 input always produces same legacy output
- **Safe:** Handles missing/optional fields gracefully (no KeyError)
- **Enum downgrade:** Maps unknown state values to legacy-known values (e.g., FULFILLED → PAID)
- **Field flattening:** Converts nested objects to flat fields
- **Type conversion:** Converts structured types to primitives
- **Items guarantee:** Ensures non-empty items list even if lineItems is missing

### Error Normalization (`normalize_error_response()`)

- Detects v2 format (errors array) and converts to v1 format
- Passes through already-v1-format responses
- Deterministic: Takes first error from array
- Safe fallback: Returns generic error if format is unexpected

### Monitoring Rule (`classify_v1_deprecation()`)

- **410 + API_VERSION_DEPRECATED** → "DEPRECATED" (not outage)
- **200** → "OK"
- **Anything else** → "OUTAGE"

Prevents false incident alerts for intentional v1 deprecation.

---

## Audit Trail

This harness is designed to be:

1. **Repeatable:** Same test cases, same checks, same results
2. **Verifiable:** Clear PASS/FAIL output with test names and details
3. **Traceable:** Embedded test cases show exactly what's being tested
4. **Deterministic:** No randomization, external API calls optional

All tests run in ~100ms in offline mode, suitable for CI/CD pipelines.

---

## Next Steps

1. **Deploy compatibility layer** to API gateway/middleware (transform responses via `v2_to_legacy()`)
2. **Update monitoring rules** to use `classify_v1_deprecation()` for v1 endpoints
3. **Run tests in CI/CD** after each API deployment
4. **Plan v1 sunset** with confidence that legacy clients are protected

---

## Contact

For questions or issues with this regression harness, refer to the test output and check the implementation details in `e2e_api_regression_harness.py`.
