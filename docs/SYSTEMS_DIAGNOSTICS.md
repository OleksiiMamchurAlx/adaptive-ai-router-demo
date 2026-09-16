# Systems & diagnostics

My background includes hands-on Windows endpoint support, PCs and peripherals, local networks and network-connected devices, hardware/electronics troubleshooting, and technical documentation. My previous application materials describe AD/server/SQL testing exposure and assistance with database copying, migration and backup/recovery; those are background statements, not newly benchmarked production-platform credentials.

## A diagnostic approach demonstrated here

1. State the symptom and the expected behavior.
2. Separate a test-harness/environment failure from a product failure.
3. Preserve the first failure before changing one variable.
4. Re-run a bounded scenario with an independent oracle.
5. Record the scope of the fix and what remains untested.

For example, the graphics validation campaign first failed under a child shell's inherited module path. Correcting only that child environment allowed the same four sandbox cases to run. It did not require changing global security or claiming the live game had passed.

In the evidence library, an SQLite transaction context committed successfully but did not close the connection used by Windows cleanup. An explicit close resolved the test-harness failure. The regression test now checks backup restoration and releases the handle.

## Boundaries

This portfolio does not establish production Azure, Kubernetes or observability-platform administration, enterprise macOS support, or end-to-end disaster recovery. The useful demonstrated habit is narrower: isolate, verify, document and preserve the limits of the result.

Project examples were implemented and documented with AI assistance. My goals, constraints and acceptance criteria are distinct from unaided coding proficiency.
