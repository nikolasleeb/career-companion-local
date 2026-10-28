"""Explicit employer-industry selection shared by all search entrypoints."""
import json
from fastapi import APIRouter,Depends,HTTPException
from . import auth,db
from .models import StrictModel
from pydantic import Field
from typing import Literal
INDUSTRIES={'science':'Science & research','healthcare':'Healthcare & life sciences','education':'Education','finance':'Finance & professional services','manufacturing':'Manufacturing & engineering','climate':'Climate & energy','nonprofit':'Nonprofits & public interest','consumer':'Consumer services & logistics','technology':'Technology'}
class Selection(StrictModel):
    employer_selection_mode:Literal['all','industries','custom']='all'
    employer_industries:list[str]=Field(default_factory=list,max_length=9)
    employer_boards:list[str]|None=Field(default=None,max_length=300)

def validate(mode,industries):
    if set(industries)-set(INDUSTRIES):raise ValueError('Choose industries from the employer catalog.')
    if mode=='industries' and not industries:raise ValueError('Choose at least one employer industry.')

def selection(query):
    mode=query.get('employer_selection_mode') or ('custom' if query.get('employer_boards') is not None else 'all')
    return {'employer_selection_mode':mode,'employer_industries':query.get('employer_industries') or [],'employer_boards':query.get('employer_boards') if mode=='custom' else None}

def resolve(boards,query):
    from .public_job_feeds import board_key
    selected=selection(query)
    try:validate(selected['employer_selection_mode'],selected['employer_industries'])
    except ValueError as error:raise HTTPException(422,str(error))
    if selected['employer_selection_mode']=='all':return boards
    if selected['employer_selection_mode']=='industries':return [b for b in boards if set(b.get('industries',[]))&set(selected['employer_industries'])]
    return [b for b in boards if board_key(b) in (selected['employer_boards'] or [])]
router=APIRouter(prefix='/api/settings/employer-sources')
@router.get('')
def get_sources(user=Depends(auth.current)):
    from . import public_job_feeds as feeds,job_alerts
    return {'industries':[{'id':k,'label':v} for k,v in INDUSTRIES.items()],'employers':feeds.listing(user['id']),'selection':selection(job_alerts.preferences(user['id'])['data']['query']),'catalog_revision':feeds.REVISION,'added_boards':db.list_entities(user['id'],'board')}
@router.put('')
def save_sources(body:Selection,user=Depends(auth.current)):
    from . import job_alerts
    try:validate(body.employer_selection_mode,body.employer_industries)
    except ValueError as e:raise HTTPException(422,str(e))
    # Merge only source choices; never overwrite roles, location or alert settings.
    r=job_alerts.preferences(user['id'])
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');stored=c.execute('SELECT payload FROM entities WHERE id=? AND user_id=?',(r['id'],user['id'])).fetchone();data=json.loads(stored[0]) if stored else r['data'];data['query'].update(body.model_dump())
        if stored:c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(data),db.now(),r['id'],user['id']))
        else:c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(r['id'],user['id'],'job_search_preferences',json.dumps(data),db.now(),db.now()))
    return get_sources(user)

from .models import Board
@router.post('/boards')
def add_board(body:Board,user=Depends(auth.current)):
    rows=db.list_entities(user['id'],'board')
    key=(body.provider,body.board,body.region)
    existing=next((r for r in rows if (r['data']['provider'],r['data']['board'],r['data'].get('region','global'))==key),None)
    if not existing and len(rows)>=16:raise HTTPException(400,'Keep at most 16 account-added employer sources.')
    return db.save(user['id'],'board',body.model_dump(),existing['id'] if existing else None)
@router.delete('/boards/{identity}')
def remove_board(identity:str,user=Depends(auth.current)):
    if not db.get(user['id'],identity,'board'):raise HTTPException(404,'Account-added employer not found.')
    db.delete(user['id'],identity);return {'removed':True}
