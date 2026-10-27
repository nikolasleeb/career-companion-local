"""Optional encrypted private profile. Values never become professional evidence."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from . import auth, config, db, private_answers
from .models import StrictModel

AUTH_FIELDS=('us_citizen','authorized_us','sponsorship_now','sponsorship_future')
SECTIONS=('citizenship','veteran','sex_gender','race_ethnicity','disability')
CHOICES={
 'veteran':['Veteran','Not a veteran','Unsure','Prefer not to answer'],
 'protected_veteran':['Protected veteran','Not a protected veteran','Unsure','Prefer not to answer'],
 'sex':['Female','Male','Intersex','Self-describe','Prefer not to answer'],
 'gender':['Woman','Man','Non-binary','Self-describe','Prefer not to answer'],
 'race_ethnicity':['American Indian or Alaska Native','Asian','Black or African American','Hispanic or Latino','Middle Eastern or North African','Native Hawaiian or Pacific Islander','White','Self-describe','Prefer not to answer'],
 'disability':['Yes','No','Unsure','Prefer not to answer'],
}

def countries():
    return json.loads((config.CONTENT_DIR/'countries.json').read_text())['countries']

class Citizenship(StrictModel):
    countries: list[str] = Field(default_factory=list,max_length=250)
    us_citizen: Literal['','yes','no','unsure']
    authorized_us: Literal['','yes','no','unsure']
    sponsorship_now: Literal['','yes','no','unsure']
    sponsorship_future: Literal['','yes','no','unsure']
    reviewed: Literal[True]
    @model_validator(mode='after')
    def valid_countries(self):
        allowed={r['code'] for r in countries()}
        if len(set(self.countries))!=len(self.countries) or any(v not in allowed for v in self.countries):
            raise ValueError('Select distinct countries from the country catalog.')
        return self

class Disclosure(StrictModel):
    values: dict[str,str|list[str]]
    reviewed: Literal[True]

def validate_disclosure(section,body):
    keys={'veteran':{'veteran','protected_veteran'},'sex_gender':{'sex','gender','sex_description','gender_description'},'race_ethnicity':{'race_ethnicity','description'},'disability':{'disability'}}[section]
    if set(body.values)-keys:raise HTTPException(422,'Unsupported private profile field.')
    result={}
    for field in keys:
        if field.endswith('_description') or field=='description':
            value=body.values.get(field,'')
            if not isinstance(value,str) or len(value)>500:raise HTTPException(422,'Self-description must be at most 500 characters.')
            result[field]=value.strip();continue
        value=body.values.get(field,[] if section=='race_ethnicity' else '')
        if section=='race_ethnicity':
            if not isinstance(value,list) or len(value)>len(CHOICES[field]) or len(set(value))!=len(value) or any(v not in CHOICES[field] for v in value):raise HTTPException(422,'Select distinct supported choices.')
            if 'Prefer not to answer' in value and len(value)!=1:raise HTTPException(422,'Prefer not to answer cannot be combined with other choices.')
        elif not isinstance(value,str) or value not in ['',*CHOICES[field]]:raise HTTPException(422,'Choose a supported answer.')
        result[field]=value
    for field,description in [('sex','sex_description'),('gender','gender_description'),('race_ethnicity','description')]:
        if field not in result:continue
        self_described='Self-describe' in result[field] if isinstance(result[field],list) else result[field]=='Self-describe'
        if self_described and not result.get(description):raise HTTPException(422,'Add your self-description before saving.')
        if not self_described and result.get(description):raise HTTPException(422,'Self-description requires the Self-describe choice.')
    return result

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS cc_private_profile (
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      section TEXT NOT NULL,ciphertext TEXT NOT NULL,updated_at TEXT NOT NULL,
      PRIMARY KEY(user_id,section))''')

def seal(user,section,value):return private_answers.seal(user,'private-profile:'+section,value)
def load(user,section):
    with db.connect() as c:row=c.execute('SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section=?',(user,section)).fetchone()
    return private_answers.unseal(user,'private-profile:'+section,row['ciphertext']) if row else None

def store(c,user,section,cipher):
    c.execute('INSERT INTO cc_private_profile VALUES(?,?,?,?) ON CONFLICT(user_id,section) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at',(user,section,cipher,db.now()))

def authorization(user):
    return load(user,'authorization') or {}

def update_settings(c,user,changes):
    """Keep the legacy settings accessor while storing private statuses only in the vault."""
    row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()
    if not row:raise HTTPException(404,'Account not found.')
    original=json.loads(row['settings'])
    legacy={k:original[k] for k in AUTH_FIELDS if k in original}
    private={k:v for k,v in changes.items() if k in AUTH_FIELDS}
    if private or legacy:
        row=c.execute("SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section='authorization'",(user,)).fetchone()
        old=private_answers.unseal(user,'private-profile:authorization',row['ciphertext']) if row else {}
        values={**legacy,**old,**private}
        if any(v not in ('','yes','no','unsure') for v in values.values()):raise HTTPException(422,'Unsupported authorization answer.')
        cipher=seal(user,'authorization',values)
        if private_answers.unseal(user,'private-profile:authorization',cipher)!=values:raise HTTPException(503,'Private answers could not be verified.')
        store(c,user,'authorization',cipher)
    public={k:v for k,v in {**original,**changes}.items() if k not in AUTH_FIELDS}
    c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(public),user))

def migrate_statuses():
    # Resolve/create the key before holding the write lock. Missing keys never regenerate.
    with db.connect() as c:
        needed=any(any(k in json.loads(r['settings']) for k in AUTH_FIELDS) for r in c.execute('SELECT settings FROM users'))
    if not needed:return
    private_answers.key()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('PRAGMA secure_delete=ON')
        for row in c.execute('SELECT id,settings FROM users').fetchall():
            if any(k in json.loads(row['settings']) for k in AUTH_FIELDS):update_settings(c,row['id'],{})
    with db.connect() as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')

def warnings(codes,settings):
    if codes and ((settings.get('us_citizen')=='yes' and 'US' not in codes) or (settings.get('us_citizen')=='no' and 'US' in codes)):
        return ['Your citizenship countries and U.S.-citizen answer differ. Review them; neither answer was changed automatically.']
    return []

router=APIRouter(prefix='/api/private-application-profile',tags=['Private application profile'])
@router.get('')
def get_profile(user=Depends(auth.current)):
    sections={s:load(user['id'],s) for s in SECTIONS}
    return {'sections':sections,'countries':countries(),'choices':CHOICES,'warnings':warnings((sections['citizenship'] or {}).get('countries',[]),db.settings(user['id'])),'review_only':True}

@router.put('/citizenship')
def save_citizenship(body:Citizenship,user=Depends(auth.current)):
    cipher=seal(user['id'],'citizenship',{'countries':body.countries})
    changes=body.model_dump(exclude={'countries','reviewed'})
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        update_settings(c,user['id'],changes)
        store(c,user['id'],'citizenship',cipher)
    settings=db.settings(user['id'])
    return {'saved':True,'warnings':warnings(body.countries,settings)}

@router.put('/{section}')
def save_disclosure(section:str,body:Disclosure,user=Depends(auth.current)):
    if section not in SECTIONS or section=='citizenship':raise HTTPException(404,'Private profile section not found.')
    value=validate_disclosure(section,body);cipher=seal(user['id'],section,value)
    with db.connect() as c:store(c,user['id'],section,cipher)
    return {'saved':True,'review_only':True}

@router.delete('/{section}')
def clear_section(section:str,user=Depends(auth.current)):
    if section not in SECTIONS:raise HTTPException(404,'Private profile section not found.')
    with db.connect() as c:c.execute('DELETE FROM cc_private_profile WHERE user_id=? AND section=?',(user['id'],section))
    return {'cleared':True}

def suggestions(user,question,application):
    category=question.get('private_category') or private_answers.category_for(user,question['label'],question.get('description',''),question.get('context',''))
    if category=='family_connection':return {'suggestions':[],'manual_only':True,'requires_review':True}
    section={'citizenship':'citizenship','veteran':'veteran','protected_veteran':'veteran','sex':'sex_gender','gender':'sex_gender','sex_gender':'sex_gender','race_ethnicity':'race_ethnicity','disability':'disability'}.get(category)
    result=[]
    if section:
        value=load(user,section) or {}
        if category=='citizenship' and value.get('countries'):
            names={r['code']:r['name'] for r in countries()}
            result.append({'label':'Citizenship countries','value':', '.join(names.get(v,v) for v in value['countries']),'source':'private_profile'})
        else:
            for field in (['sex','gender'] if category=='sex_gender' else [category]):
                answer=value.get(field)
                if not answer:continue
                display='; '.join(answer) if isinstance(answer,list) else answer
                detail=value.get(field+'_description') or (value.get('description') if field=='race_ethnicity' else '')
                if detail:display+=': '+detail
                result.append({'label':{'protected_veteran':'Protected-veteran status','sex':'Sex','gender':'Gender','veteran':'Veteran status','race_ethnicity':'Race / ethnicity','disability':'Disability'}.get(field,field),'value':display,'source':'private_profile'})
    for row in private_answers.listing(user):
        a=row['data']
        if a['category'] not in private_answers.REVIEW_CATEGORIES:continue
        if private_answers.same_question(a,question['label'],question.get('options',[]),question.get('description',''),question.get('context','')) and private_answers.in_scope(a,application):
            result.append({'label':'Previously reviewed answer for this exact question','value':a['value'],'source':'saved_question'})
    return {'suggestions':result,'requires_review':True,'manual_only':False}
