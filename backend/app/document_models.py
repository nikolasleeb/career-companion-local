"""Account-owned document model roles; selections are frozen by the task AI context."""
from contextlib import contextmanager
from contextvars import ContextVar
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal
from . import ai_settings, auth, db
from .network import ServiceError

_role=ContextVar('document_model_role',default='writer')
PROCESSES={'resume_guided','resume_optimize','cover_letter'}
class ModelChoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model:str
    reasoning_effort:str='medium'
    speed:str='standard'
class ModelPair(BaseModel):
    model_config=ConfigDict(extra='forbid')
    writer:ModelChoice
    reviewer:ModelChoice
    resume_review_mode:Literal['standard','thorough']|None=None

def choice(value):
    return ai_settings.resolve({'custom_model':value['model'],'custom_reasoning':value['reasoning_effort'],'custom_speed':value.get('speed','standard')},'custom')
def validate(pair):
    try:
        if set(pair)!={'writer','reviewer'}:raise ValueError('Choose a Writer and a Reviewer.')
        for value in pair.values():
            ModelChoice.model_validate(value)
            choice(value)
    except (ValueError,KeyError) as exc:raise ServiceError(str(exc)) from None
    return pair

def preview_settings(user,pair=None):
    settings=dict(db.settings(user))
    if pair is not None:
        value=pair.model_dump(exclude_none=True) if hasattr(pair,'model_dump') else dict(pair)
        workflow=value.pop('resume_review_mode',None)
        settings['document_models']=validate(value)
        if workflow:settings['resume_review_mode']=workflow
    return settings

def configured(settings):
    try:return validate(settings.get('document_models') or {})
    except ServiceError:raise ServiceError('Choose and save Writer and Reviewer settings before using the document optimizer.') from None

def options(settings,mode=None):
    pair=settings.get('document_models')
    return {**choice(validate(pair)[_role.get()]),'document_role':_role.get()} if pair else ai_settings.resolve(settings,mode)

@contextmanager
def role(name):
    token=_role.set(name)
    try:yield
    finally:_role.reset(token)

def estimate(settings,role_name,input_tokens,answer_tokens,mode=None):
    with role(role_name):opt=options(settings,mode)
    return ai_settings.estimate(opt['model'],opt['reasoning_effort'],input_tokens,answer_tokens,service_tier=opt['service_tier'],max_output_tokens=settings.get('ai_max_output_tokens') or None)

router=APIRouter(prefix='/api/document-models',tags=['document models'])
@router.get('')
def get_models(user=Depends(auth.current)):
    settings=db.settings(user['id'])
    return {'pair':settings.get('document_models'),'resume_review_mode':settings.get('resume_review_mode','standard'),'writer_default':ai_settings.resolve(settings),'catalog':ai_settings.public(settings)['catalog']}
@router.put('')
def save_models(body:ModelPair,user=Depends(auth.current)):
    pair=body.model_dump(exclude_none=True);workflow=pair.pop('resume_review_mode',None)
    try:validate(pair)
    except ServiceError as exc:raise HTTPException(422,str(exc)) from None
    db.update_settings(user['id'],{'document_models':pair,**({'resume_review_mode':workflow} if workflow else {})})
    return get_models(user)


@router.get('/tasks/status')
def task_status(request_token:str,user=Depends(auth.current)):
    import json
    if not 8<=len(request_token)<=100:raise HTTPException(422,'Choose a valid request token.')
    with db.connect() as c:
        rows=c.execute("SELECT id,status,result FROM tasks WHERE user_id=? AND kind IN ('resume_guided','cover_letter') ORDER BY created_at DESC",(user['id'],)).fetchall()
    for row in rows:
        payload=json.loads(row['result'] or '{}');inputs=payload.get('_task_inputs',payload.get('inputs',{}))
        if inputs.get('request_token')==request_token:return {'task_id':row['id'],'status':row['status']}
    raise HTTPException(404,'No document task exists with this request token.')
