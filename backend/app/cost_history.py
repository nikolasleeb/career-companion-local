"""Account-private provider usage ledger. No prompts, outputs, keys or billing API access."""
import hashlib
import json
import math
import re
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import Field,field_validator
from typing import Literal
from .models import StrictModel
from . import db,ai_settings

PROCESSES={'application_agent':'Application assistant','analysis':'Job comparison','resume':'Resume building','resume_optimize':'Resume optimization','resume_fit':'Resume layout','resume_guided':'Resume questions & revisions','cover_letter':'Cover letters','preparation':'Interview preparation','interview':'Interview feedback','discovery':'Job discovery','project_analysis':'Project-source analysis','story_prompts':'Story prompts','assessment':'Career interests','other':'Other AI activity'}
ENTITY_PROCESSES={'analysis':'analysis','resume':'resume','resume_draft':'resume_optimize','resume_revision':'resume_guided','resume_conversation':'resume_guided','cover_workspace':'cover_letter','cover_revision':'cover_letter','cover_letter':'cover_letter','prep':'preparation','interview':'interview','search':'discovery','project_analysis':'project_analysis','story_prompts':'story_prompts'}
PRICE_URL='https://developers.openai.com/api/docs/pricing'
WEB_SEARCH_PER_CALL=.01
PRICE_CHECKED='2026-10-23'

class UsageEvent(StrictModel):
    schema_version:Literal[1]=1
    event_key:str=Field(min_length=1,max_length=200)
    occurred_at:str
    model:str=Field(max_length=150)
    requested_service_tier:str=Field(default='',max_length=40)
    service_tier:str=Field(default='',max_length=40)
    process:str=Field(max_length=60)
    step:str=Field(default='',max_length=150)
    task_id:str=Field(default='',max_length=64)
    status:Literal['pending','completed','incomplete','failed','rejected','unknown','recovered']
    origin:Literal['provider','recovered']='provider'
    input_tokens:int=Field(default=0,ge=0,le=10**12)
    cached_input_tokens:int=Field(default=0,ge=0,le=10**12)
    cache_write_tokens:int=Field(default=0,ge=0,le=10**12)
    cache_write_30m_tokens:int=Field(default=0,ge=0,le=10**12)
    cache_write_12h_tokens:int=Field(default=0,ge=0,le=10**12)
    cache_counts_reported:bool=False
    output_tokens:int=Field(default=0,ge=0,le=10**12)
    reasoning_tokens:int=Field(default=0,ge=0,le=10**12)
    web_search_calls:int=Field(default=0,ge=0,le=100000)
    usage_reported:bool=False
    token_cost_usd:float|None=Field(default=None,ge=0,le=10**9)
    tool_cost_usd:float|None=Field(default=None,ge=0,le=10**9)
    estimated_cost_usd:float|None=Field(default=None,ge=0,le=10**9)
    estimated_cost_upper_usd:float|None=Field(default=None,ge=0,le=10**9)
    partial:bool=False
    pricing_date:str=Field(default='',max_length=30)
    rates:dict=Field(default_factory=dict,max_length=10)
    notes:list[str]=Field(default_factory=list,max_length=10)
    metadata_key:str=Field(default='',max_length=64)

    @field_validator('occurred_at')
    @classmethod
    def timestamp(cls,value):
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None:raise ValueError('Usage dates need a timezone.')
        return parsed.astimezone(timezone.utc).isoformat()
    @field_validator('rates')
    @classmethod
    def valid_rates(cls,value):
        if any(k not in ('input','cached_input','output','cache_write_30m','cache_write_12h','web_search_per_call','long_input_multiplier','long_output_multiplier') or type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1000000 for k,v in value.items()):raise ValueError('Invalid price snapshot.')
        return value
    @field_validator('notes')
    @classmethod
    def short_notes(cls,value):
        if any(len(v)>300 for v in value):raise ValueError('Usage note is too long.')
        return value


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def count(value):return min(value,10**12) if type(value) is int and value>=0 else 0

def normalized(usage):
    usage=usage if isinstance(usage,dict) else {}
    incoming=count(usage.get('input_tokens'));out=count(usage.get('output_tokens'))
    details=usage.get('input_tokens_details') or {};details=details if isinstance(details,dict) else {}
    output=usage.get('output_tokens_details') or {};output=output if isinstance(output,dict) else {}
    return {'input_tokens':incoming,'cached_input_tokens':min(incoming,count(usage.get('cached_input_tokens',details.get('cached_tokens')))),'output_tokens':out,'reasoning_tokens':min(out,count(usage.get('reasoning_tokens',output.get('reasoning_tokens'))))}


