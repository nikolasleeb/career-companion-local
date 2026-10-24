"""Verified model options and transparent planning estimates, no provider calls."""
from . import config

PRICE_DATE='2026-10-23'
SPEED_NAMES={'standard':'Standard','fast':'Fast','ultrafast':'Ultrafast'}
EFFORTS=['none','low','medium','high','xhigh','max']
# Planning assumptions, not measured reasoning-token predictions.
REASONING_ALLOWANCE={'none':0,'low':1000,'medium':3000,'high':6000,'xhigh':10000,'max':16000}
CATALOG={
 'gpt-6.1-sol':{'name':'Sol 6.1','input':2.,'cached_input':.1,'output':10.,'efforts':['low','medium','high','xhigh','max']},
 'gpt-6-luna':{'name':'Luna 6','input':.1,'cached_input':.01,'output':.5},
 'gpt-5.6-luna':{'name':'Luna 5.6','input':.2,'cached_input':.02,'output':1.2},
 'gpt-5.6-terra':{'name':'Terra 5.6','input':2.,'cached_input':.2,'output':12.},
 'gpt-5.6-sol':{'name':'Sol 5.6','input':4.,'cached_input':.4,'output':20.},
}

def speeds(model):
    return ['standard','fast','ultrafast'] if model=='gpt-6.1-sol' else ['standard','fast'] if model in CATALOG else ['standard']

def rates(model,service_tier='default'):
    """Verified short-context rates; unknown tiers remain unpriced, never free."""
    base=next((v for k,v in CATALOG.items() if model==k or model.startswith(k+'-')),None)
    canonical=next((k for k in CATALOG if model==k or model.startswith(k+'-')),model)
    tier={'default':'standard','priority':'fast'}.get(service_tier,service_tier)
    if not base or tier not in speeds(canonical):return None
    multiplier={'standard':1,'fast':2,'ultrafast':6}[tier]
    return {k:round(base[k]*multiplier,12) for k in ('input','cached_input','output')}

def validate_custom(profile):
    model=profile.get('custom_model','gpt-5.6-terra');effort=profile.get('custom_reasoning','medium')
    if model not in CATALOG or effort not in CATALOG[model].get('efforts',EFFORTS):
        raise ValueError('This model does not support the selected reasoning level. GPT-6.1 Sol requires Low or higher.')
    if profile.get('custom_speed','standard') not in speeds(model):
        raise ValueError('This model does not support the selected speed. Choose Standard or Fast, or use Sol 6.1 for Ultrafast.')

def resolve(profile,mode=None):
    mode=mode or profile.get('mode','economy')
    if mode=='custom':
        validate_custom(profile)
        model=profile.get('custom_model','gpt-5.6-terra')
        effort=profile.get('custom_reasoning','medium')
        speed=profile.get('custom_speed','standard')
    else:
        model=config.MODEL;effort='high' if mode=='deep' else 'low';speed='standard'
    return {'model':model,'reasoning_effort':effort,'mode':mode,'speed':speed,'service_tier':'default' if speed=='standard' else speed}

def estimate(model,effort,input_tokens=6000,answer_tokens=1500,service_tier='default'):
    rate=rates(model,service_tier)
    output=answer_tokens+REASONING_ALLOWANCE[effort]
    return {'usd':round((input_tokens*rate['input']+output*rate['output'])/1_000_000,6) if rate else None,
            'input_tokens':input_tokens,'answer_tokens':answer_tokens,'assumed_reasoning_tokens':REASONING_ALLOWANCE[effort],
            'total_output_tokens':output,'service_tier':service_tier,'pricing_date':PRICE_DATE,'kind':'illustrative estimate; not a quote'}

def public(profile):
    active=resolve(profile)
    return {'active':{**active,'estimate':estimate(active['model'],active['reasoning_effort'],service_tier=active['service_tier'])},
            'catalog':[{**rate,'id':model,'efforts':rate.get('efforts',EFFORTS),'speeds':[{'id':speed,'name':SPEED_NAMES[speed],'rates':rates(model,speed)} for speed in speeds(model)],'url':'https://developers.openai.com/api/docs/models/'+model} for model,rate in CATALOG.items()],
            'reasoning_allowance':REASONING_ALLOWANCE,'pricing_date':PRICE_DATE,
            'custom_model':profile.get('custom_model','gpt-5.6-terra'),'custom_reasoning':profile.get('custom_reasoning','medium'),'custom_speed':profile.get('custom_speed','standard')}

def cache_counts(usage,ttl='30m'):
    def count(value):return value if type(value) is int and value>=0 else 0
    incoming=count(usage.get('input_tokens'));details=usage.get('input_tokens_details') or {}
    if not isinstance(details,dict):return None
    cached=min(incoming,count(details.get('cached_tokens',usage.get('cached_input_tokens'))))
    writes=count(details.get('cache_write_tokens',details.get('cache_creation_tokens',usage.get('cache_write_tokens'))))
    split=details.get('cache_write_tokens_details')
    if isinstance(split,dict):short=count(split.get('ttl_30m_tokens'));long=count(split.get('ttl_12h_tokens'))
    elif 'cache_write_30m_tokens' in usage:short=count(usage.get('cache_write_30m_tokens'));long=count(usage.get('cache_write_12h_tokens'))
    else:short,long=(0,writes) if ttl=='12h' else (writes,0)
    if short+long!=writes or cached+writes>incoming:return None
    return {'cached_input_tokens':cached,'cache_write_tokens':writes,'cache_write_30m_tokens':short,'cache_write_12h_tokens':long}

def usage_cost(model,usage,cache_ttl='30m',service_tier='default'):
    # Provider snapshot IDs use the base model's published rates.
    rate=rates(model,service_tier)
    if not rate:return None
    input_count=usage.get('input_tokens',0);output_count=usage.get('output_tokens',0)
    cache=cache_counts(usage,cache_ttl)
    if cache is None:return None
    cached=cache['cached_input_tokens'];writes=cache['cache_write_tokens']
    long=input_count>272000
    # Write tokens replace ordinary input billing; they are not an additive fee.
    weighted=(input_count-cached-writes)*rate['input']+cached*rate['cached_input']+cache['cache_write_30m_tokens']*rate['input']*1.25+cache['cache_write_12h_tokens']*rate['input']*2.5
    return round(weighted*(2 if long else 1)/1_000_000+output_count*rate['output']*(1.5 if long else 1)/1_000_000,6)
