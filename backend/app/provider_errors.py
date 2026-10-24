"""User-facing provider failures. Never expose raw provider messages or inputs."""
import math
import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .network import ServiceError

QUOTA_CODES={'insufficient_quota','billing_hard_limit_reached','credit_balance_exhausted','usage_limit_reached'}

def error_code(value):
    error=value.get('error') if isinstance(value,dict) else None
    code=(error.get('code') or error.get('type')) if isinstance(error,dict) else None
    return code if isinstance(code,str) else None

def retry_delay(headers):
    raw=headers.get('retry-after')
    if raw is not None:
        try:
            delay=float(raw)
        except (ValueError,TypeError):
            try: delay=(parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds()
            except (ValueError,TypeError,OverflowError): delay=-1
        if math.isfinite(delay) and delay>=0:return delay
    return 2+random.uniform(0,1)

def failure(status,value=None,headers=None):
    code=error_code(value)
    if status==401:message='OpenAI rejected the API key (HTTP 401). Update your key in Settings.'
    elif status==403:message='OpenAI denied access (HTTP 403). Check your project permissions and model access in Settings.'
    elif status==404 or code=='model_not_found':message='The selected OpenAI model is unavailable (HTTP '+str(status)+'). Choose a model your API project can access in Settings.'
    elif code in QUOTA_CODES:message='Your OpenAI project has no available credits or has reached its spending limit'+(' (HTTP '+str(status)+')' if status>=400 else '')+'. Check the project billing and usage limits before retrying.'
    elif status==429:message='OpenAI is temporarily rate limiting requests (HTTP 429). Wait a little before retrying.'
    elif status in (408,504):message='OpenAI did not finish in time (HTTP '+str(status)+'). Wait before retrying; the request may have incurred usage.'
    elif status>=500:message='OpenAI is temporarily unavailable (HTTP '+str(status)+'). Try again later.'
    elif status==400:message='OpenAI rejected the request settings (HTTP 400). Check the model, reasoning level and speed in Settings; your API project may restrict faster tiers. Try Standard speed.'
    else:message='OpenAI could not complete this request'+(' (HTTP '+str(status)+')' if status>=400 else '')+'. Try again later.'
    request_id=(headers or {}).get('x-request-id','')
    if re.fullmatch(r'req_[A-Za-z0-9_-]{1,100}',request_id):message+=' Support reference: '+request_id+'.'
    return ServiceError(message+' Your saved inputs and previous results remain available.')