def metadata_key(meta):
    return digest([meta.get('model'),meta.get('generated_at'),normalized(meta.get('usage')),meta.get('estimated_token_cost_usd'),meta.get('pricing_date')])


def write(user,data,identity=None):
    clean=UsageEvent.model_validate(data).model_dump()
    identity=identity or digest([user,clean['event_key']])[:32]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # A concurrent history read/backup may recover the same provider response.
        if not c.execute('SELECT 1 FROM users WHERE id=?',(user,)).fetchone():return None
        existing=c.execute('SELECT user_id,kind FROM entities WHERE id=?',(identity,)).fetchone()
        if existing and (existing['user_id']!=user or existing['kind']!='usage_event'):raise ValueError('Record not found')
        stamp=db.now()
        if existing:c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=?',(json.dumps(clean),stamp,identity))
        else:c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(identity,user,'usage_event',json.dumps(clean),stamp,stamp))
    return db.get(user,identity,'usage_event')


def begin(context,body):
    user=context.get('user_id')
    if not user:return None
    schema=((body.get('text') or {}).get('format') or {}).get('name','')
    step=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',schema).removesuffix(' Output').strip()[:100]
    operation=context.get('operation','')
    if operation:step=(operation.replace('/',' · ').replace('_',' ')+' · '+step).strip(' ·')
    return write(user,{'event_key':'request:'+db.uid(),'occurred_at':db.now(),'model':str(body.get('model','Unknown'))[:150],'process':context.get('process') if context.get('process') in PROCESSES else 'other','step':step or 'Generate response','task_id':context.get('task_id',''),'status':'pending','requested_service_tier':str(body.get('service_tier','default'))[:40],'pricing_date':PRICE_CHECKED})


def finish(user,event,body,response=None,http_status=200,status=None):
    if not event:return None
    response=response if isinstance(response,dict) else {}
    raw=response.get('usage');reported=isinstance(raw,dict) and all(type(raw.get(k)) is int and raw[k]>=0 for k in ('input_tokens','output_tokens'))
    counts=normalized(raw);model=str(response.get('model') or body.get('model') or 'Unknown')[:150]
    requested=str(body.get('service_tier','default'))[:40]
    actual=str(response.get('service_tier') or '')[:40]
    tier=actual or requested
    rate=ai_settings.rates(model,tier)
    notes=[];token=None;tools=None
    snapshot={k:rate[k] for k in ('input','cached_input','output')} if rate else {}
    output=response.get('output');web=sum(1 for v in output if isinstance(v,dict) and v.get('type')=='web_search_call') if isinstance(output,list) else 0
    web_requested=any(v.get('type') in ('web_search','web_search_preview') for v in body.get('tools',[]) if isinstance(v,dict))
    if reported:
        ttl=(body.get('prompt_cache_options') or {}).get('ttl','30m')
        cache=ai_settings.cache_counts(raw,ttl)
        if cache:counts.update(cache,cache_counts_reported=True)
        if rate and cache is not None:
            token=ai_settings.usage_cost(model,raw,ttl,service_tier=tier)
            if cache['cache_write_tokens']:snapshot.update(cache_write_30m=rate['input']*1.25,cache_write_12h=rate['input']*2.5)
            if counts['input_tokens']>272000:snapshot.update(long_input_multiplier=2,long_output_multiplier=1.5);notes.append('Uses the app catalog’s long-context rate assumption.')
        elif not rate:notes.append('Model rate or service-tier rate unavailable; token cost is unpriced.')
        elif cache is None:notes.append('Inconsistent cache-token counts; token cost is unpriced.')
        if not actual and requested!='default':notes.append('Processing tier was not returned; estimate uses the requested tier.')
        if actual and {'priority':'fast','standard':'default'}.get(actual,actual)!={'priority':'fast','standard':'default'}.get(requested,requested):notes.append('OpenAI used a different processing tier; estimate uses the returned tier.')
        if not web_requested or isinstance(output,list):tools=round(web*WEB_SEARCH_PER_CALL,6)
        else:notes.append('Web-search usage was not returned; tool cost is unpriced.')
    else:notes.append('No token usage was returned; any charge is unknown.')
    if web:snapshot['web_search_per_call']=WEB_SEARCH_PER_CALL
    # Only the existing text model and web-search workflows are priced here.
    if isinstance(output,list) and any(isinstance(v,dict) and v.get('type') in ('image_generation_call','code_interpreter_call','file_search_call','computer_call') for v in output):
        notes.append('Additional tool charges are unpriced.');tools=None
    state=status or ('rejected' if 400<=http_status<500 else 'failed' if http_status>=500 or response.get('error') else (response.get('status') or 'completed'))
    if state not in ('completed','incomplete','failed','rejected','unknown'):state='unknown'
    known=[v for v in (token,tools) if v is not None]
    key='response:'+str(response['id']) if isinstance(response.get('id'),str) and len(response['id'])<=180 else event['data']['event_key']
    return write(user,{**event['data'],**counts,'model':model,'requested_service_tier':requested,'service_tier':actual,'event_key':key,'status':state,'usage_reported':reported,'web_search_calls':web,'token_cost_usd':token,'tool_cost_usd':tools,'estimated_cost_usd':round(sum(known),6) if (token is not None and tools is not None) or any(v>0 for v in known) else None,'partial':token is None or tools is None,'rates':snapshot,'notes':notes},event['id'])


