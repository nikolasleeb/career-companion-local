from conftest import onboard_test_account
"""Fictional private-profile contracts: encryption, review boundaries and compatibility."""
import base64,json,time
import pytest
from app import config,db,private_answers,private_profile,application_agent as agent,assistant_ai
from test_application_agent import run,scan,field,answer

MARKER='FictionalSecretProfileDescription-83722'

def save(client,section,values):
    return client.put('/api/private-application-profile/'+section,json={'values':values,'reviewed':True})

def citizenship(**kw):
    return {'countries':['US','GB'],'us_citizen':'yes','authorized_us':'yes','sponsorship_now':'no','sponsorship_future':'no','reviewed':True,**kw}

def test_profile_defaults_catalog_auth_and_csrf(client,account):
    r=client.get('/api/private-application-profile');assert r.status_code==200
    assert all(v is None for v in r.json()['sections'].values())
    assert r.headers['cache-control']=='no-store'
    codes={c['code'] for c in r.json()['countries']};assert {'US','GB','CA'}<=codes and not {'EU','XA','XB','ZZ'}&codes
    assert save(client,'disability',{'disability':'Prefer not to answer'}).status_code==200
    del client.headers['X-CSRF-Token']
    assert save(client,'disability',{'disability':'No'}).status_code==403
    client.cookies.clear();assert client.get('/api/private-application-profile').status_code==401

def test_citizenships_atomic_independent_and_clear(client,account,monkeypatch):
    data=citizenship(countries=['GB'],us_citizen='yes')
    r=client.put('/api/private-application-profile/citizenship',json=data);assert r.status_code==200 and r.json()['warnings']
    assert db.settings(account['id'])['us_citizen']=='yes'
    assert 'countries' not in db.settings(account['id'])
    assert private_profile.load(account['id'],'citizenship')=={'countries':['GB']}
    assert client.get('/api/private-application-profile').json()['warnings']
    original=private_profile.store
    def fail(*a):raise RuntimeError('Fictional transaction failure')
    monkeypatch.setattr(private_profile,'store',fail)
    with pytest.raises(RuntimeError):client.put('/api/private-application-profile/citizenship',json=citizenship(us_citizen='no'))
    assert db.settings(account['id'])['us_citizen']=='yes'
    assert private_profile.load(account['id'],'citizenship')=={'countries':['GB']}
    monkeypatch.setattr(private_profile,'store',original)
    assert client.put('/api/private-application-profile/citizenship',json=citizenship(countries=[])).status_code==200
    assert client.get('/api/private-application-profile').json()['warnings']==[]
    assert client.delete('/api/private-application-profile/citizenship').status_code==200
    assert db.settings(account['id'])['us_citizen']=='yes'

@pytest.mark.parametrize('codes',[['US','US'],['not-a-country'],['EU']])
def test_country_validation(client,account,codes):
    assert client.put('/api/private-application-profile/citizenship',json=citizenship(countries=codes)).status_code==422

@pytest.mark.parametrize('section,values',[
 ('veteran',{'veteran':'Unsure','protected_veteran':'Prefer not to answer'}),
 ('sex_gender',{'sex':'Self-describe','sex_description':MARKER,'gender':'Non-binary'}),
 ('race_ethnicity',{'race_ethnicity':['Asian','White','Self-describe'],'description':MARKER}),
 ('disability',{'disability':'Prefer not to answer'}),
])
def test_review_save_clear_and_restart(client,account,section,values):
    assert client.put('/api/private-application-profile/'+section,json={'values':values,'reviewed':False}).status_code==422
    assert save(client,section,values).status_code==200
    assert private_profile.load(account['id'],section)
    db.init();assert private_profile.load(account['id'],section)
    assert client.delete('/api/private-application-profile/'+section).status_code==200
    assert private_profile.load(account['id'],section) is None

@pytest.mark.parametrize('section,values',[
 ('sex_gender',{'sex':'Self-describe','sex_description':''}),
 ('sex_gender',{'sex':'Female','sex_description':MARKER}),
 ('sex_gender',{'sex':'Female','gender':'Female'}),
 ('race_ethnicity',{'race_ethnicity':['White','Prefer not to answer']}),
 ('race_ethnicity',{'race_ethnicity':['White','White']}),
 ('race_ethnicity',{'race_ethnicity':['Self-describe']}),
 ('disability',{'disability':'inferred'}),
 ('veteran',{'family_connection':MARKER}),
])
def test_guided_values_reject_ambiguity_without_echoing(client,account,section,values):
    r=save(client,section,values);assert r.status_code==422 and MARKER not in r.text


