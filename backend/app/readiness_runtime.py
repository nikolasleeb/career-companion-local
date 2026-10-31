"""Pinned SDK adapter; all network requests use the app's audited account transport."""
import json, time
from dataclasses import dataclass, field
from agents import Agent, Runner, RunConfig, ModelSettings, RunContextWrapper, function_tool
from agents.models.openai_responses import OpenAIResponsesModel
from agents.model_settings import ModelRetrySettings
from openai import Omit, NotGiven
from openai.types.responses import Response
from . import ai, ai_settings, db, task_atomic, task_progress
from .network import ServiceError
from .readiness_models import AgentEnvelope

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS cc_readiness_reservations (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        session_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        reserved REAL NOT NULL, actual REAL, state TEXT NOT NULL, created_at TEXT NOT NULL)''')

def wire_value(value):
    if hasattr(value,'model_dump'):return wire_value(value.model_dump(exclude_none=True))
    if isinstance(value,dict):return {k:wire_value(v) for k,v in value.items() if not isinstance(v,(Omit,NotGiven))}
    if isinstance(value,list):return [wire_value(v) for v in value if not isinstance(v,(Omit,NotGiven))]
    return value

@dataclass
class Context:
    user: str
    session_id: str
    inputs: dict
    mode: str
    sources: dict = field(default_factory=dict)
    activity: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    tool_count: int = 0
    model_rounds: int = 0
    researched: bool = False
    metadata: list = field(default_factory=list)
    research_warnings: list = field(default_factory=list)

    def add(self,rows):
        for row in rows:
            if row.get('text') and len(self.sources)<90:self.sources[row['source_id']]=row
        return rows

    async def invoke(self,name,args,call):
        fingerprint=json.dumps([name,args],sort_keys=True)
        if self.tool_count>=8:return {'unavailable':True,'message':'Tool limit reached. Finish with the verified evidence and explain gaps.'}
        if fingerprint in self.seen:return {'unavailable':True,'message':'This operation was already performed. Use its earlier result or clarify.'}
        self.seen.add(fingerprint);self.tool_count+=1;started=time.monotonic()
        task_progress.stage('readiness_investigation')
        status='completed'
        try:
            result=call()
            if hasattr(result,'__await__'):result=await result
            if isinstance(result,dict) and result.get('unavailable'):status='unavailable'
            return result
        except ServiceError as error:
            status='unavailable'
            return {'unavailable':True,'message':str(error)}
        finally:
            self.activity.append({'tool':name,'status':status,'seconds':round(time.monotonic()-started,3)})

class Budget:
    def __init__(self,context):
        self.context=context;self.ceiling=context.inputs['action_budget_usd'];self.used=0.
        self.options=ai.options(context.mode)
        self.rate=ai_settings.rates(self.options['model'],self.options['service_tier'])
        if not self.rate:raise ServiceError('This model or processing tier has no verified price. Choose a priced AI setup before starting readiness.')
        self.output_limit=ai.output_limit(16000 if ai.effort(context.mode) in ('high','xhigh','max') else 8000)

    def estimate(self,body):
        # UTF-8 bytes conservatively bound text token counts; include schemas and overhead.
        size=len(json.dumps(body,ensure_ascii=False).encode())+2048
        if size>180000:raise ServiceError('The readiness context is too large. Shorten the conversation or select less evidence.')
        return (size*self.rate['input']+body.get('max_output_tokens',self.output_limit)*self.rate['output'])/1_000_000 + (.04 if any(t.get('type')=='web_search' for t in body.get('tools',[])) else 0)

    def final_reserve(self):
        return (180000*self.rate['input']+self.output_limit*self.rate['output'])/1_000_000

    @task_atomic.independent
    def reserve(self,body):
        amount=self.estimate(body)
        if self.used+amount>self.ceiling+1e-9:raise ServiceError('This action reached its estimated spending ceiling. Existing reports are preserved. Review the budget before starting another action.')
        self.used+=amount;identity=db.uid();task=(ai._context.get() or {}).get('task_id','')
        with db.connect() as c:c.execute('INSERT INTO cc_readiness_reservations VALUES(?,?,?,?,?,?,?,?)',(identity,self.context.user,self.context.session_id,task,amount,None,'dispatching',db.now()))
        return identity,amount

    @task_atomic.independent
    def finish(self,reservation,response,http_status=0):
        identity,reserved=reservation;actual=None;state='unknown'
        if isinstance(response,dict):
            usage=response.get('usage')
            if isinstance(usage,dict) and all(type(usage.get(k)) is int for k in ('input_tokens','output_tokens')):
                actual=ai_settings.usage_cost(response.get('model',self.options['model']),usage,service_tier=response.get('service_tier') or self.options['service_tier'])
                if actual is not None:
                    actual+=.01*sum(r.get('type')=='web_search_call' for r in response.get('output',[]));state='reported'
            elif 400<=http_status<500:actual=0.;state='rejected'
        if actual is not None:self.used+=actual-reserved
        with db.connect() as c:c.execute('UPDATE cc_readiness_reservations SET actual=?,state=? WHERE id=? AND user_id=?',(actual,state,identity,self.context.user))

class AccountResponsesModel(OpenAIResponsesModel):
    """SDK conversion/loop with Career Companion's account-scoped HTTP clients.

    The overridden private adapter is pinned and exercised by real Runner tests.
    It avoids SDK retries, global API keys and a second usage-accounting path.
    """
    def __init__(self,context,budget):
        super().__init__(model=ai.options(context.mode)['model'],openai_client=None)
        self.context=context;self.budget=budget

    def _supports_default_prompt_cache_key(self):return False
    def _uses_official_openai_endpoint(self):return False
    def _get_client(self):
        raise ServiceError('Readiness must use the account-scoped application transport.')

    async def _fetch_response(self,*args,**kwargs):
        if kwargs.get('stream'):raise ServiceError('Readiness uses foreground task progress, not provider streaming.')
        wire=wire_value(self._build_response_create_kwargs(*args,**kwargs))
        extra=wire.pop('extra_body',None) or {};wire.update(extra)
        for key in ('extra_headers','extra_query','stream'):wire.pop(key,None)
        wire={k:v for k,v in wire.items() if v is not None}
        wire.update(store=False,service_tier=ai.options(self.context.mode)['service_tier'],max_output_tokens=self.budget.output_limit)
        self.context.model_rounds+=1
        if self.context.model_rounds>5:raise ServiceError('Readiness reached its model-turn limit. Start another explicit action to continue.')
        if self.context.model_rounds==5 or self.context.tool_count>=8 or self.budget.used+self.budget.estimate(wire)+self.budget.final_reserve()>self.budget.ceiling:
            wire['tool_choice']='none'
            wire['instructions']+=' Investigation has ended. Return a final structured outcome from verified evidence; explain remaining limitations. Ask for clarification instead of guessing.'
        task_progress.stage('readiness_synthesis' if wire.get('tool_choice')=='none' else 'readiness_investigation')
        response=await ai.call_api(wire,retry_allowed=False)
        self.context.metadata.append(ai.metadata(response,self.context.mode))
        return Response.model_validate({k:v for k,v in response.items() if not k.startswith('_')})

async def run_agent(context,payload,instructions,tools):
    budget=Budget(context)
    if budget.final_reserve()>budget.ceiling:raise ServiceError('The action budget is too low for your saved model and response limit. Increase it or select a lower-cost AI setup.')
    agent=Agent(name='Career Readiness',instructions=instructions,model=AccountResponsesModel(context,budget),
                tools=tools,output_type=AgentEnvelope,model_settings=ModelSettings(store=False,parallel_tool_calls=False,
                reasoning={'effort':ai.effort(context.mode)},max_tokens=budget.output_limit,retry=ModelRetrySettings(max_retries=0)))
    token=ai._request_policy.set(budget)
    try:
        result=await Runner.run(agent,json.dumps(payload,ensure_ascii=False),context=context,max_turns=5,
                                run_config=RunConfig(tracing_disabled=True,trace_include_sensitive_data=False))
        return result.final_output.reply.model_dump()
    finally:ai._request_policy.reset(token)
