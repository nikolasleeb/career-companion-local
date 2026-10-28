"""Per-letter aspirations enter the existing motivation review flow only."""
import copy
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from . import auth, career_goals, cover_letters as letters, db
from .models import StrictModel

router = APIRouter(prefix='/api/cover-workspaces')

class Selection(StrictModel):
    expected_version: int = Field(ge=0)
    expected_goals_revision: int = Field(ge=0)
    enabled: bool = False
    goal_ids: list[str] = Field(default_factory=list, max_length=5)

def validate_current(user, data):
    selection = data.get('career_goal_selection', {})
    if selection.get('enabled') and selection.get('goals_revision') != career_goals.read(user)['revision']:
        raise HTTPException(409, 'Career Goals changed. Review the selected motivation again before sending; your existing letter is preserved.')

def active_proposals(data):
    selection = data.get('career_goal_selection', {})
    selected = set(selection.get('goal_ids', [])) if selection.get('enabled') else set()
    return [p for p in data.get('context_proposals', []) if not p.get('career_goal_source') or
            (p['career_goal_source']['id'] in selected and p['career_goal_source']['goals_revision'] == selection.get('goals_revision'))]

def options(user, id):
    record = letters.require(user, id, 'cover_workspace')
    goals = career_goals.read(user)
    return {'goals': goals['items'], 'goals_revision': goals['revision'], 'workspace_version': record['data']['version'],
            'selection': record['data'].get('career_goal_selection', {'enabled': False, 'goal_ids': []})}

@router.get('/{id}/career-goals')
def get(id: str, user=Depends(auth.current)):
    return options(user['id'], id)

@router.put('/{id}/career-goals')
def select(id: str, body: Selection, user=Depends(auth.current)):
    uid = user['id']
    def change(data, connection):
        row = connection.execute("SELECT payload FROM entities WHERE user_id=? AND kind='career_goals' AND id=?", (uid, career_goals.identity(uid))).fetchone()
        goals = json.loads(row[0]) if row else {'revision': 0, 'items': []}
        if goals['revision'] != body.expected_goals_revision:
            raise HTTPException(409, 'Career Goals changed. Refresh the choices and review your selection again.')
        catalog = {g['id']: g for g in career_goals.canonical_items(goals)}
        ids = list(dict.fromkeys(body.goal_ids)) if body.enabled else []
        if body.enabled and not ids:
            raise HTTPException(422, 'Select at least one goal for this letter.')
        if any(g not in catalog for g in ids):
            raise HTTPException(404, 'A selected goal is no longer available in your account.')
        if any(len(catalog[g]['text']) > 3000 for g in ids):
            raise HTTPException(422, 'Choose goals of at most 3000 characters for letter motivation. Your longer statement is preserved in Profile.')
        data['career_goal_selection'] = {'enabled': body.enabled, 'goal_ids': ids, 'goals_revision': goals['revision']}
        proposals = data.setdefault('context_proposals', [])
        # Only active selections can remain pending. Historical approved sources stay stored.
        for p in proposals:
            source = p.get('career_goal_source')
            if source and p['status'] == 'pending' and (source['id'] not in ids or source['goals_revision'] != goals['revision']):
                p['status'] = 'rejected'
        for gid in ids:
            if any(p.get('career_goal_source', {}).get('id') == gid and p.get('career_goal_source', {}).get('goals_revision') == goals['revision'] and p['status'] in ('pending', 'approved') for p in proposals):
                continue
            goal = catalog[gid]
            message_id = db.uid()
            data.setdefault('messages', []).append({'id': message_id, 'role': 'user', 'text': goal['text'],
                'created_at': db.now(), 'source': 'Explicit Career Goal selection for motivation review'})
            proposals.append({'id': db.uid(), 'kind': 'motivation', 'title': 'Career Goal · motivation only',
                'user_quote': goal['text'], 'text': goal['text'], 'suggested_text': goal['text'],
                'editing_note': 'Selected by you for this letter. Review wording before use; aspirations are not accomplishments.',
                'improvement_suggestions': [], 'question_ids': [], 'related_source_id': '', 'supersedes_id': '',
                'profile_category': 'project', 'status': 'pending', 'source_message_id': message_id,
                'source_message_text': goal['text'], 'created_at': db.now(), 'profile_record_id': '',
                'profile_expected_updated_at': '', 'profile_original': None,
                'career_goal_source': {'id': gid, 'goals_revision': goals['revision'], 'snapshot': copy.deepcopy(goal)}})
        data['context_dirty'] = True
    letters.mutate(uid, id, body.expected_version, change)
    return letters.state(uid, id)
