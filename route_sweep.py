"""Enumerate the signed-coefficient route scenarios using the candidate selector."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from math import comb
from pathlib import Path
import sys
from time import perf_counter


ROUTES = 4
GATES = ("contract", "policy", "ready", "domain", "resources")
WIDTH = ROUTES * len(GATES)
ROUTE_MASK = (1 << ROUTES) - 1
SCENARIOS = 1 << WIDTH
STABLE_REQUESTS = 4096


def load_selector():
    core = Path(__file__).resolve().parent / "web" / "core"
    path = core / "route_cells.py"
    source = path.read_bytes()
    sys.path.insert(0, str(core))
    spec = spec_from_file_location("route_cells", path)
    selector = module_from_spec(spec)
    sys.modules[spec.name] = selector
    exec(compile(source, str(path), "exec"), selector.__dict__)
    return selector, hashlib.sha256(source).hexdigest()


def exhaustive(selector):
    counts = Counter()
    winners = Counter()
    digest = hashlib.sha256()
    shifts = range(0, WIDTH, ROUTES)
    for pattern in range(SCENARIOS):
        gate_masks = tuple((pattern >> shift) & ROUTE_MASK for shift in shifts)
        permitted = tuple(
            route for route in range(ROUTES)
            if all((gate >> route) % 2 for gate in gate_masks)
        )
        expected_mask = sum(2**route for route in permitted)
        cursor = pattern % ROUTES
        expected = min(permitted, key=lambda route: (route - cursor) % ROUTES, default=None)
        actual_mask = selector.eligible_mask(*gate_masks)
        chosen = selector.pick_index(actual_mask, cursor)
        if actual_mask != expected_mask or chosen != expected:
            raise AssertionError((pattern, gate_masks, cursor, expected_mask, expected, actual_mask, chosen))
        counts[actual_mask] += 1
        winners[chosen] += 1
        digest.update(bytes((actual_mask, ROUTES if chosen is None else chosen)))

    # For each permitted route exactly one of its 32 sign vectors works.
    rejected_vectors = (1 << len(GATES)) - 1
    by_cardinality = {}
    for eligible_count in range(ROUTES + 1):
        observed = sum(counts[mask] for mask in range(ROUTE_MASK + 1) if mask.bit_count() == eligible_count)
        expected = comb(ROUTES, eligible_count) * rejected_vectors ** (ROUTES - eligible_count)
        if observed != expected:
            raise AssertionError((eligible_count, observed, expected))
        by_cardinality[str(eligible_count)] = observed
    for mask in range(ROUTE_MASK + 1):
        expected = rejected_vectors ** (ROUTES - mask.bit_count())
        if counts[mask] != expected:
            raise AssertionError((mask, counts[mask], expected))

    return {
        "scenarios_checked": SCENARIOS,
        "scenarios_with_a_route": SCENARIOS - counts[0],
        "scenarios_with_no_route": counts[0],
        "scenario_counts_by_eligible_routes": by_cardinality,
        "chosen_counts_by_route_index": [winners[route] for route in range(ROUTES)],
        "oracle_mismatches": 0,
        "result_sha256": digest.hexdigest(),
    }


def fairness(selector):
    four_way = None
    max_gap = 0
    for mask in range(1, ROUTE_MASK + 1):
        permitted = tuple(route for route in range(ROUTES) if (mask >> route) % 2)
        rotation = selector.Rotation(tuple(range(ROUTES)))
        visits = [0] * ROUTES
        for sequence in range(STABLE_REQUESTS):
            chosen = rotation.choose(mask)
            if chosen != permitted[sequence % len(permitted)]:
                raise AssertionError((mask, sequence, chosen, permitted))
            visits[chosen] += 1
        counts = [visits[route] for route in permitted]
        max_gap = max(max_gap, max(counts) - min(counts))
        if mask == ROUTE_MASK:
            four_way = visits
    schedule = (0, 1, 0, 2)
    weighted = selector.Rotation(schedule)
    weighted_visits = [0] * 3
    for sequence in range(STABLE_REQUESTS):
        chosen = weighted.choose(0b111)
        if chosen != schedule[sequence % len(schedule)]:
            raise AssertionError((schedule, sequence, chosen))
        weighted_visits[chosen] += 1
    return {
        "stable_eligible_sets_checked": ROUTE_MASK,
        "requests_per_set": STABLE_REQUESTS,
        "all_four_fixed_priority_counts": [STABLE_REQUESTS, 0, 0, 0],
        "all_four_alternating_counts": four_way,
        "max_count_gap_among_eligible_routes": max_gap,
        "weighted_schedule": schedule,
        "weighted_schedule_counts": weighted_visits,
    }


def main():
    selector, pinned_sha = load_selector()
    started = perf_counter()
    results = exhaustive(selector)
    stable_results = fairness(selector)
    if hashlib.sha256(Path(selector.__file__).read_bytes()).hexdigest() != pinned_sha:
        raise AssertionError("Selector changed during the sweep")
    print(json.dumps({
        "schema": "router.route-alternation-signed-sweep.v1",
        "scope": "offline_boolean_scenarios_four_synthetic_independent_routes",
        "equation_family": "x^20 + sum(s_k * x^k for k=0..19), s_k in {-1,+1}",
        "coefficient_mapping": {
            "bit": "4 * gate_index + route_index",
            "negative": "gate closed",
            "positive": "gate open",
            "gate_order": GATES,
        },
        "selector_sha256": pinned_sha,
        **results,
        "fairness": stable_results,
        "models_called": 0,
        "external_calls": 0,
        "elapsed_seconds": round(perf_counter() - started, 3),
    }, indent=2))


if __name__ == "__main__":
    main()
