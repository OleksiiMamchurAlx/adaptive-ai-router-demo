# Bounded native-core browser demo

This is a public, static-hosted interactive sample. It
runs the accepted `native_workflow.py` and `numeric_validation.py` files without
changing their bytes. The numeric `calculate` function is extracted verbatim
from the native `experience_store.py`. `tracking_core.py` is a small browser
SQLite adapter; `browser_driver.py` limits the allowed operations and inputs.

## Local preview

Serve the repository directory over localhost with a static HTTP server, then
open `/web/index.html`. `file://` is not supported. The first run downloads
Pyodide 314.0.7 from its versioned CDN. The preview requires a browser with
module workers, WebAssembly, Web Locks, IndexedDB and Web Crypto.

Choose an operation and up to 32 numbers. **Run** executes and validates the
task. **Prepare** leaves it pending so **Cancel** can be demonstrated.
**Simulate interruption** injects a test-only stop after effect commit; **Resume**
starts a new worker and completes validation without a second effect. A changed
operation or value creates a new task revision. **Download receipt** saves only
this browser session's observed input and events. **Reset my demo session**
deletes only that session's local database.

The page does not call a language model or send task inputs to a server. The
route is deterministic. Session storage is checked before a worker starts, and
IndexedDB sync is confirmed before success is shown. A denied or failed write
blocks that action without showing a new success receipt. A browser can still
evict or clear saved data later. This sample does not demonstrate
Windows reboot recovery, native process locks, general external effects,
production service integration or model-weight training. Browser workers are
discarded after each operation so a resumed task loads persisted state again.

This first public release requires access to its network dependencies to start
and execute tasks. Offline operation is not supported. When a required resource
cannot be fetched, a new task is blocked without a success receipt.

`core-manifest.json` lists the exact public module hashes. The native-source
comparison and contract vector results are kept in the local review evidence.
See [rights and attribution](RIGHTS_AND_ATTRIBUTION.md) for this bounded
native-core subset and its separately loaded browser runtime.
The existing command-line demo and its historical evidence remain separate.

## Reproducible numeric edge case

Choose **Mean** and enter `1e100, 1, -1e100`. The browser core returns
`0.3333333333333333` with `ACCEPT`: the small middle term survives cancellation
of the large terms. A naive left-to-right sum would produce zero for this
ordering, which the separate numeric validator rejects. The standard-library
regression check runs with `python -m unittest test_web_numeric -v` from the
repository root. This tests a bounded numeric contract; it does not measure
language-model routing or general floating-point accuracy.
