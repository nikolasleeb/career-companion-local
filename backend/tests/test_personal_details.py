"""Fictional identity/address save and deterministic filling contracts."""
import json
import pytest
from conftest import onboard_test_account
from app import db,private_profile,personal_details,application_agent as agent
from app.resume_data import contact_lines
from test_application_agent import run,scan,field

def details(client,**changes):
    current=client.get('/api/private-application-profile/personal-details').json()
    app={'legal_first_name':'Élodie','middle_name':'Anne','last_name':"de la Cruz-O’Neil",'preferred_first_name':'Ellie','preferred_same_as_legal':False,'address_line1':'007 Fictional Street','address_line2':'Unit 9','postal_code':'00123 AB',**changes}
    return {'revision':current['revision'],'profile':{'name':'Resume Display Name','city':'Example City','state':'VA','country':'United States'},'application':app}

def test_private_save_atomic_and_stale(client,account,monkeypatch):
    body=details(client);saved=client.put('/api/private-application-profile/personal-details',json=body)
    assert saved.status_code==200,saved.text
    assert saved.json()['application']==body['application']
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==409
    assert client.get('/api/private-application-profile/personal-details').headers['cache-control']=='no-store'
    before=private_profile.load(account['id'],'personal_details');new=details(client,postal_code='Changed');new['profile']['name']='Never saved'
    monkeypatch.setattr(private_profile,'store',lambda *a:(_ for _ in ()).throw(RuntimeError('simulated failure')))
    with pytest.raises(RuntimeError):client.put('/api/private-application-profile/personal-details',json=new)
    assert db.settings(account['id'])['name']=='Resume Display Name'
    assert private_profile.load(account['id'],'personal_details')==before

def test_no_private_leaks_backup_cleanup_and_isolation(client,account):
    body=details(client);assert client.put('/api/private-application-profile/personal-details',json=body).status_code==200
    for value in [db.settings(account['id']),client.get('/api/workspace').json(),client.get('/api/account/export').json(),contact_lines(db.settings(account['id']))]:
        assert '007 Fictional Street' not in json.dumps(value) and '00123 AB' not in json.dumps(value)
    with db.connect() as c:
        row=c.execute("SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section='personal_details'",(account['id'],)).fetchone()
        assert 'Élodie' not in row[0] and '00123 AB' not in row[0]
    assert private_profile.load('another-account','personal_details') is None
    snapshot=db.save(account['id'],'resume',{'title':'Historic','snapshot':{'name':'Historical Name'}})
    preview=client.post('/api/account/cleanup/preview',json={'categories':['personal']}).json()
    assert preview['private_sections']==1
    assert client.post('/api/account/cleanup/apply',json={'preview_id':preview['preview_id'],'confirmed':True}).status_code==200
    assert private_profile.load(account['id'],'personal_details') is None
    assert db.get(account['id'],snapshot['id'])['data']['snapshot']['name']=='Historical Name'

def test_confirmed_fields_fill_and_sensitive_context_stays_manual(client,account):
    assert client.put('/api/private-application-profile/personal-details',json=details(client)).status_code==200
    r,connection,app=run(client,account['id'])
    fs=[field('first','First name (legal)'),field('middle','Middle name'),field('last','Family name'),field('preferred','First name (preferred)'),field('street','Address line 1'),field('zip','Zip/Postal code'),field('country','Country',control='select',options=['Canada','United States of America']),field('state','State',control='select',options=['Virginia','Arizona']),field('sponsor','Will you require visa sponsorship?',control='select',options=['Yes','No']),field('auth','Legally authorized to work in US?',control='select',options=['Yes','No']),field('family','Family member name',autocomplete='given-name'),field('password','Password',autocomplete='given-name'),field('given','Unlabelled field',autocomplete='given-name')]
    result=scan(client,r,connection,fs,metadata={"version":4,"manual_fields":["password"]});assert result.status_code==200,result.text
    writes={v['id']:v['value'] for v in result.json()['writes']}
    assert writes=={'first':'Élodie','middle':'Anne','last':"de la Cruz-O’Neil",'preferred':'Ellie','street':'007 Fictional Street','zip':'00123 AB','country':'United States of America','state':'Virginia','given':'Élodie'}

