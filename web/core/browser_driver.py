"""Limited bridge between a browser worker and the unchanged native workflow."""
import json
import os
import re

import native_workflow


class SimulatedInterruption(BaseException):
    pass


def _events(workflow, task_id, revision):
    with workflow.tracker._connection() as db:
        rows = db.execute(
            '''SELECT kind,detail_json FROM workflow_events
               WHERE task_id=? AND task_revision=? ORDER BY event_id''',
            (task_id, revision)).fetchall()
    return [{'kind': row['kind'], 'detail': json.loads(row['detail_json'])}
            for row in rows]


def dispatch(action, payload):
    session_id = payload.get('session_id')
    if not isinstance(session_id, str) or not re.fullmatch('[0-9a-f]{32}', session_id):
        raise ValueError('invalid demo session')
    revision = payload.get('revision')
    if type(revision) is not int or not 1 <= revision <= 10000:
        raise ValueError('invalid demo revision')
    task_id = 'demo-' + session_id
    workflow = native_workflow.NativeWorkflow(
        '/data/' + session_id + '.sqlite3',
        lease_seconds=0.2,
        artifact_limit_bytes=8 * 1024 * 1024,
        min_free_bytes=0)

    interrupted = False
    if action in {'prepare', 'run', 'interrupt'}:
        operation = payload.get('operation')
        values = payload.get('values')
        if operation not in {'sum', 'mean', 'min', 'max', 'range'}:
            raise ValueError('unsupported operation')
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError('enter 1 to 32 numbers')
        envelope = native_workflow.TaskEnvelope(
            task_id=task_id, task_revision=revision,
            idempotency_key=f'{task_id}-{revision}',
            operation=operation, values=tuple(values),
            source='synthetic', split='dev', dataset_id='public-demo',
            policy_version='public-demo-v1', max_attempts=3)
        workflow.submit(envelope)
        if action == 'prepare':
            pass
        elif action == 'interrupt':
            original_exit = os._exit
            old_test_mode = os.environ.get('ADAPTIVE_ROUTER_WORKFLOW_TEST_MODE')
            os.environ['ADAPTIVE_ROUTER_WORKFLOW_TEST_MODE'] = '1'
            os._exit = lambda code: (_ for _ in ()).throw(SimulatedInterruption(code))
            try:
                workflow.run(task_id, revision, memory_enabled=False,
                             simulate_interrupt_after_effect=True)
            except SimulatedInterruption:
                interrupted = True
            finally:
                os._exit = original_exit
                if old_test_mode is None:
                    os.environ.pop('ADAPTIVE_ROUTER_WORKFLOW_TEST_MODE', None)
                else:
                    os.environ['ADAPTIVE_ROUTER_WORKFLOW_TEST_MODE'] = old_test_mode
        else:
            workflow.run(task_id, revision, memory_enabled=False)
    elif action == 'resume':
        workflow.run(task_id, revision, memory_enabled=False)
    elif action == 'cancel':
        workflow.cancel(task_id, revision)
    elif action != 'status':
        raise ValueError('unsupported demo action')

    return {'core_version': native_workflow.ENGINE_VERSION,
            'status': workflow.status(task_id, revision),
            'events': _events(workflow, task_id, revision),
            'simulated_interruption': interrupted}
