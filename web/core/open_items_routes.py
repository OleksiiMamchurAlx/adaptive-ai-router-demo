"""Two local implementations of the exact open-ID contract."""

import json
import sqlite3
import threading
from contextlib import closing

from result_validation import _inputs, validate_open_items
from route_cells import Rotation, domain_mask, eligible_mask


ROUTES = ("open_items_python", "open_items_sqlite")
DEPENDENCIES = (
    frozenset({"host", "validator", "python_filter"}),
    frozenset({"host", "validator", "sqlite_engine"}),
)
ALL_ROUTES = (1 << len(ROUTES)) - 1
SCHEDULE = (0, 0, 0, 1)


def select_with_python(items):
    return {"open_ids": [item["id"] for item in items if item["state"] == "open"]}


def select_with_sqlite(items):
    with closing(sqlite3.connect(":memory:")) as database:
        database.execute("CREATE TABLE items (ordinal INTEGER PRIMARY KEY, id INTEGER NOT NULL, state TEXT NOT NULL)")
        database.executemany(
            "INSERT INTO items VALUES (?, ?, ?)",
            ((index, item["id"], item["state"]) for index, item in enumerate(items)),
        )
        return {"open_ids": [
            row[0] for row in database.execute("SELECT id FROM items WHERE state = 'open' ORDER BY ordinal")
        ]}


def _probe_python():
    return select_with_python([{"id": 4, "state": "closed"}, {"id": 9, "state": "open"}]) == {"open_ids": [9]}


def _probe_sqlite():
    return select_with_sqlite([{"id": 4, "state": "closed"}, {"id": 9, "state": "open"}]) == {"open_ids": [9]}


def _receipt(verdict, reason, attempts, *, route=None, result=None):
    return {
        "verdict": verdict,
        "task_accepted": True if verdict == "ACCEPT" else None,
        "route": route,
        "result": result,
        "attempts": attempts,
        "reason": reason,
    }


class OpenItemsRouter:
    def __init__(self, schedule=SCHEDULE):
        self._rotation = Rotation(schedule)
        self._lock = threading.Lock()

    def _probe_recovery(self):
        for index, probe in enumerate((_probe_python, _probe_sqlite)):
            if not self._rotation.recovering(index):
                continue
            try:
                healthy = probe() is True
            except MemoryError:
                raise
            except sqlite3.Error as error:
                if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_NOMEM:
                    raise MemoryError from error
                healthy = False
            except Exception:
                healthy = False
            self._rotation.observe(index, healthy)

    def run(self, items):
        attempts = []
        try:
            _inputs(items)
            snapshot = [item.copy() for item in items]
        except (TypeError, ValueError):
            return _receipt("NOT_RUN", "INVALID_OR_AMBIGUOUS_INPUT", attempts)
        except MemoryError:
            return _receipt("ERROR", "SHARED_MEMORY_UNAVAILABLE", attempts)
        except Exception:
            return _receipt("ERROR", "SHARED_INPUT_CHECK_UNAVAILABLE", attempts)

        try:
            with self._lock:
                self._probe_recovery()
        except MemoryError:
            return _receipt("ERROR", "SHARED_MEMORY_UNAVAILABLE", attempts)
        blocked = frozenset()
        for _ in ROUTES:
            with self._lock:
                eligible = eligible_mask(
                    ALL_ROUTES, ALL_ROUTES, ALL_ROUTES, domain_mask(DEPENDENCIES, blocked), ALL_ROUTES
                )
                index = self._rotation.choose(eligible)
            if index is None:
                break

            route = ROUTES[index]
            attempts.append(route)
            try:
                output = (select_with_python, select_with_sqlite)[index](snapshot)
                raw = json.dumps(output, separators=(",", ":"), allow_nan=False)
            except MemoryError:
                return _receipt("ERROR", "SHARED_MEMORY_UNAVAILABLE", attempts)
            except sqlite3.Error as error:
                if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_NOMEM:
                    return _receipt("ERROR", "SHARED_MEMORY_UNAVAILABLE", attempts)
            except Exception:
                pass
            else:
                try:
                    validation = validate_open_items(snapshot, raw)
                    verdict = validation.get("verdict")
                    if verdict == "ACCEPT" and validation.get("task_accepted") is True:
                        return _receipt("ACCEPT", validation["reason"], attempts, route=route, result=output)
                except Exception:
                    return _receipt("ERROR", "SHARED_VALIDATOR_UNAVAILABLE", attempts)
                if verdict != "REJECT":
                    return _receipt("ERROR", "SHARED_VALIDATOR_UNAVAILABLE", attempts)

            failed_component = ("python_filter", "sqlite_engine")[index]
            blocked = blocked | {failed_component}
            with self._lock:
                self._rotation.observe(index, False)
        return _receipt("NOT_RUN" if not attempts else "ERROR", "NO_QUALIFIED_ROUTE", attempts)


_router = OpenItemsRouter()


def run(items):
    return _router.run(items)
