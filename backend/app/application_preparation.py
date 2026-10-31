"""Derived, account-owned preparation status. Never starts or repeats provider work."""
import json
from . import db

ACTIVE = {'queued', 'running', 'cancelling'}
FAILED = {'failed', 'interrupted', 'cancelled'}
KINDS = ('analysis', 'resume', 'resume_guided', 'resume_optimize', 'resume_fit', 'cover_letter')


def reconcile(user):
    """Repair historical workspaces once; later deletions stay deleted."""
    if db.settings(user).get('preparation_listing_version', 0) >= 1:
        return
    from . import applications
    jobs = {row['id'] for row in db.list_entities(user, 'job')}
    for kind in ('resume_conversation', 'resume_draft', 'analysis'):
        for row in db.list_entities(user, kind):
            job_id = row['data'].get('job_id')
            if job_id in jobs:
                applications.start(user, job_id, recovering=True)
    db.update_settings(user, {'preparation_listing_version': 1})


def decorate(user, records):
    """Attach transient listing metadata; stored application/document snapshots stay intact."""
    kinds = ('resume_conversation', 'resume_revision', 'resume_draft', 'resume',
             'cover_workspace', 'cover_revision', 'cover_letter', 'analysis', 'job')
    entities = {kind: db.list_entities(user, kind) for kind in kinds}
    by_id = {row['id']: row for rows in entities.values() for row in rows}
    placeholders = ','.join('?' for _ in KINDS)
    with db.connect() as connection:
        tasks = [dict(row) for row in connection.execute(
            f'SELECT id,kind,status,result,updated_at FROM tasks WHERE user_id=? '
            f'AND kind IN ({placeholders}) ORDER BY created_at DESC,id DESC', (user, *KINDS))]
    grouped = {}
    for task in tasks:
        payload = json.loads(task['result'] or '{}')
        inputs = payload.get('_task_inputs', payload.get('inputs', {})) or {}
        parent = by_id.get(inputs.get('conversation_id') or inputs.get('workspace_id'))
        # Successful historical tasks predate saved input metadata. Resolve only
        # their owned entity result, never substring-match arbitrary JSON text.
        result = payload.get('_task_result', payload)
        saved = by_id.get(result.get('id')) if isinstance(result, dict) else None
        job_id = inputs.get('job_id') or (parent or saved or {}).get('data', {}).get('job_id')
        if job_id:
            grouped.setdefault(job_id, []).append(task)
    output = []
    for record in records:
        data = record['data']; job_id = data.get('job_id'); flow = data.get('workflow') or {}
        if data.get('status') != 'preparing' or data.get('archived'):
            output.append(record)
            continue
        state = {'state': 'ready', 'label': 'Prepare your application', 'stage': 'posting',
                 'action_label': 'Continue preparation', 'posting_available': job_id in by_id}
        conversation = next((row for row in entities['resume_conversation'] if row['data'].get('job_id') == job_id), None)
        revision = by_id.get((conversation or {}).get('data', {}).get('current_revision_id'))
        draft = next((row for row in entities['resume_draft'] if row['data'].get('job_id') == job_id), None)
        if conversation or any(row['data'].get('job_id') == job_id for row in entities['analysis']):
            state.update(label='Prepare resume', stage='resume', action_label='Continue resume')
        if draft or revision and not revision['data'].get('finalized_resume_id'):
            state.update(label='Draft ready to review', stage='resume', action_label='Review resume draft')
        # Explicit selected versions always take precedence over older draft work.
        if flow.get('resume_id'):
            state.update(label='Prepare or skip letter', stage='letter', action_label='Prepare or skip letter')
            if flow.get('cover_letter_id') or flow.get('cover_skipped'):
                state.update(label='Review finished documents', stage='finish', action_label='Review finished documents')
            if flow['resume_id'] not in by_id:
                state.update(state='attention', label='Needs attention', stage='resume', action_label='Choose a saved resume')
        own = grouped.get(job_id, [])
        latest = next((task for task in own if task['status'] in ACTIVE), None) or next(iter(own), None)
        if latest:
            letter = latest['kind'] == 'cover_letter'
            stage = 'posting' if latest['kind'] == 'analysis' else 'letter' if letter else 'resume'
            completed = max((row['updated_at'] for kind in ('resume_revision', 'resume_draft', 'resume', 'cover_revision', 'cover_letter', 'analysis')
                             for row in entities[kind] if row['data'].get('job_id') == job_id), default='')
            if latest['status'] in ACTIVE:
                label = ('Stopping preparation' if latest['status'] == 'cancelling' else
                         'Comparing posting' if stage == 'posting' else
                         'Cover letter generating' if letter else 'Resume generating')
                state.update(state='working', label=label, stage=stage, action_label='View preparation progress')
            elif latest['status'] in FAILED and latest['updated_at'] > completed:
                state.update(state='attention', label='Needs attention', stage=stage, action_label='Check preparation status')
            if latest['status'] in ACTIVE | FAILED and state['state'] in ('working', 'attention'):
                state.update(task_id=latest['id'], task_status=latest['status'])
        if not state['posting_available']:
            state.update(action_label='Review application details')
        output.append({**record, 'preparation': state})
    return output
