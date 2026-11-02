"""Explicit application identity/address, isolated from resume and model context."""
import hashlib,json
from fastapi import HTTPException
from pydantic import Field,model_validator
from . import db,private_answers
from .models import StrictModel,SettingsUpdate

SECTION='personal_details'
PUBLIC=('name','contact','contact_reviewed','headline','use_professional_headline','email','phone','city','state','country','county','website','linkedin','github')
class ApplicationDetails(StrictModel):
    legal_first_name:str=Field(default='',max_length=150)
    middle_name:str=Field(default='',max_length=150)
    last_name:str=Field(default='',max_length=150)
    preferred_first_name:str=Field(default='',max_length=150)
    preferred_same_as_legal:bool=Field(default=False,strict=True)
    address_line1:str=Field(default='',max_length=250)
    address_line2:str=Field(default='',max_length=250)
    postal_code:str=Field(default='',max_length=40)

class PersonalDetailsSave(StrictModel):
    revision:str=Field(min_length=64,max_length=64)
    profile:SettingsUpdate
    application:ApplicationDetails
    @model_validator(mode='after')
    def limited_profile(self):
        if set(self.profile.model_fields_set)-set(PUBLIC):raise ValueError('Only personal contact fields can be saved here.')
        return self

def snapshot(c,user):
    row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()
    if not row:raise HTTPException(404,'Account not found.')
    values=json.loads(row['settings']);public={k:values[k] for k in PUBLIC if k in values}
    row=c.execute('SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section=?',(user,SECTION)).fetchone()
    application=private_answers.unseal(user,'private-profile:'+SECTION,row['ciphertext']) if row else None
    revision=hashlib.sha256(json.dumps([user,public,application],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'profile':public,'application':application,'revision':revision}

def get(user):
    from . import private_profile
    with db.connect() as c:result=snapshot(c,user)
    return {**result,'countries':private_profile.countries()}

def save(user,body):
    from . import private_profile
    application={k:v.strip() if isinstance(v,str) else v for k,v in body.application.model_dump().items()}
    # Verify encryption before beginning the transaction; no plaintext fallback.
    cipher=private_profile.seal(user,SECTION,application)
    if private_answers.unseal(user,'private-profile:'+SECTION,cipher)!=application:raise HTTPException(503,'Personal details could not be verified.')
    public={k:v.strip() if isinstance(v,str) else v for k,v in body.profile.model_dump(exclude_none=True).items()}
    country=public.get('country','');match=next((r['name'] for r in private_profile.countries() if country.casefold() in (r['code'].casefold(),r['name'].casefold())),None)
    if match:public['country']=match
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if snapshot(c,user)['revision']!=body.revision:raise HTTPException(409,'Personal details changed elsewhere. Reload saved details before saving; your edits are still here.')
        private_profile.update_settings(c,user,public)
        private_profile.store(c,user,SECTION,cipher)
        result=snapshot(c,user)
    return {**result,'countries':private_profile.countries(),'saved':True}