def test_legacy_no_silent_split_preferred_sync_blanks_and_autocomplete(client,account):
    db.update_settings(account['id'],{'name':'Old Name'})
    assert agent.local_value(account['id'],agent.FieldInfo(**field(label='First name')),{'id':'x','data':{}}) is None
    body=details(client,preferred_same_as_legal=True,middle_name='',address_line2='')
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==200
    app={'id':'x','data':{}}
    assert agent.local_value(account['id'],agent.FieldInfo(**field(label='Preferred first name')),app)=='Élodie'
    body=details(client,legal_first_name='New',preferred_same_as_legal=True)
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==200
    assert agent.local_value(account['id'],agent.FieldInfo(**field(label='Preferred first name')),app)=='New'
    from app.application_values import option_value
    assert option_value('GB',['United Kingdom','France'],'country')=='United Kingdom'
    assert option_value('00123 AB',[],'postal_code')=='00123 AB'

@pytest.mark.parametrize('extra',[{'model':'gpt-6.1-sol'},{'authorized_us':'yes'},{'name':'x'*151}])
def test_contact_api_rejects_unrelated_settings(client,account,extra):
    body=details(client);body['profile'].update(extra)
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==422

def test_auth_and_csrf(client,account):
    body=details(client);del client.headers['X-CSRF-Token']
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==403
    client.cookies.clear();assert client.get('/api/private-application-profile/personal-details').status_code==401

def test_blank_optional_existing_values_and_ambiguous_choices(client,account):
    assert client.put('/api/private-application-profile/personal-details',json=details(client,middle_name='',address_line2='')).status_code==200
    r,connection,app=run(client,account['id'])
    result=scan(client,r,connection,[field('middle','Middle name'),field('line2','Address line 2'),field('requiredmiddle','Middle name',required=True),field('occupied','First name (legal)',has_value=True),field('country','Country',control='select',options=['United States','USA'])],metadata={'version':4})
    assert result.status_code==200,result.text
    assert result.json()['writes']==[]
    assert {q['id'] for q in result.json()['run']['unresolved']}=={'requiredmiddle','country'}

def test_country_code_normalization_and_encryption_failure(client,account,monkeypatch):
    body=details(client);body['profile']['country']='GB'
    response=client.put('/api/private-application-profile/personal-details',json=body)
    assert response.status_code==200 and response.json()['profile']['country']=='United Kingdom'
    before=response.json();body=details(client);body['profile']['name']='Not committed'
    def failed(*a):
        from fastapi import HTTPException
        raise HTTPException(503,'Encryption unavailable')
    monkeypatch.setattr(private_profile,'seal',failed)
    assert client.put('/api/private-application-profile/personal-details',json=body).status_code==503
    assert db.settings(account['id'])['name']=='Resume Display Name'
    assert private_profile.load(account['id'],'personal_details')==before['application']

def test_other_signed_in_account_has_own_empty_details(client,account):
    assert client.put('/api/private-application-profile/personal-details',json=details(client)).status_code==200
    old=account['id']
    assert client.post('/api/auth/logout').status_code==200
    response=client.post('/api/auth/register',json={'username':'other-student','password':'fictional-other-password'})
    assert response.status_code==200,response.text
    current=response.json();onboard_test_account(current);client.headers['X-CSRF-Token']=current['csrf']
    assert client.get('/api/private-application-profile/personal-details').json()['application'] is None
    assert client.put('/api/private-application-profile/personal-details',json=details(client,postal_code='ZZ9 9ZZ')).status_code==200
    assert private_profile.load(old,'personal_details')['postal_code']=='00123 AB'
    assert private_profile.load(current['id'],'personal_details')['postal_code']=='ZZ9 9ZZ'
