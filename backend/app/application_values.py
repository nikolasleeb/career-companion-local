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
    country_names={key:r['code'].lower() for r in private_profile.countries() for key in (r['code'].lower(),label_key(r['name']))} if field=='country' else {}
    def canonical(v):
        v=label_key(str(v)).replace('’',"'")
        if field=='country':
            v={'usa':'us','u.s.':'us','united states of america':'us'}.get(v,v)
            return country_names.get(v,v)
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
    def started(r):
        data=r['data'];start=data.get('start_date','') or re.split(r'\s+[–—-]\s+',data.get('dates',''))[0]
        return month_value(start,'month') or ''
    return sorted([r for r in db.list_entities(user,'experience') if r['data'].get('confirmed') and r['data'].get('category')==section],key=lambda r:(started(r),r['created_at'],r['id']),reverse=True)


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
    # A saved business-unit name can use its unambiguous employer catalog name.
    # Keep the original Profile record intact; never pick arbitrary near matches.
    if prop=='organization' and data.get('category')=='employment':
        value={'amazon fulfillment centers':'Amazon'}.get(label_key(value),value)
    value=month_value(value,field.control)
    return option_value(value,field.options,prop or '')


PERSONAL_LABELS={
 'first name':'legal_first_name','first name (legal)':'legal_first_name','legal first name':'legal_first_name','given name':'legal_first_name',
 'middle name':'middle_name','middle initial':'middle_initial','last name':'last_name','last/family name':'last_name','family name':'last_name','surname':'last_name',
 'first name (preferred)':'preferred_first_name','preferred first name':'preferred_first_name','preferred name':'preferred_first_name',
 'address line 1':'address_line1','address line1':'address_line1','street address':'address_line1','address':'address_line1',
 'address line 2':'address_line2','address line2':'address_line2','apartment':'address_line2',
 'zip/postal code':'postal_code','zip / postal code':'postal_code','zip code':'postal_code','postal code':'postal_code','postcode':'postal_code','zip':'postal_code',
 'legal name':'legal_full_name','full legal name':'legal_full_name',
}
PERSONAL_AUTO={'given-name':'legal_first_name','additional-name':'middle_name','family-name':'last_name','address-line1':'address_line1','address-line2':'address_line2','postal-code':'postal_code'}
def personal_property(field):
    # Autocomplete is a hint, never permission to repurpose a disclosure question.
    key=label_key(field.label)
    if key in PERSONAL_LABELS:return PERSONAL_LABELS[key]
    return PERSONAL_AUTO.get(field.autocomplete)

def personal_value(user,field):
    prop=personal_property(field)
    if not prop:return None
    saved=private_profile.load(user,'personal_details')
    if saved is None:return None
    if prop=='preferred_first_name' and saved.get('preferred_same_as_legal'):value=saved.get('legal_first_name','')
    elif prop=='middle_initial':value=saved.get('middle_name','')[:1]
    elif prop=='legal_full_name':value=' '.join(saved.get(k,'') for k in ('legal_first_name','middle_name','last_name') if saved.get(k))
    else:value=saved.get(prop,'')
    return option_value(value,field.options,prop)

def intentional_blank(user,field):
    prop=personal_property(field)
    if field.required or not prop:return False
    saved=private_profile.load(user,'personal_details')
    return saved is not None and personal_value(user,field) is None and prop in ('middle_name','middle_initial','address_line2','preferred_first_name') and not (prop=='preferred_first_name' and saved.get('preferred_same_as_legal') and saved.get('legal_first_name'))


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
        if field.entry_id:
            selected=next((r for r in saved if r['id']==field.entry_id),None)
            return entry_value(selected,field) if selected else None
        return entry_value(saved[field.repeat_index],field) if field.repeat_index<len(saved) else None
    personal=personal_value(user,field)
    if personal_property(field):return personal
    settings=db.settings(user)
    props={'name':'name','full name':'name','email':'email','email address':'email','preferred email':'email','confirm email':'email','confirm email address':'email','phone':'phone','phone number':'phone','city':'city','state':'state','country':'country','linkedin':'linkedin','linkedin profile':'linkedin','website':'website','portfolio website':'website','github':'github','github profile':'github','github url':'github','github profile url':'github','github link':'github','github profile link':'github'}
    auto={'name':'name','email':'email','tel':'phone','address-level2':'city','address-level1':'state','country-name':'country','country':'country','url':'website'}
    prop=auto.get(field.autocomplete) or props.get(key)
    # Private application identity never enters the general settings accessor.
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


def organization_key(value):
    key=label_key(value)
    return {'amazon fulfillment centers':'amazon'}.get(key,key)


def bind_repeated_rows(user, metadata):
    """Match occupied rows before assigning empty slots; never combine entries."""
    bindings={};targets=[]
    for section in ('education','employment'):
        saved=rows(user,section);physical=[r for r in metadata.repeat_rows if r.section==section]
        if not physical:continue
        used=set();ambiguous=False
        for row in physical:
            if not row.organization and not row.title:continue
            matches=[r for r in saved if (not row.organization or organization_key(r['data'].get('organization',''))==organization_key(row.organization)) and (not row.title or (option_value(r['data'].get('degree',''),[row.title],'degree') if section=='education' else label_key(r['data'].get('title',''))==label_key(row.title)))]
            if len(matches)==1 and matches[0]['id'] not in used:
                bindings[(section,row.index)]=matches[0]['id'];used.add(matches[0]['id'])
            else:bindings[(section,row.index)]='unmatched';ambiguous=True
        available=iter(r for r in saved if r['id'] not in used)
        for row in physical:
            key=(section,row.index)
            if key not in bindings:bindings[key]=next(available,{'id':'unmatched'})['id']
        descriptor=next((r for r in metadata.repeat_sections if r.section==section),None)
        if not ambiguous and descriptor and descriptor.count==len(physical) and sorted(r.index for r in physical)==list(range(len(physical))) and descriptor.count<len(saved):
            targets.append({'section':section,'count':min(len(saved),10)})
    return bindings,targets