def link_metadata(user,event,meta):
    if not event:return
    with db.connect() as c:
        row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='usage_event'",(event,user)).fetchone()
        if row:
            data=json.loads(row[0]);data['metadata_key']=metadata_key(meta)
            c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(data),db.now(),event,user))


def _walk(value,path=()):
    if isinstance(value,dict):
        if isinstance(value.get('model'),str) and isinstance(value.get('usage'),dict) and value.get('generated_at'):
            yield value,path;return
        for key,child in value.items():
            if key not in ('profile','retrieved','resume_snapshot','posting_snapshot','original','catalog','sources'):yield from _walk(child,path+(key,))
    elif isinstance(value,list):
        for i,child in enumerate(value):yield from _walk(child,path+(str(i),))


def recover(user):
    """Deduplicate saved per-call metadata, never aggregate estimates or document copies."""
    existing=db.list_entities(user,'usage_event')
    seen={r['data'].get('metadata_key') for r in existing if r['data'].get('metadata_key')}
    keys={r['data']['event_key'] for r in existing}
    with db.connect() as c:
        tasks=c.execute('SELECT * FROM tasks WHERE user_id=? ORDER BY created_at',(user,)).fetchall()
        entities=c.execute("SELECT kind,payload FROM entities WHERE user_id=? AND kind!='usage_event' ORDER BY created_at",(user,)).fetchall()
    candidates=[]
    for task in tasks:
        if not task['result']:continue
        try:items=list(_walk(json.loads(task['result'])))
        except (ValueError,TypeError):continue
        for meta,path in items:
            try:stamp=datetime.fromisoformat(meta['generated_at']);start=datetime.fromisoformat(task['created_at']);end=datetime.fromisoformat(task['updated_at'])
            except (ValueError,TypeError):continue
            if stamp.tzinfo and start<=stamp<=end:candidates.append((meta,path,task['kind'],task['id']))
    for entity in entities:
        if entity['kind'] not in ENTITY_PROCESSES:continue
        try:candidates.extend((meta,path,ENTITY_PROCESSES[entity['kind']], '') for meta,path in _walk(json.loads(entity['payload'])))
        except (ValueError,TypeError):continue
    for meta,path,process,task_id in candidates:
        if meta.get('usage_event_id'):continue
        if not any(k in meta['usage'] for k in ('input_tokens','output_tokens')):continue
        fingerprint=metadata_key(meta);key='legacy:'+fingerprint
        if fingerprint in seen or key in keys:continue
        amount=meta.get('estimated_token_cost_usd')
        if type(amount) not in (int,float) or not math.isfinite(amount) or amount<0:amount=None
        step='Evidence audit' if 'audit_ai' in path else 'Layout correction' if 'layout_ai' in path else 'Recovered saved response'
        data={'event_key':key,'occurred_at':meta['generated_at'],'model':meta['model'][:150],'process':process if process in PROCESSES else 'other','step':step,'task_id':task_id,'status':'recovered','origin':'recovered',**normalized(meta['usage']),'usage_reported':True,'token_cost_usd':amount,'tool_cost_usd':None,'estimated_cost_usd':amount,'partial':True,'pricing_date':str(meta.get('pricing_date',''))[:30],'metadata_key':fingerprint,'notes':['Recovered saved token estimate. Older failed/deleted calls and tool fees may be missing.']}
        try:write(user,data)
        except ValueError:continue
        seen.add(fingerprint);keys.add(key)


