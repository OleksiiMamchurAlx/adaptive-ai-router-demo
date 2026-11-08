from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent / "web" / "core"))
import open_items_routes as routes
from route_example import run_example


class RouteAlternationTests(unittest.TestCase):
    items = [{"id": 9, "state": "open"}, {"id": 2, "state": "open"}]

    def test_public_example_rotates_without_changing_result_order(self):
        runs = run_example()["runs"]
        self.assertEqual([run["route"] for run in runs], [*([routes.ROUTES[0]] * 3), routes.ROUTES[1]])
        for run in runs:
            self.assertEqual(run["verdict"], "ACCEPT")
            self.assertEqual(run["result"], {"open_ids": [9, 2]})
            self.assertEqual(run["attempts"], [run["route"]])

    def test_route_specific_sqlite_failure_can_use_python(self):
        router = routes.OpenItemsRouter(schedule=(1, 0))
        with patch.object(routes, "select_with_sqlite", side_effect=sqlite3.OperationalError("test fixture")):
            result = router.run(self.items)
        self.assertEqual(result["verdict"], "ACCEPT")
        self.assertEqual(result["attempts"], list(reversed(routes.ROUTES)))
        self.assertEqual(result["result"], {"open_ids": [9, 2]})

    def test_failed_route_reenters_after_two_good_probes(self):
        router = routes.OpenItemsRouter(schedule=(0, 1))
        with patch.object(routes, "select_with_python", return_value={"open_ids": [2, 9]}):
            first = router.run(self.items)
        self.assertEqual(first["attempts"], list(routes.ROUTES))
        self.assertEqual(first["route"], routes.ROUTES[1])
        self.assertEqual(router.run(self.items)["route"], routes.ROUTES[1])
        self.assertEqual(router.run(self.items)["route"], routes.ROUTES[0])

    def test_validator_error_stops_before_alternate(self):
        router = routes.OpenItemsRouter()
        with patch.object(routes, "validate_open_items", side_effect=RuntimeError("test fixture")):
            with patch.object(routes, "select_with_sqlite") as alternate:
                result = router.run(self.items)
        alternate.assert_not_called()
        self.assertEqual(result["reason"], "SHARED_VALIDATOR_UNAVAILABLE")
        self.assertIsNone(result["task_accepted"])

    def test_shared_memory_refusal_stops_before_alternate(self):
        router = routes.OpenItemsRouter()
        with patch.object(routes, "select_with_python", side_effect=MemoryError):
            with patch.object(routes, "select_with_sqlite") as alternate:
                result = router.run(self.items)
        alternate.assert_not_called()
        self.assertEqual(result["reason"], "SHARED_MEMORY_UNAVAILABLE")
        self.assertIsNone(result["task_accepted"])

    def test_duplicate_id_does_not_dispatch(self):
        router = routes.OpenItemsRouter()
        result = router.run(self.items * 2)
        self.assertEqual(result["verdict"], "NOT_RUN")
        self.assertEqual(result["attempts"], [])
