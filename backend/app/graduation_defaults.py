"""Calendar defaults based only on reviewed, precision-preserving education dates."""
import calendar,re
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
from . import db
BOTH=['internship','early_career']
def interval(value):
    value=str(value or '').strip()
    # Stored date precision is the text itself: YYYY, YYYY-MM, or YYYY-MM-DD.
    match=re.fullmatch(r'(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?',value)
    if not match:
        for fmt,precision in [('%B %Y','month'),('%b %Y','month'),('%B %d, %Y','day'),('%b %d, %Y','day')]:
            try:
                parsed=datetime.strptime(value,fmt).date()
                return (parsed,parsed) if precision=='day' else (parsed.replace(day=1),parsed.replace(day=calendar.monthrange(parsed.year,parsed.month)[1]))
            except ValueError:pass
        return None
    y,m,d=map(lambda v:int(v) if v else None,match.groups())
    try:
        return (date(y,m,d),date(y,m,d)) if d else (date(y,m,1),date(y,m,calendar.monthrange(y,m)[1])) if m else (date(y,1,1),date(y,12,31))
    except ValueError:return None

def for_profile(user,zone='UTC',now=None):
    today=(now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone)).date()
    month=today.month-1+9;y=today.year+month//12;m=month%12+1
    cutoff=date(y,m,min(today.day,calendar.monthrange(y,m)[1]))
    education=[r['data'] for r in db.list_entities(user,'experience') if r['data'].get('category')=='education' and r['data'].get('confirmed')]
    upcoming=[];uncertain=False;completed=False
    for d in education:
        expected=str(d.get('expected_graduation') or '').strip()
        if expected:
            span=interval(expected)
            if not span:uncertain=True
            elif span[1]<today:completed=True
            elif span[0]<today:uncertain=True
            else:upcoming.append(span)
        else:
            end=interval(d.get('end_date'))
            if end and end[1]<today:completed=True
            else:uncertain=True
    types=BOTH;reason='Graduation timing is missing or uncertain, so both job types are selected.'
    if upcoming and not uncertain:
        earliest=min(upper for _,upper in upcoming)
        # Ranges that overlap the nearest program may be the nearest graduation.
        candidates=[span for span in upcoming if span[0]<=earliest]
        if all(upper<=cutoff for _,upper in candidates):
            types=['early_career'];reason='Your nearest expected graduation is within nine calendar months. Full-time roles are selected.'
        elif all(lower>cutoff for lower,_ in candidates):
            types=['internship'];reason='Your nearest expected graduation is more than nine calendar months away. Internships are selected.'
        else:reason='Your graduation date is not precise enough to resolve the nine-month boundary. Both job types are selected.'
    elif completed and not uncertain:
        types=['early_career'];reason='Your reviewed education is completed, with no current undated program. Full-time roles are selected.'
    return {'job_types':types,'explanation':reason,'timezone':zone,'as_of':today.isoformat()}
