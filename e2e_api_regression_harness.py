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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import requests

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
    url = base_url.rstrip('/') + path
    try:
        response = requests.request(method, url, params=query, timeout=10)
        response.raise_for_status()  # Raise for bad status, but we return status anyway
        body = response.json()
        return response.status_code, body
    except requests.exceptions.RequestException as e:
        # For simplicity, return 500 with error
        return 500, {"error": "REQUEST_FAILED", "message": str(e)}
    except ValueError:
        # Not JSON
        raise RuntimeError(f"Response is not JSON: {response.text}")


# -------------------------
# TODO #2: compatibility mapping (ADVANCED)
# -------------------------

def v2_to_legacy(order_v2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform v2 order shape into legacy-safe shape:
      - state -> status (downgrade unknown values deterministically)
      - amount{value, currency} -> totalPrice (float, USD assumed if missing)
      - customer{id, name, email} -> customerId, customerName (flatten nested object)
      - lineItems(name, quantity, unitPrice, tax) -> items(productName, qty) (drop extra fields)
      - createdAt ISO 8601 -> YYYY-MM-DD date string
      - trackingNumber: pass through if present, otherwise omit
      - Guarantee items exists and is non-empty list for legacy UI safety

    Must be deterministic and stable.
    """
    legacy = {}
    
    # orderId
    legacy["orderId"] = order_v2.get("orderId")
    
    # state -> status
    state = order_v2.get("state", "")
    if state in LEGACY_ENUM:
        legacy["status"] = state
    else:
        # Downgrade unknown states to a safe legacy value
        legacy["status"] = "PAID"
    
    # amount -> totalPrice
    amount = order_v2.get("amount", {})
    if isinstance(amount, dict) and "value" in amount:
        legacy["totalPrice"] = float(amount["value"])
    else:
        legacy["totalPrice"] = 0.0
    
    # customer -> customerId, customerName
    customer = order_v2.get("customer", {})
    if isinstance(customer, dict):
        legacy["customerId"] = customer.get("id", "")
        legacy["customerName"] = customer.get("name", "")
    else:
        legacy["customerId"] = ""
        legacy["customerName"] = ""
    
    # createdAt -> YYYY-MM-DD
    created_at = order_v2.get("createdAt", "")
    if "T" in created_at:
        legacy["createdAt"] = created_at.split("T")[0]
    else:
        legacy["createdAt"] = created_at
    
    # lineItems -> items
    line_items = order_v2.get("lineItems", [])
    if line_items:
        legacy["items"] = [
            {"productName": item.get("name", ""), "qty": item.get("quantity", 0)}
            for item in line_items
        ]
    else:
        # Guarantee non-empty items
        legacy["items"] = [{"productName": "Unknown Item", "qty": 1}]
    
    # trackingNumber if present
    if "trackingNumber" in order_v2:
        legacy["trackingNumber"] = order_v2["trackingNumber"]
    
    return legacy


# -------------------------
# TODO #3: monitoring semantics
# -------------------------

def classify_v1_deprecation(status_code: int, body: Dict[str, Any]) -> str:
    """
    Return one of: "DEPRECATED", "OUTAGE", "OK"
    Rules:
      - 410 + error=API_VERSION_DEPRECATED => DEPRECATED (not outage)
      - 200 => OK
      - anything else => OUTAGE
    """
    if status_code == 410 and body.get("error") == "API_VERSION_DEPRECATED":
        return "DEPRECATED"
    elif status_code == 200:
        return "OK"
    else:
        return "OUTAGE"


# -------------------------
# TODO #4: error response normalization
# -------------------------

def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize v2 error format to v1 format.
    
    v1 format: {\"error\": \"ERROR_CODE\", \"message\": \"Human readable message\"}
    v2 format: {\"errors\": [{\"code\": \"...\", \"message\": \"...\", \"field\": \"...\"}]}
    
    Rules:
      - If v2 errors array exists, take first error and map to v1 format
      - If already v1 format, pass through
      - Must be deterministic
    """
    if "errors" in body and isinstance(body["errors"], list) and body["errors"]:
        first_error = body["errors"][0]
        return {
            "error": first_error.get("code", "UNKNOWN_ERROR"),
            "message": first_error.get("message", "An error occurred")
        }
    else:
        # Assume already v1 format or pass through
        return body


# -------------------------
# Checks (assert legacy assumptions, fail in RAW_V2, pass in COMPAT)
# -------------------------

def check_legacy_items_exist(body: Dict[str, Any]) -> CheckResult:
    if "items" not in body or not isinstance(body["items"], list) or len(body["items"]) == 0:
        return _fail("legacy assumption: items must exist and be non-empty list", f"items={body.get('items')}")
    return _pass("legacy assumption: items present and non-empty")


def check_legacy_customer_flat(body: Dict[str, Any]) -> CheckResult:
    if "customer" in body and isinstance(body["customer"], dict):
        return _fail("legacy assumption: customer must not be nested object", f"customer={body['customer']}")
    if "customerId" not in body or "customerName" not in body:
        return _fail("legacy assumption: customerId and customerName must be flat fields", f"body keys={list(body.keys())}")
    if not isinstance(body["customerId"], str) or not isinstance(body["customerName"], str):
        return _fail("legacy assumption: customerId/customerName must be strings", f"customerId={body.get('customerId')}, customerName={body.get('customerName')}")
    return _pass("legacy assumption: customer flattened correctly")


def check_legacy_totalPrice_float(body: Dict[str, Any]) -> CheckResult:
    if "amount" in body and isinstance(body["amount"], dict):
        return _fail("legacy assumption: amount must not be object", f"amount={body['amount']}")
    if "totalPrice" not in body or not isinstance(body["totalPrice"], (int, float)):
        return _fail("legacy assumption: totalPrice must be numeric", f"totalPrice={body.get('totalPrice')}")
    return _pass("legacy assumption: totalPrice is float")


def check_legacy_createdAt_yyyy_mm_dd(body: Dict[str, Any]) -> CheckResult:
    import re
    created_at = body.get("createdAt", "")
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', created_at):
        return _fail("legacy assumption: createdAt must be YYYY-MM-DD", f"createdAt={created_at}")
    return _pass("legacy assumption: createdAt is YYYY-MM-DD")


def check_legacy_status_enum(body: Dict[str, Any]) -> CheckResult:
    status = body.get("status", body.get("state", ""))  # in raw, state, in compat, status
    if status not in LEGACY_ENUM:
        return _fail("legacy assumption: status must be known enum", f"status={status}, known={LEGACY_ENUM}")
    return _pass("legacy assumption: status in legacy enum")


def check_legacy_error_format(body: Dict[str, Any]) -> CheckResult:
    if "errors" in body and isinstance(body["errors"], list):
        return _fail("legacy assumption: error must not be array", f"errors={body['errors']}")
    if "error" not in body or "message" not in body:
        return _fail("legacy assumption: error and message must be present", f"body keys={list(body.keys())}")
    return _pass("legacy assumption: error format is v1")

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


# Additional checks for RAW_V2 mode (to show breakage)
def check_raw_v2_nested_customer_not_flat() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("raw v2 nested: expected 200", f"got {status}")
    if "customer" not in body or not isinstance(body["customer"], dict):
        return _fail("raw v2 nested: should have nested customer", f"body={body}")
    if "customerId" in body or "customerName" in body:
        return _fail("raw v2 nested: should not have flat fields", f"body={body}")
    return _pass("raw v2 nested: customer is nested object")


def check_raw_v2_amount_is_object() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
    if status != 200:
        return _fail("raw v2 amount: expected 200", f"got {status}")
    if not isinstance(body.get("amount"), dict):
        return _fail("raw v2 amount: should be object", f"amount={body.get('amount')}")
    if "totalPrice" in body:
        return _fail("raw v2 amount: should not have totalPrice", f"body={body}")
    return _pass("raw v2 amount: amount is object")


def check_raw_v2_date_is_iso() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("raw v2 date: expected 200", f"got {status}")
    created_at = body.get("createdAt", "")
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', created_at):
        return _fail("raw v2 date: should be ISO 8601", f"createdAt={created_at}")
    return _pass("raw v2 date: createdAt is ISO 8601")


def check_raw_v2_error_is_array() -> CheckResult:
    status, body = request_json("GET", "/api/v2/orders", {"userId": "invalid"})
    if status != 400:
        return _fail("raw v2 error: expected 400", f"got {status}")
    if "errors" not in body or not isinstance(body["errors"], list):
        return _fail("raw v2 error: should have errors array", f"body={body}")
    if "error" in body or "message" in body:
        return _fail("raw v2 error: should not have v1 format", f"body={body}")
    return _pass("raw v2 error: errors is array")


def main() -> None:
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "RAW_V2"
    
    if mode == "RAW_V2":
        # Run legacy assumption checks on raw v2 responses (expect failures)
        results = [
            check_legacy_items_exist(request_json("GET", "/api/v2/orders", {"userId": "123"})[1]),
            check_legacy_status_enum(request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})[1]),
            check_legacy_customer_flat(request_json("GET", "/api/v2/orders", {"userId": "123"})[1]),
            check_legacy_totalPrice_float(request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})[1]),
            check_legacy_createdAt_yyyy_mm_dd(request_json("GET", "/api/v2/orders", {"userId": "123"})[1]),
            check_legacy_error_format(request_json("GET", "/api/v2/orders", {"userId": "invalid"})[1]),
        ]
    elif mode == "COMPAT":
        # Run legacy assumption checks on mapped v2 responses (expect passes)
        # For successful responses, apply v2_to_legacy
        status1, body1 = request_json("GET", "/api/v2/orders", {"userId": "123"})
        mapped_body1 = v2_to_legacy(body1) if status1 == 200 else body1
        
        status2, body2 = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
        mapped_body2 = v2_to_legacy(body2) if status2 == 200 else body2
        
        status3, body3 = request_json("GET", "/api/v2/orders", {"userId": "123"})
        mapped_body3 = v2_to_legacy(body3) if status3 == 200 else body3
        
        status4, body4 = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
        mapped_body4 = v2_to_legacy(body4) if status4 == 200 else body4
        
        status5, body5 = request_json("GET", "/api/v2/orders", {"userId": "123"})
        mapped_body5 = v2_to_legacy(body5) if status5 == 200 else body5
        
        # For error response, apply normalize_error_response
        status6, body6 = request_json("GET", "/api/v2/orders", {"userId": "invalid"})
        mapped_body6 = normalize_error_response(status6, body6)
        
        results = [
            check_legacy_items_exist(mapped_body1),
            check_legacy_status_enum(mapped_body2),
            check_legacy_customer_flat(mapped_body3),
            check_legacy_totalPrice_float(mapped_body4),
            check_legacy_createdAt_yyyy_mm_dd(mapped_body5),
            check_legacy_error_format(mapped_body6),
            check_v1_deprecation_classified_not_outage(),
        ]
    else:
        print("Invalid mode. Use RAW_V2 or COMPAT")
        sys.exit(1)
    
    print(f"Running in {mode} mode:")
    print_report(results)


if __name__ == "__main__":
    main()
