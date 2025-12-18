"""
E2E API Migration Regression Harness

How to run (real API):
  export BASE_URL="https://api.example.com"
  python e2e_api_regression_harness.py

How to run (no real API, offline mode):
  unset BASE_URL
  python e2e_api_regression_harness.py

What this tests:
- Raw v2 breaks legacy assumptions with schema mismatches
- Compatibility mapping handles nested structure changes, type changes, format changes
- v1 deprecation (410) must be classified as deprecation, not outage
- Error response format changes (v1 vs v2 error structures)

Schema changes in v2:
1. Nested structure: customerId/customerName → customer{id, name, email}
2. Type change: amount (float) → amount{value, currency}
3. Date format: createdAt "YYYY-MM-DD" → ISO 8601 "YYYY-MM-DDTHH:MM:SSZ"
4. Conditional fields: state=SHIPPED requires trackingNumber in v2
5. Error format: {error: string} → {errors: [{code, message, field}]}
6. Array element changes: lineItems gain new fields (unitPrice, tax)

Agent task:
- Implement TODO sections:
  1) request_json(): real HTTP calling when BASE_URL is set
  2) v2_to_legacy(): deterministic mapping rules
  3) classify_v1_deprecation(): monitoring semantics
  4) normalize_error_response(): handle error format differences
- Ensure the harness produces PASS for all required checks.
"""

from __future__ import annotations
import json
import os
import sys
import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# -------------------------
# Test vectors (embedded)
# -------------------------

CASES_JSON = r"""
{
  "error_cases": [
    {
      "id": "missing_includeItems_v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "123" }
      },
      "response": {
        "statusCode": 200,
        "body": { 
          "orderId": "ORD-123", 
          "state": "PAID", 
          "amount": {"value": 199.99, "currency": "USD"},
          "customer": {"id": "C123", "name": "Alice", "email": "alice@example.com"},
          "createdAt": "2024-12-18T10:30:00Z"
        }
      }
    },
    {
      "id": "items_vs_lineItems_mismatch",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "789", "includeItems": "true" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "orderId": "ORD-789",
          "state": "SHIPPED",
          "amount": {"value": 59.5, "currency": "USD"},
          "customer": {"id": "C789", "name": "Bob", "email": "bob@example.com"},
          "createdAt": "2024-12-17T15:45:30Z",
          "trackingNumber": "TRACK-789-XYZ",
          "lineItems": [
            { "name": "Pen", "quantity": 3, "unitPrice": 5.5, "tax": 0.8 },
            { "name": "Notebook", "quantity": 2, "unitPrice": 15.0, "tax": 2.0 }
          ]
        }
      }
    },
    {
      "id": "deprecated_v1_monitored_as_outage",
      "request": {
        "method": "GET",
        "path": "/api/v1/orders",
        "query": { "userId": "999" }
      },
      "response": {
        "statusCode": 410,
        "body": { "error": "API_VERSION_DEPRECATED", "message": "Please migrate to /api/v2/orders" }
      }
    },
    {
      "id": "new_state_enum_breaks_legacy_enum",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "555", "includeItems": "false" }
      },
      "response": {
        "statusCode": 200,
        "body": { 
          "orderId": "ORD-555", 
          "state": "FULFILLED", 
          "amount": {"value": 120.0, "currency": "EUR"},
          "customer": {"id": "C555", "name": "Charlie"},
          "createdAt": "2024-12-16T08:20:15Z"
        }
      }
    },
    {
      "id": "v2_error_format_new_structure",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "invalid" }
      },
      "response": {
        "statusCode": 400,
        "body": {
          "errors": [
            {"code": "INVALID_USER_ID", "message": "User ID must be numeric", "field": "userId"},
            {"code": "RATE_LIMIT", "message": "Too many requests", "field": null}
          ]
        }
      }
    },
    {
      "id": "nested_customer_data_missing_email",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "888" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "orderId": "ORD-888",
          "state": "CANCELLED",
          "amount": {"value": 0.0, "currency": "USD"},
          "customer": {"id": "C888", "name": "Dave"},
          "createdAt": "2024-12-15T12:00:00Z"
        }
      }
    }
  ]
}
"""

CASES = json.loads(CASES_JSON)["error_cases"]

LEGACY_ENUM = {"PAID", "CANCELLED", "SHIPPED"}  # legacy known values


# -------------------------
# Minimal runner utilities
# -------------------------

@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""


def _pass(name: str, details: str = "") -> CheckResult:
    return CheckResult(name=name, ok=True, details=details)


def _fail(name: str, details: str = "") -> CheckResult:
    return CheckResult(name=name, ok=False, details=details)


