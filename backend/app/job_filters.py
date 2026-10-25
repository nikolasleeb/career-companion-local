"""Explicit career and hard-filter policy; unknown facts are never invented."""
import re
from . import job_locations
ALL=['internship','early_career','mid_career']
SENIOR=r'\b(senior|sr\.?|principal|director|head of|chief|vice president|vp|cto|cfo|ceo)\b|\bstaff\b.*\b(engineer|scientist)\b'
MANAGER=r'\b(manager|supervisory|supervisor|supv|lead)\b'
def levels(request):
 value=getattr(request,'career_levels',None)
 return value if value is not None else ALL if 'any' in request.job_types else list(request.job_types)
def career(job):
 title=job['title'];text=job.get('description','')
 if re.search(SENIOR,title,re.I):return 'senior'
 if re.search(r'\bintern(?:ship)?\b',title+' '+job.get('employment_type',''),re.I):return 'internship'
 if re.search(MANAGER,title,re.I) and not re.search(r'account manager|lead generation',title,re.I):return 'mid_career'
 lines=re.findall(r'[^.!?\n]{0,100}\b\d+\s*(?:[-–]\s*\d+)?\+?\s+years?[^.!?\n]{0,100}',text,re.I)
 years=[int(m.group(1)) for line in lines if re.search(r'requir|minimum|at least',line,re.I) and not re.search(r'preferred|desired|equivalent|in lieu|\bGS[- ]?\d',line,re.I) for m in re.finditer(r'(\d+)\s*(?:[-–]\s*\d+)?\+?\s+years?',line,re.I)]
 if years:return 'mid_career' if min(years)>=4 else 'early_career'
 if re.search(r'entry[- ]level|new grad|recent grad|junior|\bengineer (?:i|1)\b',title,re.I) or re.search(r'no (?:prior |previous )?experience required',text,re.I):return 'early_career'
 return 'unknown'
def location(job,request):
 wanted=getattr(request,'locations',[]) or [request.location]
 states=[job_locations.matches(job,q) for q in wanted]
 if any(s is True for s in states):
  choices=[job.get('location','')]+[str(v.get('location',''))+(', '+str(v['state']) if v.get('state') else '') for v in job.get('locations',[]) if isinstance(v,dict)]
  for v in choices:
   if v and any(job_locations.matches({'location':v},q) is True for q in wanted):job['matching_location']=v;break
  return True
 return None if None in states else False

def salary(job):
 structured=job.get('salary_details')
 if structured:return structured
 value=str(job.get('salary') or '')
 if not value or value=='Not stated':return None
 period='hour' if re.search(r'\b(hour|hourly|hr)\b',value,re.I) else 'year' if re.search(r'\b(year|annual|annually|yr)\b',value,re.I) or re.search(r'\d\s*[kK]\b',value) else None
 if not period:return None
 amounts=[]
 for n,k in re.findall(r'(?<!\w)(\d[\d,]*(?:\.\d+)?)\s*([kK]?)(?!\w)',value):
  amounts.append(float(n.replace(',',''))*(1000 if k else 1))
 if not amounts:return None
 return {'minimum':min(amounts),'maximum':max(amounts),'currency':'USD','period':period,'estimated':'estimate' in value.casefold()}
def pay(job,request):
 minimum=getattr(request,'minimum_salary',None)
 if minimum is None:return True
 data=salary(job)
 if not data or data.get('estimated') or data.get('currency')!='USD' or data.get('period')!=request.pay_period:return None
 return data.get('maximum',0)>=minimum
