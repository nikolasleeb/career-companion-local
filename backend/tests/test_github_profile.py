import json
from app import db,resume_data,resume_parser,application_agent

def test_github_settings_export_restore_and_separate_application_mapping(client,account):
 values={'website':'https://example.com/portfolio','github':'https://github.com/fictional-user','linkedin':'https://linkedin.com/in/fictional-user'}
 assert client.put('/api/settings',json=values).status_code==200
 assert all(client.get('/api/me').json()['settings'][k]==v for k,v in values.items())
 backup=client.get('/api/account/export').json();assert backup['profile']['github']==values['github']
 lines=resume_data.contact_lines(values);assert all(v in lines[0] for v in values.values())
 Field=application_agent.FieldInfo
 assert application_agent.local_value(account['id'],Field(id='g',label='GitHub',control='text',autocomplete='url'),{})==values['github']
 assert application_agent.local_value(account['id'],Field(id='w',label='Personal website',control='text',autocomplete='url'),{})==values['website']
 assert application_agent.local_value(account['id'],Field(id='g',label='GitHub or portfolio',control='text',autocomplete='url'),{}) is None
 assert client.put('/api/settings',json={'github':'javascript:alert(1)'}).status_code==422
 assert len(resume_data.contact_lines({'website':values['github'],'github':values['github']})[0].split(' | '))==1
 other=client.post('/api/auth/register',json={'username':'github-restoration','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert not db.settings(other['id']).get('github')
 restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert restored.status_code==200,restored.text
 assert all(db.settings(other['id'])[k]==v for k,v in values.items())

def test_resume_parser_keeps_three_professional_links_separate():
 parsed=resume_parser.parse('Alex Example\nhttps://github.com/fictional-user | https://example.com/portfolio | https://linkedin.com/in/fictional-user\n\nEDUCATION\nFictional University\nBS, Computer Science')
 assert parsed['profile']['github']=='https://github.com/fictional-user'
 assert parsed['profile']['website']=='https://example.com/portfolio'
 assert parsed['profile']['linkedin']=='https://linkedin.com/in/fictional-user'
