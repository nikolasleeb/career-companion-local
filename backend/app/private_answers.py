"""Encrypted, account-bound disclosures. Never stored in entities or evidence indexes."""
import base64
import json
import os
import re
import secrets
import stat
from pathlib import Path
from datetime import date
from typing import Literal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from . import auth, config, db
from .models import StrictModel

# Country/territory dropdowns routinely contain more than sixty choices. Share
# this bounded limit with scans so a reviewed answer retains the exact list.
MAX_OPTIONS = 500
CATEGORIES = ('veteran','protected_veteran','disability','gender','sex','citizenship','race_ethnicity','clearance_current','clearance_previous','government_employment','family_connection','conflict','additional')

class Answer(StrictModel):
    category: Literal['veteran','protected_veteran','disability','gender','sex','citizenship','race_ethnicity','clearance_current','clearance_previous','government_employment','family_connection','conflict','additional']
    question: str = Field(min_length=1,max_length=500)
    description: str = Field(default='',max_length=1500)
    context: str = Field(default='',max_length=1000)
    options: list[str] = Field(default_factory=list,max_length=MAX_OPTIONS)
    value: str = Field(min_length=1,max_length=3000)
    scope: Literal['account','employer','application'] = 'account'
    employer: str = Field(default='',max_length=250)
    application_id: str = Field(default='',max_length=64)
    effective_date: str = ''
    reviewed: Literal[True]

    @model_validator(mode='after')
    def validate_meaning(self):
        if any(not s.strip() or len(s)>500 for s in self.options) or len(set(self.options))!=len(self.options):
            raise ValueError('Provide distinct, complete choices.')
        if self.options and self.value not in self.options:raise ValueError('Choose one of the exact choices.')
        if self.scope=='employer' and not self.employer.strip():raise ValueError('Specify the employer.')
        if self.scope=='application' and not self.application_id:raise ValueError('Specify the application.')
        if self.category=='family_connection' or classify(self.question,self.description,self.context)=='family_connection':raise ValueError('Complete employer family-connection questions manually; these answers cannot be saved.')
        if self.category=='conflict' and self.scope=='account':raise ValueError('Employer-specific answers require an employer or application scope.')
        if self.category.startswith('clearance_') and not self.effective_date:raise ValueError('Record the effective date for clearance information.')
        if self.effective_date:date.fromisoformat(self.effective_date)
        return self

class Reuse(StrictModel):
    enabled: bool

