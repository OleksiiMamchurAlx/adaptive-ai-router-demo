const $ = id => document.getElementById(id);
const storageKey = 'adaptive-router-bounded-demo-v1';
const actionIds = ['prepare','run','interrupt','resume','cancel','reset'];
let session;
let lastReceipt = null;
let busy = false;

function freshSession() {
  return {session_id: crypto.randomUUID().replaceAll('-', ''), revision: 0, lastInput: null};
}

function restoreSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (saved && /^[0-9a-f]{32}$/.test(saved.session_id) &&
        Number.isInteger(saved.revision) && saved.revision >= 0)
      return saved;
  } catch (_) { /* invalid local state starts a new demo session */ }
  return freshSession();
}

function saveSession() { sessionStorage.setItem(storageKey, JSON.stringify(session)); }
function message(value) { $('message').textContent = value; }

function getInput() {
  const operation = $('operation').value;
  const raw = $('values').value.trim();
  const parts = raw.split(/[\s,]+/).filter(Boolean);
  if (!parts.length || parts.length > 32) throw new Error('Enter 1 to 32 numbers.');
  const values = parts.map(Number);
  if (values.some(value => !Number.isFinite(value) || Math.abs(value) > 1e100))
    throw new Error('Use finite numbers with magnitude at most 1e100.');
  return {operation, values};
}

function prepareRevision(input) {
  const canonical = JSON.stringify(input);
  if (canonical !== session.lastInput) {
    session.revision += 1;
    session.lastInput = canonical;
    saveSession();
  }
  return {session_id:session.session_id, revision:session.revision, ...input};
}

async function workerAction(action, payload) {
  if (!navigator.locks?.request) throw new Error('Web Locks unavailable: safe two-tab storage is blocked.');
  return navigator.locks.request('adaptive-router-public-demo-idbfs', {mode:'exclusive'},
    () => new Promise((resolve, reject) => {
      const worker = new Worker('./worker.js', {type:'module'});
      const timer = setTimeout(() => { worker.terminate(); reject(new Error('Execution timeout.')); }, 120000);
      worker.onmessage = event => {
        clearTimeout(timer);
        worker.terminate();
        event.data.ok ? resolve(event.data.result) : reject(new Error(event.data.reason));
      };
      worker.onerror = event => {
        clearTimeout(timer);
        worker.terminate();
        reject(new Error(event.message || 'Browser worker failed.'));
      };
      worker.postMessage({action, payload});
    }));
}

function render(receipt) {
  lastReceipt = receipt;
  const status = receipt.status;
  const result = status.result === null ? '—' : String(status.result);
  $('summary').textContent = `${status.state} · result ${result} · validation ${status.validation_verdict} · committed effects ${status.committed_effect_count}`;
  $('input').textContent = JSON.stringify({
    input:session.lastInput ? JSON.parse(session.lastInput) : null,
    input_digest:status.input_digest, task_revision:status.task_revision,
    route:status.route, runtime:receipt.runtime,
    persistence:receipt.persistence, persistence_limit:receipt.persistence_limit,
    core_version:receipt.core_version
  }, null, 2);
  $('events').textContent = JSON.stringify(receipt.events, null, 2);
  if (receipt.simulated_interruption)
    message('Test-only interruption occurred after effect commit. Use Resume to validate without repeating that effect.');
  else if (status.waiting_reason)
    message(`Waiting: ${status.waiting_reason}. Resume after the lease expires.`);
  else
    message(`Observed ${status.state}. Browser storage sync completed before this result was shown.`);
}

async function act(action) {
  if (busy) return;
  busy = true;
  for (const id of actionIds) $(id).disabled = true;
  message('Loading the pinned Python runtime and executing the selected action…');
  try {
    if (action === 'reset') {
      await workerAction('reset', {session_id:session.session_id});
      sessionStorage.removeItem(storageKey);
      session = freshSession();
      lastReceipt = null;
      $('summary').textContent = 'No task has run.';
      $('input').textContent = '—';
      $('events').textContent = '—';
      message('Only this demo session was reset. Browser storage sync completed.');
      return;
    }
    let payload;
    if (['prepare','run','interrupt'].includes(action))
      payload = prepareRevision(getInput());
    else {
      if (!session.revision) throw new Error('No prepared task to resume or cancel.');
      payload = {session_id:session.session_id, revision:session.revision};
    }
    const receipt = await workerAction(action, payload);
    render(receipt);
  } catch (error) {
    message(`Action blocked: ${String(error.message || error).slice(0, 240)} No durable success receipt was issued.`);
  } finally {
    busy = false;
    for (const id of actionIds) $(id).disabled = false;
  }
}

session = restoreSession();
if (session.lastInput) {
  try {
    const input = JSON.parse(session.lastInput);
    $('operation').value = input.operation;
    $('values').value = input.values.join(', ');
  } catch (_) { /* the next entered input creates a new revision */ }
}

const pageId = crypto.randomUUID();
const channel = new BroadcastChannel('adaptive-router-public-demo-sessions');
channel.onmessage = event => {
  const data = event.data;
  if (data.session_id !== session.session_id || data.page_id === pageId) return;
  if (data.type === 'hello')
    channel.postMessage({type:'collision', session_id:session.session_id,
      page_id:pageId, target:data.page_id});
  if (data.type === 'collision' && data.target === pageId) {
    session = freshSession();
    saveSession();
    lastReceipt = null;
    $('summary').textContent = 'This tab has its own new demo session.';
    $('input').textContent = '—';
    $('events').textContent = '—';
    message('A second tab reused the browser session identifier. This tab now has an isolated session.');
  }
};
channel.postMessage({type:'hello', session_id:session.session_id, page_id:pageId});
for (const id of actionIds) $(id).addEventListener('click', () => act(id));
$('receipt').addEventListener('click', () => {
  if (!lastReceipt) { message('Run or inspect a task before downloading a receipt.'); return; }
  const body = JSON.stringify({...lastReceipt, accepted_input:JSON.parse(session.lastInput)}, null, 2);
  const url = URL.createObjectURL(new Blob([body], {type:'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'router-demo-receipt.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

setTimeout(() => { if (session.revision) act('status'); }, 250);
