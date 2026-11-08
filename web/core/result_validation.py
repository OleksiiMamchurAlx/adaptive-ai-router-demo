"""Independent, no-effect oracle for one bounded task; not a general LLM judge.

Matches integer open_ids to supplied items in input order. No network, executor,
DB writes, model voting, source authentication or automatic retry is provided.
"""
from __future__ import annotations

import hashlib
import json

VALIDATOR_REVISION = "open-items.exact.v1"
MAX_OUTPUT_CHARS = 20000
MAX_ITEMS = 1000


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError("NONFINITE_JSON_CONSTANT")


def _inputs(items):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError("BOUNDED_ITEM_LIST_REQUIRED")
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"id", "state"}
                or type(item["id"]) is not int or not 0 <= item["id"] <= 2**31 - 1
                or not isinstance(item["state"], str)
                or item["state"] not in {"open", "closed", "pending"}):
            raise ValueError("INVALID_ITEM")
        if item["id"] in seen:
            raise ValueError("DUPLICATE_INPUT_ID")
        seen.add(item["id"])
    return [item["id"] for item in items if item["state"] == "open"]


def validate_open_items(items, raw_output, *, execution_state="succeeded",
                        validator_available=True):
    """An ACCEPT only means this output matches these supplied synthetic inputs.

    Runtime provenance, input authenticity and learning eligibility are separate.
    Never coerce ERROR/NOT_RUN to a negative training label.
    """
    receipt = {
        "schema": "router.bounded-validation.v1",
        "validator_revision": VALIDATOR_REVISION,
        "scope": "select_integer_open_ids_in_supplied_input_order",
        "execution_state": execution_state if isinstance(execution_state, str) else "unknown",
        "input_sha256": None,
        "output_sha256": None,
        "verdict": "ERROR", "task_accepted": None,
        "reason": None, "strict_format_pass": None, "semantic_pass": None,
        "can_execute": False, "authority_granted": False, "automatic_retry": False,
        "training_eligible": False,
        "eligibility_reason": "NO_AUTHENTICATED_RUN_OR_DATASET_BINDING",
    }
    if execution_state == "not_run":
        receipt.update(verdict="NOT_RUN", reason="EXECUTOR_NOT_RUN")
        return receipt
    if execution_state != "succeeded":
        receipt["reason"] = "EXECUTION_UNAVAILABLE_OR_UNKNOWN"
        return receipt
    if validator_available is not True:
        receipt["reason"] = "VALIDATOR_UNAVAILABLE"
        return receipt
    try:
        expected = _inputs(items)
        receipt["input_sha256"] = _hash({"items": items, "order": "input",
            "validator_revision": VALIDATOR_REVISION})
    except (TypeError, ValueError):
        receipt["reason"] = "INVALID_OR_AMBIGUOUS_INPUT"
        return receipt
    try:
        if not isinstance(raw_output, str) or len(raw_output) > MAX_OUTPUT_CHARS:
            raise ValueError("BOUNDED_JSON_STRING_REQUIRED")
        receipt["output_sha256"] = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
        output = json.loads(raw_output, object_pairs_hook=_unique_object,
            parse_constant=_reject_constant)
        if (not isinstance(output, dict) or set(output) != {"open_ids"}
                or not isinstance(output["open_ids"], list)
                or len(output["open_ids"]) > MAX_ITEMS
                or any(type(v) is not int or not 0 <= v <= 2**31 - 1 for v in output["open_ids"])):
            raise ValueError("OUTPUT_SCHEMA_MISMATCH")
    except (TypeError, ValueError, RecursionError):
        receipt.update(verdict="REJECT", task_accepted=False,
            reason="STRICT_JSON_CONTRACT_FAILED", strict_format_pass=False)
        return receipt
    correct = output["open_ids"] == expected
    receipt.update(verdict="ACCEPT" if correct else "REJECT", task_accepted=correct,
        strict_format_pass=True, semantic_pass=correct,
        reason="EXACT_MATCH" if correct else "ORACLE_MISMATCH")
    return receipt