def print_report(results: List[CheckResult]) -> None:
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        line = f"{status} - {r.name}"
        if r.details:
            line += f" :: {r.details}"
        print(line)
    print(f"\nSummary: {passed}/{total} PASS")
    if passed != total:
        sys.exit(1)


# -------------------------
# TODO #1: real HTTP client
# -------------------------

def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """
    If BASE_URL is set, call the real API (E2E).
    If BASE_URL is not set, fall back to the embedded 'response' in CASES (offline simulation).

    Requirements for real call:
    - Use requests (standard library doesn't include HTTP client as ergonomic; requests is acceptable)
    - Must return (status_code, json_body_dict)
    - Fail loudly if response is not JSON
    """
    base_url = os.environ.get("BASE_URL", "").strip()
    if not base_url:
        # Offline mode: return the canned response matching path+query
        for c in CASES:
            req = c["request"]
            if req["method"] == method and req["path"] == path and req["query"] == query:
                return c["response"]["statusCode"], c["response"]["body"]
        raise RuntimeError(f"No canned response for {method} {path} {query}")

    # Real HTTP call
    url = base_url.rstrip("/") + path
    try:
        resp = requests.request(method, url, params=query, timeout=10)
    except requests.RequestException as exc:
        raise RuntimeError(f"HTTP request failed: {exc}") from exc

    # Ensure JSON response
    content_type = resp.headers.get("Content-Type", "")
    if "application/json" not in content_type and not resp.text.strip().startswith("{"):
        raise RuntimeError(f"Non-JSON response from {url}: content-type={content_type}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Response from {url} is not valid JSON: {exc}") from exc
    return resp.status_code, body


# -------------------------
# TODO #2: compatibility mapping (ADVANCED)
# -------------------------

def v2_to_legacy(order_v2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic mapping from v2 -> legacy-safe shape.
    See docstring above for mapping intent.
    """
    legacy: Dict[str, Any] = {}

    # passthrough orderId
    if "orderId" in order_v2:
        legacy["orderId"] = order_v2["orderId"]

    # status: downgrade unknown states deterministically to 'PAID'
    state = order_v2.get("state")
    if isinstance(state, str) and state in LEGACY_ENUM:
        legacy["status"] = state
    else:
        # deterministic downgrade for unknown/new states
        legacy["status"] = "PAID"

    # amount -> totalPrice (float)
    total = 0.0
    amt = order_v2.get("amount")
    if isinstance(amt, dict):
        try:
            total = float(amt.get("value", 0.0))
        except Exception:
            total = 0.0
    elif isinstance(amt, (int, float)):
        total = float(amt)
    legacy["totalPrice"] = total

    # customer flattening
    cust = order_v2.get("customer")
    if isinstance(cust, dict):
        legacy["customerId"] = str(cust.get("id", ""))
        legacy["customerName"] = str(cust.get("name", ""))
    else:
        # graceful defaults
        legacy["customerId"] = str(order_v2.get("customerId", ""))
        legacy["customerName"] = str(order_v2.get("customerName", ""))

    # lineItems -> items (productName, qty)
    items: List[Dict[str, Any]] = []
    line_items = order_v2.get("lineItems")
    if isinstance(line_items, list) and len(line_items) > 0:
        for li in line_items:
            name = li.get("name") if isinstance(li, dict) else None
            qty = li.get("quantity") if isinstance(li, dict) else None
            try:
                qty_val = int(qty) if qty is not None else 0
            except Exception:
                qty_val = 0
            items.append({"productName": name or "UNKNOWN", "qty": qty_val})
    # Guarantee non-empty items list for legacy safety
    if not items:
        items = [{"productName": "UNKNOWN", "qty": 0}]
    legacy["items"] = items

    # createdAt: ISO 8601 -> YYYY-MM-DD
    created = order_v2.get("createdAt", "")
    if isinstance(created, str):
        # handle Z suffix and common ISO variants
        try:
            from datetime import datetime
            s = created
            if s.endswith("Z"):
                dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            else:
                # attempt fromisoformat for variants with timezone
                dt = datetime.fromisoformat(s)
            legacy["createdAt"] = dt.strftime("%Y-%m-%d")
        except Exception:
            # fallback: take date prefix
            legacy["createdAt"] = created.split("T")[0] if "T" in created else created
    else:
        legacy["createdAt"] = "1970-01-01"

    # trackingNumber pass-through if present
    if "trackingNumber" in order_v2:
        legacy["trackingNumber"] = order_v2["trackingNumber"]

    return legacy


# -------------------------
# TODO #3: monitoring semantics
# -------------------------

def classify_v1_deprecation(status_code: int, body: Dict[str, Any]) -> str:
    """
    Classify v1 responses for monitoring semantics.
    """
    if status_code == 200:
        return "OK"
    # deprecation signal
    if status_code == 410:
        # body may be {"error": "API_VERSION_DEPRECATED", "message": ...}
        err = body.get("error") if isinstance(body, dict) else None
        if err == "API_VERSION_DEPRECATED":
            return "DEPRECATED"
        # also check message for hints
        msg = (body.get("message") or "") if isinstance(body, dict) else ""
        if "deprecated" in str(msg).lower() or "migrate" in str(msg).lower():
            return "DEPRECATED"
        return "DEPRECATED"
    return "OUTAGE"


# -------------------------
# TODO #4: error response normalization
# -------------------------

def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize v2 error format to v1 format deterministically.
    """
    if not isinstance(body, dict):
        return {"error": "UNKNOWN_ERROR", "message": "Non-dict error body"}

    # v1 already
    if "error" in body and "message" in body:
        return {"error": str(body.get("error")), "message": str(body.get("message"))}

    # v2 style: errors array
    errs = body.get("errors")
    if isinstance(errs, list) and len(errs) > 0 and isinstance(errs[0], dict):
        first = errs[0]
        code = first.get("code") or "ERROR"
        message = first.get("message") or ""
        return {"error": str(code), "message": str(message)}

    # fallback
    return {"error": "UNKNOWN_ERROR", "message": json.dumps(body)}


# -------------------------
# RAW-only checks (assert that v2 raw responses break legacy assumptions)
# -------------------------

def raw_check_customer_is_nested() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("raw nested customer: expected 200", f"got {status}")
    if "customer" in body and isinstance(body["customer"], dict):
        return _pass("raw nested customer detected")
    return _fail("raw nested customer: expected nested customer", f"body={body}")


def raw_check_amount_is_object() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
    if status != 200:
        return _fail("raw amount object: expected 200", f"got {status}")
    if isinstance(body.get("amount"), dict):
        return _pass("raw amount is object as expected")
    return _fail("raw amount should be object", f"amount={body.get('amount')}")


def raw_check_createdAt_is_iso() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("raw createdAt: expected 200", f"got {status}")
    created = body.get("createdAt")
    if isinstance(created, str) and ("T" in created and (created.endswith("Z") or "+" in created)):
        return _pass("raw createdAt in ISO 8601 format")
    return _fail("raw createdAt not ISO", f"createdAt={created}")


def raw_check_error_format_array() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "invalid"})
    if status != 400:
        return _fail("raw error format: expected 400", f"got {status}")
    if "errors" in body and isinstance(body["errors"], list):
        return _pass("raw v2 error format uses errors array")
    return _fail("raw v2 error format not array", f"body={body}")


