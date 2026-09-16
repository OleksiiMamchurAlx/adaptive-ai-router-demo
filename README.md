# Adaptive AI Router — Reliability & Evidence Demo

**Python + SQLite · offline demo · structured validation · controlled recovery**

A small, inspectable part of an AI-assisted automation project: distinguish an executor answering from a task actually passing validation, record the outcome, and recover a committed result without repeating the numeric tool.

This is a portfolio prototype, not a production SRE platform or a general-purpose autonomous agent. No account, API key, local model or running router is required.

## Start in 60 seconds

Requires Python 3.11 or newer; standard library only. From the repository directory:

```console
python -m unittest discover -v
python demo.py self-test
```

The demo runs in an automatically cleaned temporary directory. It selects a deterministic numeric tool, computes a mean, checks it against an exact oracle, commits a validation and event to SQLite, deliberately exits with code 73, then resumes export twice. The coordinator expects that worker exit; the overall self-test returns success.

**Test scope:** 16 inherited evidence-library tests, 4 portable-demo tests and 6 planning-metadata checks. These are isolated checks, not a percentage of production reliability or Unreal gameplay tests. See [current verification](project.json); [earlier results](evidence/verification.json) remain historical.

## What I owned / how AI helped

Project owner; AI-assisted implementation, testing and documentation. I defined the goals, spending boundaries and acceptance criteria, and challenged misleading success claims. AI assisted with code, test execution and technical writing. The work does not imply unaided authorship of every line.

I use AI tools as engineering assistants. I define project goals, constraints and acceptance criteria, review outputs, preserve failures and limitations, and validate results through tests or reproducible evidence.

## Design

```text
structured task -> explicit numeric route -> tool result -> exact validation
                                                      -> SQL commit
                                                      -> deliberate worker exit
                                                      -> resume export, no repeated tool
```

- [evidence.py](evidence.py): small evidence library, transactions, backup and event export.
- [schema.sql](schema.sql): readable schema; `ACCEPT` must mean true, `REJECT` false, verifier errors remain unknown.
- [demo.py](demo.py): portable controlled-recovery example.
- [test_evidence.py](test_evidence.py) and [test_demo.py](test_demo.py): positive, negative and recovery checks.
- [Systems diagnostic approach](docs/SYSTEMS_DIAGNOSTICS.md): how the same discipline supports troubleshooting.
- [Evidence boundaries](docs/EVIDENCE_BOUNDARIES.md): prior private experiment versus this runnable public demo.

## Evidence and failures

The earlier local project exercised a fresh MCP numeric tool, one committed result and two resume/export operations. The public demo is a **new, dependency-free reproduction of that bounded pattern**, not the original MCP runtime. Its results are recorded separately.

Earlier testing caught an unclosed SQLite connection during Windows cleanup and a NULL-consistency issue in validation constraints. Both became regression checks. A local-model draft also required correction; a generated response was not automatically treated as accepted evidence.

## Limitations

- Recovery is tested **after commit**, not in the middle of an arbitrary external side effect. An uncertain `INFLIGHT` state stops for reconciliation.
- There is no Windows reboot recovery, microphone capture, browser observation or operating-system control in this repository.
- Event IDs suppress duplicate inserts; different payloads reusing an ID are not reconciled. This is not a general exactly-once guarantee.
- A previous small routing-policy comparison remains inconclusive. No model-weight training or routing-superiority claim is made.
- No cloud providers are invoked; this demo does not measure cloud savings or prove a production resource budget.
- Use new demo databases only. The library is not a production migration tool; never point it at a working router database.

## Demonstrated skill areas

Reliability-oriented automation, QA test design, Python/SQL, validation semantics, failure analysis, reproducible evidence and explicit acceptance boundaries.

Raw databases, runtime identifiers, internal configuration, personal documents and third-party binaries are intentionally excluded. [Rights and attribution](RIGHTS_AND_ATTRIBUTION.md). [Publication manifest](PUBLICATION_MANIFEST.json).

## Related planning evidence

[Future Game Automation / Unreal R&D](docs/FUTURE_RD_METHOD.md) is a small, separately labelled architecture-planning case: task dependencies, acceptance criteria, telemetry and bounded repair loops. It is not a shipped game or a verified production Unreal system. [Machine-readable summary](projects/future-unreal-automation-rd.json).
