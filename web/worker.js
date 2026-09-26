import {loadPyodide} from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const RUNTIME = 'browser-pyodide-314.0.7';
const INDEX_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';

function syncfs(pyodide, populate) {
  return new Promise((resolve, reject) =>
    pyodide.FS.syncfs(populate, error => error ? reject(error) : resolve()));
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

async function loadReviewedCore(pyodide) {
  const manifestResponse = await fetch('./core-manifest.json', {cache:'no-store'});
  if (!manifestResponse.ok) throw new Error('CORE_MANIFEST_UNAVAILABLE');
  const manifest = await manifestResponse.json();
  if (manifest.schema_version !== 1 || !Array.isArray(manifest.modules))
    throw new Error('CORE_MANIFEST_INVALID');
  pyodide.FS.mkdir('/app');
  for (const item of manifest.modules) {
    if (!/^[a-z_]+\.py$/.test(item.name) || !/^[0-9a-f]{64}$/.test(item.sha256))
      throw new Error('CORE_MANIFEST_INVALID');
    const response = await fetch(`./core/${item.name}`, {cache:'no-store'});
    if (!response.ok) throw new Error('CORE_MODULE_UNAVAILABLE');
    const bytes = await response.arrayBuffer();
    if (await sha256(bytes) !== item.sha256) throw new Error('CORE_HASH_MISMATCH');
    pyodide.FS.writeFile(`/app/${item.name}`, new Uint8Array(bytes));
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/app')");
  return manifest;
}

self.onmessage = async event => {
  const {action, payload} = event.data;
  let pyodide;
  let mounted = false;
  try {
    pyodide = await loadPyodide({indexURL: INDEX_URL});
    pyodide.FS.mkdir('/data');
    pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, '/data');
    mounted = true;
    await syncfs(pyodide, true);

    if (action === 'reset') {
      const sessionId = payload.session_id;
      if (!/^[0-9a-f]{32}$/.test(sessionId)) throw new Error('INVALID_SESSION');
      for (const name of pyodide.FS.readdir('/data')) {
        if (name === `${sessionId}.sqlite3` ||
            name === `${sessionId}.sqlite3-journal` ||
            name === `${sessionId}.sqlite3-wal` ||
            name === `${sessionId}.sqlite3-shm`)
          pyodide.FS.unlink(`/data/${name}`);
      }
      await syncfs(pyodide, false);
      self.postMessage({ok:true, result:{reset:true, runtime:RUNTIME,
        persistence:'IDBFS_SYNC_CONFIRMED'}});
      return;
    }

    const manifest = await loadReviewedCore(pyodide);
    pyodide.globals.set('request_json', JSON.stringify({action, payload}));
    const response = pyodide.runPython(`
import json
from browser_driver import dispatch
request = json.loads(request_json)
json.dumps(dispatch(request['action'], request['payload']),
           sort_keys=True, allow_nan=False)
`);
    await syncfs(pyodide, false);
    self.postMessage({ok:true, result:{...JSON.parse(response), runtime:RUNTIME,
      persistence:'IDBFS_SYNC_CONFIRMED',
      persistence_limit:'Browser storage can be denied, evicted or cleared.',
      public_core:manifest.modules.map(({name,sha256}) => ({name,sha256}))}});
  } catch (error) {
    if (mounted) {
      try { await syncfs(pyodide, false); } catch (_) { /* no durability claim */ }
    }
    self.postMessage({ok:false, reason:String(error).slice(0, 240)});
  }
};
