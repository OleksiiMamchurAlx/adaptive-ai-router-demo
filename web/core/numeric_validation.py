"""Independent numeric contract for the existing deterministic Router executor."""
from __future__ import annotations

from decimal import Decimal, localcontext
from math import isclose, isfinite


def validate_numeric(operation: str, values: tuple[float, ...], actual: object) -> tuple[bool, str]:
    if type(actual) not in (int, float) or not isfinite(actual):
        return False, "NON_NUMERIC_OUTPUT"
    decimal_values = [Decimal(str(value)) for value in values]
    # The executor allows magnitudes up to 1e100. Default Decimal precision
    # would discard a small term before large positive/negative terms cancel.
    with localcontext() as context:
        context.prec = 256
        expected = {
            "sum": lambda: sum(decimal_values),
            "mean": lambda: sum(decimal_values) / len(decimal_values),
            "min": lambda: min(decimal_values),
            "max": lambda: max(decimal_values),
            "range": lambda: max(decimal_values) - min(decimal_values),
        }[operation]()
    if isclose(float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12):
        return True, "NUMERIC_CONTRACT_ACCEPT"
    return False, "NUMERIC_MISMATCH"