def events(user):
    recover(user)
    records=db.list_entities(user,'usage_event');unique={}
    with db.connect() as c:tasks={r['id']:r['status'] for r in c.execute('SELECT id,status FROM tasks WHERE user_id=?',(user,))}
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=10)
    for record in records:
        data=record['data'];key=data['event_key']
        # The original ledger discarded write counts. Preserve that limitation as
        # a bounded estimate, using its frozen rates and the app's default 30m TTL.
        if data.get('notes')==['Cache-write pricing is unavailable; token cost is unpriced.'] and data.get('token_cost_usd') is None and data.get('origin')=='provider' and all(k in data.get('rates',{}) for k in ('input','cached_input','output')):
            rates=data['rates'];incoming=data['input_tokens'];cached=data['cached_input_tokens'];long=incoming>272000
            input_cost=(incoming-cached)*rates['input']*(2 if long else 1)/1_000_000
            fixed=(cached*rates['cached_input']*(2 if long else 1)+data['output_tokens']*rates['output']*(1.5 if long else 1))/1_000_000
            token=round(fixed+input_cost,6);tools=data.get('tool_cost_usd') or 0
            data={**data,'token_cost_usd':token,'estimated_cost_usd':round(token+tools,6),'estimated_cost_upper_usd':round(fixed+input_cost*1.25+tools,6),'partial':True,'notes':['Historical estimate range: cache-write counts were not retained. Uses frozen model rates and the app’s default 30-minute cache lifetime. Exact original charges cannot be reconstructed.']}
            record=write(user,data,record['id'])
        if data['status']=='pending' and (tasks.get(data.get('task_id')) in ('interrupted','failed','completed') or datetime.fromisoformat(data['occurred_at'])<cutoff):
            data={**data,'status':'unknown','partial':True,'notes':['The request ended without final usage; any charge is unknown.']};record=write(user,data,record['id'])
        value={**data,'id':record['id'],'task_status':tasks.get(data.get('task_id'))}
        if key not in unique or unique[key]['status']=='pending':unique[key]=value
    return sorted(unique.values(),key=lambda v:v['occurred_at'],reverse=True)


def filtered(user,start='',end='',model='',process='',tz='UTC'):
    try:
        zone=ZoneInfo(tz)
        lower=date.fromisoformat(start) if start else None;upper=date.fromisoformat(end) if end else None
        if lower and upper and upper<lower:raise ValueError()
    except (ValueError,ZoneInfoNotFoundError):raise ValueError('Choose a valid date range and timezone.') from None
    all_rows=events(user);rows=[]
    for row in all_rows:
        day=datetime.fromisoformat(row['occurred_at']).astimezone(zone).date()
        if (not lower or day>=lower) and (not upper or day<=upper) and (not model or row['model']==model) and (not process or row['process']==process):rows.append(row)
    return rows,all_rows,zone


def totals(rows):
    def subtotal(key):
        known=[r[key] for r in rows if r.get(key) is not None]
        return round(sum(known),6) if known or not rows else None
    ranged=any(r.get('estimated_cost_upper_usd') is not None for r in rows)
    bounded=all(r.get('estimated_cost_usd') is not None and (not r['partial'] or r.get('estimated_cost_upper_usd') is not None) for r in rows)
    upper=round(sum(r.get('estimated_cost_upper_usd') if r.get('estimated_cost_upper_usd') is not None else r['estimated_cost_usd'] for r in rows),6) if ranged and bounded else None
    return {'estimated_cost_usd':subtotal('estimated_cost_usd'),'estimated_cost_upper_usd':upper,'token_cost_usd':subtotal('token_cost_usd'),'tool_cost_usd':subtotal('tool_cost_usd'),'requests':len(rows),'unpriced_requests':sum(r['partial'] or r['estimated_cost_usd'] is None for r in rows),'recovered_requests':sum(r['origin']=='recovered' for r in rows),**{key:sum(r.get(key,0) for r in rows) for key in ('input_tokens','cached_input_tokens','cache_write_tokens','output_tokens','reasoning_tokens','web_search_calls')}}


def report(user,start='',end='',model='',process='',tz='UTC',bucket='day',offset=0,limit=30):
    rows,all_rows,zone=filtered(user,start,end,model,process,tz)
    def grouped(key):
        groups={}
        for row in rows:groups.setdefault(key(row),[]).append(row)
        return [{'key':key,**totals(values)} for key,values in sorted(groups.items())]
    by_model=grouped(lambda r:r['model']);by_process=grouped(lambda r:r['process'])
    for row in by_process:row['label']=PROCESSES.get(row['key'],'Other AI activity')
    return {'totals':totals(rows),'series':grouped(lambda r:datetime.fromisoformat(r['occurred_at']).astimezone(zone).strftime('%Y-%m' if bucket=='month' else '%Y-%m-%d')),'by_model':by_model,'by_process':by_process,'events':rows[offset:offset+limit],'offset':offset,'limit':limit,'models':sorted({r['model'] for r in all_rows}),'processes':[{'id':key,'label':PROCESSES.get(key,'Other AI activity')} for key in sorted({r['process'] for r in all_rows})],'earliest':min((r['occurred_at'] for r in all_rows),default=None),'pricing_url':PRICE_URL,'timezone':tz}