def main() -> None:
    """Mode-aware runner.

    MODE env values:
      - RAW: run raw checks that demonstrate v2 breaks legacy assumptions (should PASS to show failures)
      - COMPAT: run compatibility checks (mapping + normalization) and expect PASS
      - ALL (default): run RAW then COMPAT sequentially
    """
    mode = os.environ.get("MODE", "ALL").upper()

    raw_checks = [
        check_raw_v2_breaks_legacy_items_missing,
        check_raw_v2_breaks_legacy_enum_on_new_state,
        raw_check_customer_is_nested,
        raw_check_amount_is_object,
        raw_check_createdAt_is_iso,
        raw_check_error_format_array,
    ]

    compat_checks = [
        check_nested_structure_flattened,
        check_type_change_amount_object,
        check_compat_mapping_produces_legacy_shape,
        check_error_format_normalized,
        check_v1_deprecation_classified_not_outage,
    ]

    if mode == "RAW":
        print("=== MODE: RAW (showing v2 breaks that would impact legacy) ===")
        results = [c() for c in raw_checks]
        print_report(results)
        return

    if mode == "COMPAT":
        print("=== MODE: COMPAT (compatibility mapping enabled) ===")
        results = [c() for c in compat_checks]
        print_report(results)
        return

    # default ALL: run RAW then COMPAT and ensure both sets pass
    print("=== MODE: ALL -> RAW then COMPAT ===")
    print("--- RAW phase ---")
    raw_results = [c() for c in raw_checks]
    print_report(raw_results)

    print("--- COMPAT phase ---")
    compat_results = [c() for c in compat_checks]
    print_report(compat_results)



# -------------------------
# Checks
# -------------------------

def check_raw_v2_breaks_legacy_items_missing() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("raw v2: expected 200", f"got {status}")
    # Legacy expects items[]; raw v2 does not provide it.
    if "items" in body:
        return _fail("raw v2 breaks legacy: items should be missing in v2", "unexpected items present")
    return _pass("raw v2 breaks legacy: items missing as expected")


