"""Bounded durable workflow for the installed Router's numeric executor.

The workflow lives in the existing RoutingTracker SQLite database. It does not
replace the provider router or grant arbitrary code, network, or shell access.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from experience_store import calculate
from numeric_validation import validate_numeric
from tracking_core import RoutingTracker

ENGINE_VERSION = "native-numeric-workflow.v1"
OPERATIONS = frozenset({"sum", "mean", "min", "max", "range"})


class _BoundedOutput:
    """Discard raw executor output while recording bounded audit metadata."""

    def __init__(self, limit_chars: int = 8192) -> None:
        self.limit_chars = limit_chars
        self.total_chars = 0
        self.hash = hashlib.sha256()

    def write(self, value: str) -> int:
        self.total_chars += len(value)
        # Do not retain untrusted stdout or build another huge byte buffer.
        for offset in range(0, len(value), 4096):
            self.hash.update(value[offset:offset + 4096].encode("utf-8", errors="replace"))
        return len(value)

    def flush(self) -> None:
        pass

    def receipt(self) -> dict[str, Any]:
        return {"total_chars": self.total_chars,
                "retained_chars": 0,
                "truncated": self.total_chars > self.limit_chars,
                "content_policy": "digest_only",
                "sha256": self.hash.hexdigest()}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    operation: str
    values: tuple[float, ...]
    idempotency_key: str
    parent_goal_id: str = "numeric-qa"
    task_revision: int = 1
    schema_version: int = 1
    capabilities: tuple[str, ...] = ("local_deterministic",)
    dependencies: tuple[dict[str, Any], ...] = ()
    priority: int = 0
    deadline_epoch: float | None = None
    policy_version: str = "native-local-v1"
    validation_contract: str = "numeric-v1"
    privacy_class: str = "local_numeric"
    max_attempts: int = 3
    cancelled: bool = False
    source: str = "real"
    split: str = "production"
    dataset_id: str = "production"

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", self.task_id):
            raise ValueError("task_id must be a bounded opaque identifier")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", self.idempotency_key):
            raise ValueError("idempotency_key must be a bounded opaque identifier")
        for label in (self.parent_goal_id, self.policy_version, self.dataset_id):
            if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,120}", label):
                raise ValueError("task labels must be bounded opaque identifiers")
        if not self.capabilities or set(self.capabilities) != {"local_deterministic"}:
            raise ValueError("only the bounded local deterministic capability is enabled")
        if self.schema_version != 1 or self.task_revision < 1:
            raise ValueError("unsupported task schema or revision")
        if self.operation not in OPERATIONS or not 1 <= len(self.values) <= 4096:
            raise ValueError("unsupported numeric operation or list size")
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e100 for v in self.values):
            raise ValueError("bounded finite numeric values required")
        if type(self.priority) is not int or not -100 <= self.priority <= 100:
            raise ValueError("priority outside allowed bounds")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("attempt budget outside allowed bounds")
        if self.validation_contract != "numeric-v1" or self.privacy_class != "local_numeric":
            raise ValueError("unsupported validation or privacy contract")
        if self.source not in {"real", "synthetic"} or self.split not in {"production", "dev", "holdout"}:
            raise ValueError("unsupported provenance")
        if self.source == "real" and self.dataset_id != "production":
            raise ValueError("real input must use the production scope")
        if self.source == "synthetic" and self.dataset_id == "production":
            raise ValueError("synthetic input needs an isolated dataset")
        if self.deadline_epoch is not None and (type(self.deadline_epoch) not in (int, float) or not math.isfinite(self.deadline_epoch)):
            raise ValueError("invalid deadline")
        for dep in self.dependencies:
            if set(dep) != {"task_id", "task_revision", "input_digest"} or not re.fullmatch(r"[0-9a-f]{64}", dep["input_digest"]):
                raise ValueError("dependency must name a task revision and input digest")

    @property
    def input_digest(self) -> str:
        return _digest({"operation": self.operation, "values": self.values})

    def record(self) -> dict[str, Any]:
        return {**asdict(self), "input_digest": self.input_digest, "engine_version": ENGINE_VERSION}


class NativeWorkflow:
    def __init__(self, db_path: str | Path, *, lease_seconds: float = 30.0,
                 artifact_limit_bytes: int = 512 * 1024 * 1024,
                 min_free_bytes: int | None = None) -> None:
        self.tracker = RoutingTracker(db_path)
        self.lease_seconds = max(0.2, float(lease_seconds))
        self.artifact_limit_bytes = artifact_limit_bytes
        self.min_free_bytes = (50 * 1024 ** 3 if self.tracker.path.drive.upper() == "E:"
                               else 0) if min_free_bytes is None else min_free_bytes
        self._ensure()

    def _resource_reason(self) -> str | None:
        database_bytes = sum(path.stat().st_size for path in (
            self.tracker.path, Path(str(self.tracker.path) + "-wal"),
            Path(str(self.tracker.path) + "-shm")) if path.exists())
        if database_bytes > self.artifact_limit_bytes:
            return "ARTIFACT_LIMIT"
        if shutil.disk_usage(self.tracker.path.parent).free < self.min_free_bytes:
            return "DISK_FREE_BELOW_FLOOR"
        return None

    def _ensure(self) -> None:
        with self.tracker._write_connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_tasks (
                    task_id TEXT NOT NULL, task_revision INTEGER NOT NULL,
                    envelope_json TEXT NOT NULL, input_digest TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, engine_version TEXT NOT NULL,
                    priority INTEGER NOT NULL, created_at REAL NOT NULL,
                    state TEXT NOT NULL, execution_status TEXT NOT NULL,
                    validation_verdict TEXT NOT NULL, publication_status TEXT NOT NULL,
                    reason_code TEXT, lease_owner TEXT, lease_expires REAL,
                    fence INTEGER NOT NULL DEFAULT 0, attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_failure TEXT, same_failure_count INTEGER NOT NULL DEFAULT 0,
                    effect_key TEXT NOT NULL UNIQUE, result_json TEXT, result_digest TEXT,
                    experience_id TEXT, PRIMARY KEY(task_id,task_revision));
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL, task_revision INTEGER NOT NULL,
                    kind TEXT NOT NULL, detail_json TEXT NOT NULL, recorded_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_effects (
                    effect_key TEXT PRIMARY KEY, state TEXT NOT NULL,
                    result_json TEXT, result_digest TEXT,
                    committed_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS workflow_experience (
                    example_id TEXT PRIMARY KEY, conditions_digest TEXT NOT NULL,
                    source TEXT NOT NULL, split TEXT NOT NULL, dataset_id TEXT NOT NULL,
                    task_id TEXT NOT NULL, task_revision INTEGER NOT NULL,
                    validator TEXT NOT NULL, result_digest TEXT NOT NULL,
                    created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_workflow_experience_conditions
                    ON workflow_experience(conditions_digest,created_at);
            """)

    @staticmethod
    def _event(db: Any, env: TaskEnvelope, kind: str, detail: dict[str, Any]) -> None:
        db.execute("INSERT INTO workflow_events(task_id,task_revision,kind,detail_json,recorded_at) VALUES (?,?,?,?,?)",
                   (env.task_id, env.task_revision, kind, _json(detail), time.time()))

    @staticmethod
    def _envelope(row: Any) -> TaskEnvelope:
        data = json.loads(row["envelope_json"])
        data.pop("input_digest")
        data.pop("engine_version")
        return TaskEnvelope(**data)

    @staticmethod
    def _conditions(env: TaskEnvelope) -> str:
        return _digest({"source": env.source, "dataset_id": env.dataset_id,
                        "operation": env.operation, "size_bucket": (len(env.values) - 1) // 8,
                        "policy_version": env.policy_version, "validation_contract": env.validation_contract,
                        "privacy_class": env.privacy_class})

    def submit(self, env: TaskEnvelope) -> dict[str, Any]:
        effect_key = _digest({"task_id": env.task_id, "revision": env.task_revision,
                              "input_digest": env.input_digest, "idempotency_key": env.idempotency_key})
        with self.tracker._write_connection() as db:
            existing = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                  (env.task_id, env.task_revision)).fetchone()
            if existing:
                if existing["envelope_json"] != _json(env.record()):
                    raise ValueError("existing task revision has different input or contract")
                return self._view(db, existing)
            reused = db.execute("SELECT task_id,task_revision FROM workflow_tasks WHERE idempotency_key=?",
                                (env.idempotency_key,)).fetchone()
            if reused:
                raise ValueError("idempotency key belongs to a different task revision")
            db.execute("""INSERT INTO workflow_tasks(task_id,task_revision,envelope_json,input_digest,
                idempotency_key,engine_version,priority,created_at,state,execution_status,
                validation_verdict,publication_status,effect_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (env.task_id, env.task_revision, _json(env.record()), env.input_digest,
                 env.idempotency_key, ENGINE_VERSION, env.priority, time.time(), "PENDING",
                 "NOT_STARTED", "NOT_RUN", "NOT_PUBLISHED", effect_key))
            self._event(db, env, "TASK_ACCEPTED", {"input_digest": env.input_digest})
            return self._view(db, db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                             (env.task_id, env.task_revision)).fetchone())

    @staticmethod
    def _view(db: Any, row: Any) -> dict[str, Any]:
        envelope = json.loads(row["envelope_json"])
        effect = db.execute("SELECT state,committed_count FROM workflow_effects WHERE effect_key=?",
                            (row["effect_key"],)).fetchone()
        example = db.execute("""SELECT source,split,dataset_id,task_id,task_revision,validator
            FROM workflow_experience WHERE example_id=?""", (row["experience_id"],)).fetchone() if row["experience_id"] else None
        return {key: row[key] for key in ("task_id", "task_revision", "input_digest", "state",
                "execution_status", "validation_verdict", "publication_status", "reason_code",
                "attempt_count", "result_digest", "experience_id")} | {
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                    "provenance": {**{key: envelope[key] for key in ("source", "split", "dataset_id")},
                                   "origin": "client_declared"},
                    "route": {"provider": "local_deterministic",
                              "reason_codes": ["bounded_numeric_contract"] +
                                  (["validated_experience_reference"] if example else []),
                              "model": None},
                    "experience_provenance": dict(example) if example else None,
                    "effect_state": effect["state"] if effect else None,
                    "committed_effect_count": effect["committed_count"] if effect else 0}

    def status(self, task_id: str, revision: int = 1) -> dict[str, Any]:
        with self.tracker._connection() as db:
            row = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                             (task_id, revision)).fetchone()
            if not row:
                raise KeyError(task_id)
            return self._view(db, row)

    @staticmethod
    def _ready_reason(db: Any, row: Any, env: TaskEnvelope, now: float) -> str | None:
        effect = db.execute("SELECT state FROM workflow_effects WHERE effect_key=?",
                            (row["effect_key"],)).fetchone()
        committed = bool(effect and effect["state"] == "COMMITTED")
        if row["engine_version"] != ENGINE_VERSION or row["input_digest"] != env.input_digest:
            return "VERSION_OR_INPUT_DRIFT"
        if env.cancelled or row["state"] == "CANCELLED":
            return "CANCELLED"
        if env.deadline_epoch is not None and now > env.deadline_epoch:
            return "DEADLINE_EXPIRED"
        if "local_deterministic" not in env.capabilities:
            return "CAPABILITY_UNAVAILABLE"
        if row["attempt_count"] >= env.max_attempts and not committed:
            return "ATTEMPT_BUDGET_EXHAUSTED"
        if row["state"] == "RUNNING" and row["lease_expires"] and row["lease_expires"] > now:
            return "LEASE_HELD"
        for dep in env.dependencies:
            parent = db.execute("SELECT state,validation_verdict,input_digest FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                (dep["task_id"], dep["task_revision"])).fetchone()
            if not parent or parent["state"] != "COMPLETE" or parent["validation_verdict"] != "ACCEPT":
                return "DEPENDENCY_NOT_ACCEPTED"
            if parent["input_digest"] != dep["input_digest"]:
                return "DEPENDENCY_DIGEST_DRIFT"
        return None

    def ready(self) -> list[dict[str, Any]]:
        if self._resource_reason():
            return []
        now = time.time()
        with self.tracker._connection() as db:
            rows = db.execute("SELECT * FROM workflow_tasks WHERE state IN ('PENDING','RUNNING')").fetchall()
            ready = []
            for row in rows:
                env = self._envelope(row)
                reason = self._ready_reason(db, row, env, now)
                if reason is None:
                    age_boost = min(200, int((now - row["created_at"]) / 30))
                    ready.append({"task_id": env.task_id, "task_revision": env.task_revision,
                                  "priority": env.priority, "effective_priority": env.priority + age_boost,
                                  "route": "local_deterministic", "route_reason": "bounded_numeric_contract",
                                  "created_at": row["created_at"]})
            return sorted(ready, key=lambda x: (-x["effective_priority"], x["created_at"], x["task_id"]))

    def run_next(self, **kwargs: Any) -> dict[str, Any] | None:
        ready = self.ready()
        return self.run(ready[0]["task_id"], ready[0]["task_revision"], **kwargs) if ready else None

    def run(self, task_id: str, revision: int = 1, *, memory_enabled: bool = True,
            executor: Callable[[str, list[float]], object] | None = None,
            simulate_interrupt_before_effect: bool = False,
            simulate_interrupt_after_effect: bool = False) -> dict[str, Any]:
        if (simulate_interrupt_before_effect or simulate_interrupt_after_effect) and os.environ.get("ADAPTIVE_ROUTER_WORKFLOW_TEST_MODE") != "1":
            raise ValueError("interruption injection is available only in an isolated test process")
        owner = uuid.uuid4().hex
        now = time.time()
        with self.tracker._write_connection() as db:
            row = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                             (task_id, revision)).fetchone()
            if not row:
                raise KeyError(task_id)
            if row["state"] in {"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"}:
                return self._view(db, row)
            env = self._envelope(row)
            reason = self._resource_reason() or self._ready_reason(db, row, env, now)
            if reason:
                if reason == "LEASE_HELD" or reason == "DEPENDENCY_NOT_ACCEPTED":
                    return {**self._view(db, row), "waiting_reason": reason}
                state = "CANCELLED" if reason == "CANCELLED" else "BLOCKED"
                db.execute("UPDATE workflow_tasks SET state=?,reason_code=? WHERE task_id=? AND task_revision=?",
                           (state, reason, task_id, revision))
                self._event(db, env, state, {"reason_code": reason})
                updated = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                     (task_id, revision)).fetchone()
                return self._view(db, updated)
            fence = row["fence"] + 1
            effect = db.execute("SELECT state FROM workflow_effects WHERE effect_key=?",
                                (row["effect_key"],)).fetchone()
            resume_committed = bool(effect and effect["state"] == "COMMITTED")
            attempt_increment = 0 if resume_committed else 1
            db.execute("""UPDATE workflow_tasks SET state='RUNNING',execution_status='RUNNING',
                lease_owner=?,lease_expires=?,fence=?,attempt_count=attempt_count+?
                WHERE task_id=? AND task_revision=?""",
                (owner, now + self.lease_seconds, fence, attempt_increment, task_id, revision))
            example_id = None
            if memory_enabled and env.split != "holdout":
                example = db.execute("""SELECT example_id FROM workflow_experience
                    WHERE conditions_digest=? AND source=? AND dataset_id=?
                    ORDER BY created_at DESC,example_id DESC LIMIT 1""",
                    (self._conditions(env), env.source, env.dataset_id)).fetchone()
                example_id = example["example_id"] if example else None
            db.execute("UPDATE workflow_tasks SET experience_id=? WHERE task_id=? AND task_revision=?",
                       (example_id, task_id, revision))
            self._event(db, env, "ROUTE_SELECTED", {"provider": "local_deterministic",
                "reason": "bounded_numeric_contract", "experience_id": example_id,
                "fence": fence, "attempt": row["attempt_count"] + attempt_increment,
                "resumed_committed_effect": resume_committed})
            effect_key = row["effect_key"]

        try:
            with self.tracker._write_connection() as db:
                effect = db.execute("SELECT * FROM workflow_effects WHERE effect_key=?", (effect_key,)).fetchone()
                if effect and effect["state"] == "COMMITTED":
                    result = json.loads(effect["result_json"])
                else:
                    db.execute("INSERT OR IGNORE INTO workflow_effects(effect_key,state) VALUES (?, 'INTENT')",
                               (effect_key,))
                    self._event(db, env, "EFFECT_INTENT", {"effect_key": effect_key, "pure_function": True})
                    result = None
            if result is None:
                if simulate_interrupt_before_effect:
                    os._exit(22)
                stdout = _BoundedOutput()
                stderr = _BoundedOutput()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = (executor or calculate)(env.operation, list(env.values))
                with self.tracker._write_connection() as db:
                    self._event(db, env, "EXECUTOR_OUTPUT", {"stdout": stdout.receipt(),
                        "stderr": stderr.receipt()})
                result_json = _json(result)
                result_digest = _digest(result)
                with self.tracker._write_connection() as db:
                    current = db.execute("SELECT fence,lease_owner FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                         (task_id, revision)).fetchone()
                    if current["fence"] != fence or current["lease_owner"] != owner:
                        return {"task_id": task_id, "state": "FENCED"}
                    db.execute("""UPDATE workflow_effects SET state='COMMITTED',result_json=?,result_digest=?,
                        committed_count=committed_count+1 WHERE effect_key=? AND state='INTENT'""",
                        (result_json, result_digest, effect_key))
                    db.execute("""UPDATE workflow_tasks SET execution_status='SUCCEEDED',result_json=?,result_digest=?
                        WHERE task_id=? AND task_revision=?""", (result_json, result_digest, task_id, revision))
                    self._event(db, env, "EFFECT_COMMITTED", {"result_digest": result_digest})
                if simulate_interrupt_after_effect:
                    os._exit(23)  # Test-only process exit; never aimed at the installed service.
            accepted, verdict_reason = validate_numeric(env.operation, env.values, result)
            with self.tracker._write_connection() as db:
                current = db.execute("SELECT fence,lease_owner FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                     (task_id, revision)).fetchone()
                if current["fence"] != fence or current["lease_owner"] != owner:
                    return {"task_id": task_id, "state": "FENCED"}
                result_digest = _digest(result)
                state = "COMPLETE" if accepted else "FAILED"
                db.execute("""UPDATE workflow_tasks SET state=?,execution_status='SUCCEEDED',
                    validation_verdict=?,reason_code=?,lease_owner=NULL,lease_expires=NULL,
                    result_json=?,result_digest=? WHERE task_id=? AND task_revision=?""",
                    (state, "ACCEPT" if accepted else "REJECT", verdict_reason,
                     _json(result), result_digest, task_id, revision))
                self._event(db, env, "VALIDATION_" + ("ACCEPT" if accepted else "REJECT"),
                            {"validator": "numeric_validation.validate_numeric", "reason_code": verdict_reason,
                             "result_digest": result_digest})
                if accepted and memory_enabled and env.split != "holdout":
                    example_id = _digest({"task": task_id, "revision": revision, "result_digest": result_digest})
                    db.execute("""INSERT OR IGNORE INTO workflow_experience
                        (example_id,conditions_digest,source,split,dataset_id,task_id,task_revision,
                         validator,result_digest,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (example_id, self._conditions(env), env.source, env.split, env.dataset_id,
                         task_id, revision, "numeric_validation.validate_numeric", result_digest, time.time()))
            return self.status(task_id, revision)
        except Exception as error:
            fingerprint = _digest({"type": type(error).__name__, "message": str(error)[:160]})
            with self.tracker._write_connection() as db:
                row = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                                 (task_id, revision)).fetchone()
                if row["fence"] == fence and row["lease_owner"] == owner:
                    repeats = row["same_failure_count"] + 1 if row["last_failure"] == fingerprint else 1
                    final = repeats >= 2 or row["attempt_count"] >= env.max_attempts
                    db.execute("""UPDATE workflow_tasks SET state=?,execution_status='FAILED',
                        reason_code=?,last_failure=?,same_failure_count=?,lease_owner=NULL,lease_expires=NULL
                        WHERE task_id=? AND task_revision=?""",
                        ("FAILED" if final else "PENDING", type(error).__name__.upper(),
                         fingerprint, repeats, task_id, revision))
                    self._event(db, env, "EXECUTION_ERROR", {"category": type(error).__name__,
                        "fingerprint": fingerprint, "retry_allowed": not final})
            return self.status(task_id, revision)

    def cancel(self, task_id: str, revision: int = 1) -> dict[str, Any]:
        with self.tracker._write_connection() as db:
            row = db.execute("SELECT * FROM workflow_tasks WHERE task_id=? AND task_revision=?",
                             (task_id, revision)).fetchone()
            if not row:
                raise KeyError(task_id)
            if row["state"] in {"PENDING", "BLOCKED"}:
                env = self._envelope(row)
                db.execute("UPDATE workflow_tasks SET state='CANCELLED',reason_code='OWNER_CANCELLED' WHERE task_id=? AND task_revision=?",
                           (task_id, revision))
                self._event(db, env, "CANCELLED", {"reason_code": "OWNER_CANCELLED"})
            elif row["state"] == "RUNNING":
                raise RuntimeError("in-flight cancellation requires executor cooperation")
        return self.status(task_id, revision)
