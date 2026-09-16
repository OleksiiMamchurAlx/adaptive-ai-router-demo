"""Offline numeric-tool demo. Use a new directory, never an existing database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from evidence import connect, event, export_events, now

def start(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    with connect(root / 'demo.sqlite3') as db:
        # The route is deterministic and explicit, not an LLM decision.
        result = {'mean': sum([10, 20, 30]) / 3, 'route': 'numeric_tool'}
        accepted = result['mean'] == 20
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                   ('demo', 'COMMITTED', json.dumps(result, sort_keys=True),
                    'deterministic', None, 1, None, now()))
        db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',
                   ('numeric-check', 'demo', 'ACCEPT' if accepted else 'REJECT',
                    int(accepted), 'exact numeric oracle', 'Expected mean = 20'))
        event(db, 'result-committed', 'demo', 'validated', {'accepted': accepted})
    # Deliberate abrupt process exit AFTER commit, BEFORE export.
    os._exit(73)

def resume(root):
    root = Path(root).resolve()
    path = root / 'demo.sqlite3'
    if not path.is_file():
        raise ValueError('No existing demo to resume')
    db = sqlite3.connect(path)
    try:
        row = db.execute('SELECT state,result_json,tool_calls FROM jobs WHERE job_id=?', ('demo',)).fetchone()
        if row is None or row[0] not in ('COMMITTED', 'EXPORTED'):
            raise ValueError('NEEDS_RECONCILIATION: do not repeat an uncertain action')
        check = db.execute('SELECT verdict,task_accepted FROM validations WHERE validation_id=?', ('numeric-check',)).fetchone()
        if check != ('ACCEPT', 1) or json.loads(row[1]).get('mean') != 20 or row[2] != 1:
            raise ValueError('Stored result failed independent validation')
        artifact = (row[1] + '\n').encode()
        sha = hashlib.sha256(artifact).hexdigest()
        (root / 'result.json').write_bytes(artifact)
        with db:
            db.execute('UPDATE jobs SET state=?,artifact_sha256=? WHERE job_id=?', ('EXPORTED', sha, 'demo'))
            event(db, 'result-exported', 'demo', 'exported', {'artifact_sha256': sha})
        export_events(db, root / 'events.jsonl')
        return {'task_accepted': True, 'tool_calls': row[2], 'artifact_sha256': sha,
                'events': db.execute('SELECT count(*) FROM events').fetchone()[0]}
    finally:
        db.close()

def self_test():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'isolated-demo'
        worker = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'start', str(root)],
                                capture_output=True, timeout=20)
        if worker.returncode != 73:
            raise RuntimeError('Expected controlled exit 73')
        first = resume(root)
        exported = (root / 'events.jsonl').read_bytes()
        second = resume(root)
        assert first == second
        assert exported == (root / 'events.jsonl').read_bytes()
        assert first['tool_calls'] == 1 and first['events'] == 2
        return {'mode': 'NEW_PORTABLE_DETERMINISTIC_DEMO', 'status': 'PASS',
                'crash_exit': 73, 'tool_calls': 1, 'resume_count': 2,
                'repeat_export_identical': True, 'reboot_tested': False,
                'external_calls': 0, 'model_inference': False}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['self-test', 'start', 'resume'])
    parser.add_argument('directory', nargs='?')
    args = parser.parse_args()
    if args.action == 'self-test':
        print(json.dumps(self_test(), indent=2))
    elif not args.directory:
        parser.error('start/resume requires a demo directory')
    elif args.action == 'start':
        start(args.directory)
    else:
        print(json.dumps(resume(args.directory), indent=2))