def init(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS cc_vault (
      id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      ciphertext TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS cc_vault_owner ON cc_vault(user_id);
      CREATE TABLE IF NOT EXISTS cc_preferences (user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,reuse INTEGER NOT NULL DEFAULT 0);
    ''')

def key():
    """Persistent key separate from DB and ordinary exports. Never replace a missing key."""
    target=Path(config.VAULT_KEY_FILE)
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not target.exists():
        with db.connect() as c:
            if c.execute('SELECT count(*) FROM cc_vault').fetchone()[0] or c.execute('SELECT count(*) FROM cc_run_answers').fetchone()[0] or c.execute('SELECT count(*) FROM cc_private_profile').fetchone()[0]:
                raise HTTPException(503,'Private vault key is unavailable. Restore the protected key before using the vault.')
        try:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(AESGCM.generate_key(bit_length=256));f.flush();os.fsync(f.fileno())
        except FileExistsError:pass
    if stat.S_IMODE(target.stat().st_mode)&0o077:
        raise HTTPException(503,'Private vault key permissions must be owner-only.')
    raw=target.read_bytes()
    if len(raw)!=32:raise HTTPException(503,'Private vault key is invalid. Restore the protected key.')
    return raw

def seal(user,id,value):
    nonce=secrets.token_bytes(12)
    encrypted=AESGCM(key()).encrypt(nonce,json.dumps(value,separators=(',',':')).encode(),f'career-companion:v1:{user}:{id}'.encode())
    return base64.b64encode(nonce+encrypted).decode()

def unseal(user,id,ciphertext):
    try:
        raw=base64.b64decode(ciphertext,validate=True)
        return json.loads(AESGCM(key()).decrypt(raw[:12],raw[12:],f'career-companion:v1:{user}:{id}'.encode()))
    except (InvalidTag,ValueError,TypeError):
        raise HTTPException(503,'Private vault could not be authenticated. Restore its matching protected key.') from None

def validate_scope(user,body):
    if body.application_id and not db.get(user,body.application_id,'application'):raise HTTPException(404,'Application not found.')

def save(user,body,id=None):
    validate_scope(user,body);id=id or db.uid();stamp=db.now();ciphertext=seal(user,id,body.model_dump())
    with db.connect() as c:
        old=c.execute('SELECT user_id FROM cc_vault WHERE id=?',(id,)).fetchone()
        if old and old['user_id']!=user:raise HTTPException(404,'Private answer not found.')
        c.execute('INSERT INTO cc_vault VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at',(id,user,ciphertext,stamp,stamp))
    return {'id':id,'data':body.model_dump(),'updated_at':stamp}

def listing(user):
    with db.connect() as c:
        rows=c.execute('SELECT * FROM cc_vault WHERE user_id=? ORDER BY updated_at DESC',(user,)).fetchall()
    return [{'id':r['id'],'data':unseal(user,r['id'],r['ciphertext']),'updated_at':r['updated_at']} for r in rows]

def reuse(user):
    with db.connect() as c:
        row=c.execute('SELECT reuse FROM cc_preferences WHERE user_id=?',(user,)).fetchone()
    return bool(row and row['reuse'])

def normalized(value):return ' '.join(value.casefold().split())

REVIEW_CATEGORIES={'veteran','protected_veteran','sex','gender','sex_gender','race_ethnicity','disability','citizenship'}

def classify(question,description='',context=''):
    def category(text):
        if re.search(r'family.{0,20}(?:member|relation|connection)|familial|\brelatives\b|related to (?:anyone|someone|an? (?:employee|person|member))|(?:family|relativ|related to).*(?:employ|company|work|connection)|(?:employ|company|work).*(?:family|relativ|related to)',text,re.I):return 'family_connection'
        if re.search(r'citizen|nationalit',text,re.I):return 'citizenship'
        if re.search(r'protected.{0,12}veteran',text,re.I):return 'protected_veteran'
        if re.search(r'veteran',text,re.I):return 'veteran'
        if re.search(r'disab',text,re.I):return 'disability'
        gender=bool(re.search(r'gender',text,re.I));sex=bool(re.search(r'\bsex\b',text,re.I))
        if gender and sex:return 'sex_gender'
        if gender:return 'gender'
        if sex:return 'sex'
        if re.search(r'\brace\b|ethnic|hispanic|latino',text,re.I):return 'race_ethnicity'
        return ''
    return category(question) or category(' '.join((description,context)))

def category_for(user,question,description='',context=''):
    found=classify(question,description,context)
    if found:return found
    for row in listing(user):
        a=row['data']
        if normalized(a['question'])==normalized(question) and a['category'] in REVIEW_CATEGORIES|{'family_connection'}:return a['category']
    return ''

def same_question(a,question,options,description='',context=''):
    return normalized(a['question'])==normalized(question) and normalized(a.get('description',''))==normalized(description) and normalized(a.get('context',''))==normalized(context) and [normalized(x) for x in a['options']]==[normalized(x) for x in options]

def in_scope(a,application):
    return not (a['scope']=='application' and a['application_id']!=application['id'] or a['scope']=='employer' and normalized(a['employer'])!=normalized(application['data'].get('company','')))

def match(user,question,options,application,description='',context=''):
    if not reuse(user) or classify(question,description,context) in REVIEW_CATEGORIES|{'family_connection'}:return None
    for row in listing(user):
        a=row['data']
        if a['category'] in REVIEW_CATEGORIES|{'family_connection'} or classify(a['question'],a.get('description',''),a.get('context','')) in REVIEW_CATEGORIES|{'family_connection'}:continue
        if not same_question(a,question,options,description,context) or not in_scope(a,application):continue
        if a['category'].startswith('clearance_'):continue
        return a['value']
    return None

router=APIRouter(prefix='/api/private-application-answers',tags=['Private application answers'])
@router.get('')
def get_answers(user=Depends(auth.current)):
    return {'answers':[{**r,'manual_only':r['data']['category']=='family_connection' or classify(r['data']['question'],r['data'].get('description',''),r['data'].get('context',''))=='family_connection'} for r in listing(user['id'])],'automatically_reuse':reuse(user['id']),'categories':tuple(c for c in CATEGORIES if c!='family_connection')}
@router.post('')
def add_answer(body:Answer,user=Depends(auth.current)):return save(user['id'],body)
@router.put('/reuse')
def set_reuse(body:Reuse,user=Depends(auth.current)):
    with db.connect() as c:c.execute('INSERT INTO cc_preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET reuse=excluded.reuse',(user['id'],int(body.enabled)))
    return {'enabled':body.enabled}
@router.put('/{id}')
def edit_answer(id:str,body:Answer,user=Depends(auth.current)):
    with db.connect() as c:
        if not c.execute('SELECT 1 FROM cc_vault WHERE id=? AND user_id=?',(id,user['id'])).fetchone():raise HTTPException(404,'Private answer not found.')
    return save(user['id'],body,id)
@router.delete('/{id}')
def delete_answer(id:str,user=Depends(auth.current)):
    with db.connect() as c:c.execute('DELETE FROM cc_vault WHERE id=? AND user_id=?',(id,user['id']))
    return {'ok':True}
