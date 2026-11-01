"""Deterministic saved-field candidates; no model calls and no new Profile facts."""
import re
from datetime import datetime, date
from . import db, private_answers, private_profile


def label_key(value):
    value=private_answers.normalized(value).strip(' :*?')
    return 'school' if value.startswith('school please select ') else 'employer' if value.startswith('employer if employer ') else value


def option_value(value, options, field=''):
    if not value:return None
    if not options:return str(value)
    def canonical(v):
        v=label_key(str(v)).replace('’',"'")
        if field=='country':
            return {'us':'united states','usa':'united states','u.s.':'united states','united states of america':'united states'}.get(v,v)
        if field=='degree':
            if re.fullmatch(r"master(?:'s|s)?(?: degree)?|m\.?s\.?|master of (science|arts)(?: \([^)]+\))?",v):return 'masters'
            if re.fullmatch(r"bachelor(?:'s|s)?(?: degree)?|b\.?s\.?|bachelor of (science|arts)(?: \([^)]+\))?",v):return 'bachelors'
        if field=='state':
            from .job_locations import STATES
            # Catalog formats differ across editions; exact matching remains safe.
            if isinstance(STATES,dict):return label_key(STATES.get(v.upper(),v))
        return v
    matches=[o for o in options if canonical(o)==canonical(value)]
    return matches[0] if len(matches)==1 else None


def section_for(field):
    if field.section:return field.section
    key=label_key(field.label)
    if key in ('job title','current job','employer','company','company name'):return 'employment'
    if key in ('school','school name','university','education level','primary major/program','major','degree','field of study','as of today, have you completed this degree/program'):return 'education'
    return ''


def rows(user, section):
    return sorted([r for r in db.list_entities(user,'experience') if r['data'].get('confirmed') and r['data'].get('category')==section],key=lambda r:(r['data'].get('start_date',''),r['created_at'],r['id']),reverse=True)


def month_value(value, control):
    value=str(value or '').strip()
    if control not in ('date','month'):return value
    for fmt in ('%Y-%m-%d','%Y-%m','%B %Y','%b %Y','%m/%Y'):
        try:
            parsed=datetime.strptime(value,fmt)
            # Never invent a day when only month precision is known.
            if control=='date' and fmt!='%Y-%m-%d':return None
            return parsed.strftime('%Y-%m' if control=='month' else '%Y-%m-%d')
        except ValueError:pass
    return None


def entry_value(row,field):
    data=row['data'];key=label_key(field.label)
    mapping={'school':'organization','school name':'organization','university':'organization','employer':'organization','company':'organization','company name':'organization','job title':'title','title':'title','degree':'degree','education level':'degree','major':'major','primary major/program':'major','field of study':'major','start date':'start_date','end date':'end_date'}
    prop=mapping.get(key);value=data.get(prop,'') if prop else ''
    if key=='current job':
        end=label_key(data.get('end_date','') or (re.split(r'\s+[–—-]\s+',data.get('dates',''))[-1] if re.search(r'\s+[–—-]\s+',data.get('dates','')) else ''))
        value='Yes' if end in ('present','current','ongoing') else 'No' if month_value(end,'month') else ''
        # An empty end date alone does not establish current employment.
    if key=='as of today, have you completed this degree/program':
        if data.get('expected_graduation'):value='No'
        else:
            end=month_value(data.get('end_date',''),'month')
            value='Yes' if end and end<date.today().strftime('%Y-%m') else ''
    if not value and prop in ('start_date','end_date'):
        period=re.split(r'\s+[–—-]\s+',data.get('dates',''))
        if len(period)==2:value=period[0 if prop=='start_date' else 1]
    value=month_value(value,field.control)
    return option_value(value,field.options,prop or '')


def candidates(user,field):
    settings=db.settings(user);key=label_key(field.label);result=[]
    section=section_for(field)
    if section:
        for row in rows(user,section):
            value=entry_value(row,field)
            if value:result.append({'label':row['data']['title']+' · '+row['data'].get('organization',''),'value':value,'source':'confirmed_profile','experience_id':row['id']})
        return result
    aliases={'address line 1':'street','street address':'street','address':'street','address line 2':'street2','apartment':'street2','zip/postal code':'postal','zip code':'postal','postal code':'postal','country':'country','first name (legal)':'legal_first','legal first name':'legal_first','first name':'first','given name':'first','last name':'last','family name':'last','first name (preferred)':'preferred','preferred first name':'preferred','preferred name':'preferred','middle name':'middle'}
    prop=aliases.get(key)
    if prop:
        for saved in private_answers.listing(user):
            a=saved['data']
            if aliases.get(label_key(a.get('question','')))==prop and a.get('scope')=='account':
                value=option_value(a.get('value',''),field.options,prop)
                if value:result.append({'label':'Previously reviewed '+a['question'],'value':value,'source':'saved_question'})
    # Full names do not establish the user's legal/preferred name or how multi-part names split.
    name=settings.get('name','').strip();parts=name.split()
    namefield=bool(re.search(r'\b(first|given|last|family|middle|preferred) name\b',key))
    if namefield and len(parts)>=2:
        value=parts[-1] if re.search(r'last|family',key) else ' '.join(parts[1:-1]) if 'middle' in key else parts[0]
        if value:result.append({'label':'From your saved full name: '+name+' — confirm the name parts','value':value,'source':'profile_name_review'})
    return result


def automatic(user,field):
    key=label_key(field.label);section=section_for(field)
    if section:
        saved=rows(user,section)
        # Without a recognized repeated section, several entries require an explicit choice.
        if not field.section and len(saved)!=1:return None
        return entry_value(saved[field.repeat_index],field) if field.repeat_index<len(saved) else None
    settings=db.settings(user)
    props={'name':'name','full name':'name','email':'email','email address':'email','preferred email':'email','confirm email':'email','confirm email address':'email','phone':'phone','phone number':'phone','city':'city','state':'state','country':'country','linkedin':'linkedin','linkedin profile':'linkedin','website':'website','portfolio website':'website','github':'github','github profile':'github','github url':'github','github profile url':'github','github link':'github','github profile link':'github'}
    auto={'name':'name','email':'email','tel':'phone','address-level2':'city','address-level1':'state','country-name':'country','country':'country','url':'website'}
    prop=auto.get(field.autocomplete) or props.get(key)
    # given-name/family-name still require review unless separately saved for that exact question.
    return option_value(settings.get(prop,'') if prop else '',field.options,prop or '')


def authorization_suggestions(user,question):
    key=label_key(question['label']);values=private_profile.authorization(user);result=[]
    if re.search(r'authoriz\w* to work (?:in (?:the )?)?(?:u\.?s\.?|united states)',key):
        keys=['authorized_us']
    elif 'sponsor' in key and re.search(r'visa|employment|work',key):
        keys=['sponsorship_now','sponsorship_future'] if re.search(r'now.*future',key) else ['sponsorship_future'] if 'future' in key else ['sponsorship_now'] if re.search(r'now|currently',key) else []
    else:keys=[]
    labels={'authorized_us':'U.S. work authorization','sponsorship_now':'Sponsorship now','sponsorship_future':'Sponsorship in the future'}
    for k in keys:
        if values.get(k):result.append({'label':labels[k]+' · saved private setting','value':values[k].capitalize(),'source':'private_profile'})
    return result