def test_encryption_isolation_tamper_key_recovery_no_leaks(client,account):
    assert save(client,'sex_gender',{'sex':'Self-describe','sex_description':MARKER}).status_code==200
    with db.connect() as c:
        cipher=c.execute('SELECT ciphertext FROM cc_private_profile').fetchone()[0]
        assert MARKER not in cipher
        assert MARKER not in repr(c.execute('SELECT * FROM entities').fetchall())
        assert not c.execute('SELECT 1 FROM evidence_fts WHERE text LIKE ?',('%'+MARKER+'%',)).fetchone()
    for path in ['/api/workspace','/api/account/export','/api/application-agent/status']:
        assert MARKER not in client.get(path).text
    with pytest.raises(Exception):private_answers.unseal('other','private-profile:sex_gender',cipher)
    with pytest.raises(Exception):private_answers.unseal(account['id'],'private-profile:disability',cipher)
    raw=bytearray(base64.b64decode(cipher));raw[-1]^=1
    with db.connect() as c:c.execute('UPDATE cc_private_profile SET ciphertext=?',(base64.b64encode(raw).decode(),))
    assert client.get('/api/private-application-profile').status_code==503
    with db.connect() as c:c.execute('UPDATE cc_private_profile SET ciphertext=?',(cipher,))
    key=config.VAULT_KEY_FILE.read_bytes();config.VAULT_KEY_FILE.unlink()
    assert client.get('/api/private-application-profile').status_code==503 and not config.VAULT_KEY_FILE.exists()
    config.VAULT_KEY_FILE.write_bytes(key);config.VAULT_KEY_FILE.chmod(0o600)
    assert client.get('/api/private-application-profile').status_code==200
    other=client.post('/api/auth/register',json={'username':'other','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    assert all(v is None for v in client.get('/api/private-application-profile').json()['sections'].values())
    assert client.delete('/api/private-application-profile/sex_gender').status_code==200
    assert private_profile.load(account['id'],'sex_gender')['sex_description']==MARKER


def test_suggestions_never_write_or_enter_run_payload_until_approved(client,account):
    assert save(client,'sex_gender',{'sex':'Self-describe','sex_description':MARKER,'gender':'Woman'}).status_code==200
    r,c,app=run(client,account['id']);label='What is your sex?'
    result=scan(client,r,c,[field(label=label,control='select',options=['Female','Male','Prefer not to answer'])]).json()
    assert result['writes']==[] and result['run']['unresolved'][0]['private_category']=='sex'
    r=result['run'];path='/api/application-agent/runs/'+r['id']
    suggestions=client.get(path+'/questions/f0/suggestions');assert suggestions.status_code==200 and suggestions.headers['cache-control']=='no-store'
    assert suggestions.json()['suggestions'][0]['value']=='Self-describe: '+MARKER
    assert 'Woman' not in suggestions.text
    assert MARKER not in client.get(path).text
    with db.connect() as con:assert MARKER not in con.execute('SELECT payload FROM cc_runs').fetchone()[0]
    body={'question_id':'f0','value':'Prefer not to answer','answer_kind':'private','decision':'once','expected_version':r['version']}
    assert client.post(path+'/answers',json={**body,'decision':'save'}).status_code==422
    assert client.post(path+'/answers',json=body).status_code==200
    r=client.get(path).json();result=scan(client,r,c,[field(label=label,control='select',options=['Female','Male','Prefer not to answer'])]).json()
    assert result['writes']==[{'id':'f0','value':'Prefer not to answer'}]
    with db.connect() as con:
        assert MARKER not in con.execute('SELECT payload FROM cc_runs').fetchone()[0]
        assert con.execute('SELECT count(*) FROM cc_run_answers').fetchone()[0]==1
    assert client.get(path+'/questions/missing/suggestions').status_code==404


def test_veteran_protected_gender_and_residence_are_not_inferred(client,account):
    save(client,'veteran',{'veteran':'Veteran'})
    save(client,'sex_gender',{'sex':'Male'})
    client.put('/api/private-application-profile/citizenship',json=citizenship())
    for label,expected in [('Are you a protected veteran?',[]),('Gender',[]),('Country of residence',[])]:
        q={'label':label,'options':[],'description':'','context':''}
        assert private_profile.suggestions(account['id'],q,{'id':'a','data':{}})['suggestions']==expected
    q={'label':'Countries of citizenship','options':[]}
    got=private_profile.suggestions(account['id'],q,{'id':'a','data':{}})['suggestions'];assert 'United States' in got[0]['value'] and 'United Kingdom' in got[0]['value']


def test_legacy_common_answers_review_even_when_reuse_enabled(client,account):
    a=answer();assert client.post('/api/private-application-answers',json=a).status_code==200
    client.put('/api/private-application-answers/reuse',json={'enabled':True})
    r,c,app=run(client,account['id']);result=scan(client,r,c,[field(label=a['question'],control='select',options=a['options'])]).json()
    assert result['writes']==[]
    q=result['run']['unresolved'][0]
    suggestions=private_profile.suggestions(account['id'],q,app)['suggestions']
    assert suggestions==[{'label':'Previously reviewed answer for this exact question','value':a['value'],'source':'saved_question'}]
    q={**q,'description':'Different definitions'};assert private_profile.suggestions(account['id'],q,app)['suggestions']==[]


def test_family_connections_manual_only_and_legacy_deletable(client,account):
    label='Do you have relatives employed by this company?'
    for category in ['family_connection','additional']:
        assert client.post('/api/private-application-answers',json=answer(question=label,category=category,scope='employer',employer='Fixture Employer')).status_code==422
    # Simulate a pre-upgrade record without passing through the now-prohibited write API.
    id=db.uid();cipher=private_answers.seal(account['id'],id,answer(question=label,category='family_connection',scope='employer',employer='Fixture Employer'))
    with db.connect() as con:con.execute('INSERT INTO cc_vault VALUES(?,?,?,?,?)',(id,account['id'],cipher,db.now(),db.now()))
    client.put('/api/private-application-answers/reuse',json={'enabled':True})
    r,c,app=run(client,account['id']);result=scan(client,r,c,[field(label=label)]).json();r=result['run']
    assert result['writes']==[] and r['unresolved'][0]['reason']=='family_connection_manual'
    assert private_profile.suggestions(account['id'],r['unresolved'][0],app)['manual_only']
    path='/api/application-agent/runs/'+r['id']
    assert client.post(path+'/answers',json={'question_id':'f0','value':'No','decision':'once','answer_kind':'private','expected_version':r['version']}).status_code==422
    with db.connect() as con:assert con.execute('SELECT count(*) FROM cc_run_answers').fetchone()[0]==0
    assert any(x['id']==id for x in client.get('/api/private-application-answers').json()['answers'])
    assert client.delete('/api/private-application-answers/'+id).status_code==200


def test_private_questions_cannot_be_sent_to_ai_and_suggestion_authorization(client,account):
    r,c,app=run(client,account['id']);r=scan(client,r,c,[field(label='What is your nationality?')]).json()['run']
    from app.assistant_ai import Assistance
    with pytest.raises(Exception):assistant_ai.build_payload(account['id'],r,Assistance(request_token='a'*32,question_id='f0',action='interpret',approved_cost_usd=.01,consent=True))
    path='/api/application-agent/runs/'+r['id']+'/questions/f0/suggestions'
    assert client.get(path).status_code==200
    with db.connect() as con:
        saved=agent.load(account['id'],r['id']);saved['expires']=time.time()-1;con.execute('UPDATE cc_runs SET payload=? WHERE id=?',(json.dumps(saved),r['id']))
    assert client.get(path).status_code==403


def test_legacy_common_category_blocks_ordinary_autocomplete_before_review(client,account):
    a=answer(category='gender',question='Identify yourself',options=[],value='Fictional legacy disclosure')
    assert client.post('/api/private-application-answers',json=a).status_code==200
    client.put('/api/private-application-answers/reuse',json={'enabled':True})
    db.update_settings(account['id'],{'name':'Fictional ordinary name'})
    r,c,app=run(client,account['id'])
    result=scan(client,r,c,[field(label=a['question'],autocomplete='name')]).json()
    assert result['writes']==[] and result['run']['unresolved'][0]['private_category']=='gender'


def test_suggestions_cannot_cross_account_or_login_sessions(client,account):
    r,c,app=run(client,account['id']);r=scan(client,r,c,[field(label='Gender')]).json()['run']
    path='/api/application-agent/runs/'+r['id']+'/questions/f0/suggestions'
    assert client.get(path).status_code==200
    user=client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=user['csrf']
    assert client.get(path).status_code==403
    user=client.post('/api/auth/register',json={'username':'otherprofile','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=user['csrf'];onboard_test_account(user)
    assert client.get(path).status_code==404
