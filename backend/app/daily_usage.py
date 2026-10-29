"""Small read-only account ledger summary. Warning thresholds never gate requests."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from fastapi import APIRouter,Depends,HTTPException,Query
from . import db,auth,cost_history
router=APIRouter(prefix='/api/usage')
def summary(user,tz='UTC',now=None):
 settings=db.settings(user);name=settings.get('usage_timezone') or tz or 'UTC'
 try:zone=ZoneInfo(name)
 except (ValueError,ZoneInfoNotFoundError):raise HTTPException(422,'Choose a valid day-boundary timezone.')
 now=now or datetime.now(timezone.utc);today=now.astimezone(zone).date();rows={}
 # No history recovery, repricing or provider requests on a frequently polled read.
 for record in db.list_entities(user,'usage_event'):
  d=record['data']
  if datetime.fromisoformat(d['occurred_at']).astimezone(zone).date()!=today:continue
  if d['event_key'] not in rows or rows[d['event_key']]['status']=='pending':rows[d['event_key']]=d
 values=list(rows.values());totals=cost_history.totals(values);limit=settings.get('daily_spend_warning_usd') or 0;amount=totals['estimated_cost_usd']
 ratio=amount/limit if limit and amount is not None else None
 midnight=datetime.combine(today+timedelta(days=1),datetime.min.time(),zone)
 return {'date':today.isoformat(),'timezone':name,'estimated_cost_usd':amount,'estimated_cost_upper_usd':totals['estimated_cost_upper_usd'],'partial':bool(totals['unpriced_requests']),'pending_requests':sum(v['status']=='pending' for v in values),'unpriced_requests':totals['unpriced_requests'],'requests':len(values),'warning_limit_usd':limit,'percent':round(ratio*100,2) if ratio is not None else None,'warning_state':'limit' if ratio is not None and ratio>=1 else 'near' if ratio is not None and ratio>=.8 else 'normal','updated_at':now.isoformat(),'next_midnight':midnight.isoformat()}
@router.get('/today')
def today(tz:str=Query(default='UTC',max_length=100),user=Depends(auth.current)):return summary(user['id'],tz)
