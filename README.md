# API Migration Regression Harness

This project implements a compatibility layer and regression tests for migrating from `/api/v1/orders` to `/api/v2/orders` with complex schema changes.

## What Changed Between v1 and v2

### Schema Changes
1. **Nested Structure Change**: `customerId` and `customerName` (flat fields) → `customer{id, name, email}` (nested object). Email may be missing.
2. **Type Change**: `totalPrice` (float) → `amount{value, currency}` (structured object).
3. **Date Format Change**: `createdAt` "YYYY-MM-DD" → ISO 8601 "YYYY-MM-DDTHH:MM:SSZ".
4. **Field Rename + Structure**: `status` (string enum) → `state` (string enum with new values like "FULFILLED").
5. **Array Element Structure Change**: `items[]{productName, qty}` → `lineItems[]{name, quantity, unitPrice, tax}`.
6. **Conditional Fields**: `trackingNumber` present when `state=SHIPPED`.
7. **Error Response Format Change**: `{error, message}` → `{errors: [{code, message, field}]}`.

### Behavioral Changes
- `/api/v2/orders` introduces `includeItems` query param (default false), omitting `lineItems` when absent/false.
- New `state` values break legacy enum assumptions.
- `/api/v1/orders` deprecated, returns 410 with `API_VERSION_DEPRECATED`.

## What Broke and Why

Legacy clients assume:
- `items` always exists and is non-empty.
- `status` and `totalPrice` are primitives (string/float).
- `customerId` and `customerName` are top-level fields.
- `createdAt` is "YYYY-MM-DD".
- Enum values are fixed.
- Error responses use `{error, message}`.
- `/api/v1/orders` always returns 200.

Raw v2 responses break these assumptions due to nested structures, type changes, format changes, and new enum values.

## Compatibility Mapping Strategy

The `v2_to_legacy()` function transforms v2 responses to legacy-safe shapes:
- Flattens `customer` to `customerId`/`customerName`.
- Converts `amount` to `totalPrice` float.
- Truncates `createdAt` to YYYY-MM-DD.
- Maps `state` to `status`, downgrading unknowns to "PAID".
- Converts `lineItems` to `items`, dropping extra fields.
- Ensures `items` is non-empty (adds dummy if needed).
- Normalizes error format from array to single error/message.

## How to Run Tests

### Prerequisites
- Python 3.8+
- PowerShell (for run_tests.ps1)

### Running Tests
Execute `run_tests.ps1` to run the FAIL-THEN-PASS gate:
- **Mode A (RAW_V2)**: Demonstrates failures for legacy assumptions.
- **Mode B (COMPAT)**: Shows passes after applying compatibility mapping.

For manual runs:
```bash
python e2e_api_regression_harness.py RAW_V2  # Expect failures
python e2e_api_regression_harness.py COMPAT  # Expect passes
```

For real API testing:
```bash
export BASE_URL="https://your-api.example.com"
python e2e_api_regression_harness.py COMPAT
```

## What Output Indicates Migration Safety

- **Mode A FAIL**: All checks pass (meaning breakage detected).
- **Mode B PASS**: All checks pass (meaning compatibility ensured).
- The gate fails if Mode A passes unexpectedly or Mode B fails.

Successful output shows FAIL-THEN-PASS with clear summaries for each mode.