def check_raw_v2_breaks_legacy_enum_on_new_state() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
    if status != 200:
        return _fail("raw v2: expected 200 for enum case", f"got {status}")
    state = body.get("state")
    if not state:
        return _fail("raw v2: state missing", "no state")
    # If state is new, legacy strict enum would crash (simulated).
    if state not in LEGACY_ENUM:
        return _pass("raw v2 breaks legacy enum: new state detected", f"state={state}")
    return _fail("raw v2 breaks legacy enum: expected new value", f"state={state} is legacy-known")


def check_compat_mapping_produces_legacy_shape() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "789", "includeItems": "true"})
    if status != 200:
        return _fail("compat mapping: expected 200", f"got {status}")
    legacy = v2_to_legacy(body)

    required = {"orderId", "status", "totalPrice", "items", "customerId", "customerName", "createdAt"}
    missing = [k for k in required if k not in legacy]
    if missing:
        return _fail("compat mapping: required fields missing", f"missing={missing}")

    if not isinstance(legacy["items"], list) or len(legacy["items"]) == 0:
        return _fail("compat mapping: items must be non-empty list", f"items={legacy['items']}")

    item0 = legacy["items"][0]
    if "productName" not in item0 or "qty" not in item0:
        return _fail("compat mapping: items shape invalid", f"item0={item0}")

    if legacy["status"] not in LEGACY_ENUM:
        return _fail("compat mapping: status must be legacy enum-safe", f"status={legacy['status']}")
    
    # Advanced checks: customer flattening
    if not isinstance(legacy["customerId"], str) or not legacy["customerId"]:
        return _fail("compat mapping: customerId must be non-empty string", f"customerId={legacy.get('customerId')}")
    
    # Advanced checks: totalPrice type (must be float, not dict)
    if not isinstance(legacy["totalPrice"], (int, float)):
        return _fail("compat mapping: totalPrice must be numeric", f"totalPrice={legacy['totalPrice']}")
    
    # Advanced checks: date format (must be YYYY-MM-DD, not ISO 8601)
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', legacy["createdAt"]):
        return _fail("compat mapping: createdAt must be YYYY-MM-DD", f"createdAt={legacy['createdAt']}")

    return _pass("compat mapping produces legacy-safe shape")


def check_nested_structure_flattened() -> CheckResult:
    """Check that nested customer object is properly flattened."""
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("nested structure: expected 200", f"got {status}")
    
    # v2 has nested customer{id, name, email}
    if "customer" not in body or not isinstance(body["customer"], dict):
        return _fail("nested structure: v2 should have nested customer", f"body={body}")
    
    legacy = v2_to_legacy(body)
    
    # Legacy should have flat customerId, customerName
    if "customer" in legacy:
        return _fail("nested structure: legacy should not have nested customer", f"legacy={legacy}")
    
    if "customerId" not in legacy or "customerName" not in legacy:
        return _fail("nested structure: missing flattened fields", f"legacy={legacy}")
    
    return _pass("nested structure flattened correctly")


def check_type_change_amount_object() -> CheckResult:
    """Check that v2 amount{value, currency} is converted to legacy totalPrice float."""
    status, body = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
    if status != 200:
        return _fail("type change: expected 200", f"got {status}")
    
    # v2 has amount as object
    if not isinstance(body.get("amount"), dict):
        return _fail("type change: v2 should have amount as object", f"amount={body.get('amount')}")
    
    legacy = v2_to_legacy(body)
    
    # Legacy should have totalPrice as float
    if not isinstance(legacy.get("totalPrice"), (int, float)):
        return _fail("type change: totalPrice should be numeric", f"totalPrice={legacy.get('totalPrice')}")
    
    return _pass("type change: amount object converted to totalPrice float")


def check_error_format_normalized() -> CheckResult:
    """Check that v2 error format is normalized to v1 format."""
    status, body = request_json("GET", "/api/v2/orders", {"userId": "invalid"})
    if status != 400:
        return _fail("error format: expected 400", f"got {status}")
    
    # v2 has errors array
    if "errors" not in body or not isinstance(body["errors"], list):
        return _fail("error format: v2 should have errors array", f"body={body}")
    
    normalized = normalize_error_response(status, body)
    
    # Normalized should have v1 format
    if "error" not in normalized or "message" not in normalized:
        return _fail("error format: normalized should have error/message", f"normalized={normalized}")
    
    if "errors" in normalized:
        return _fail("error format: normalized should not have errors array", f"normalized={normalized}")
    
    return _pass("error format normalized to v1 structure")


def check_v1_deprecation_classified_not_outage() -> CheckResult:
    status, body = request_json("GET", "/api/v1/orders", {"userId": "999"})
    classification = classify_v1_deprecation(status, body)
    if classification != "DEPRECATED":
        return _fail("monitoring: v1 deprecation must not be outage", f"classification={classification}, status={status}, body={body}")
    return _pass("monitoring: v1 deprecation classified as DEPRECATED")




if __name__ == "__main__":
    main()
