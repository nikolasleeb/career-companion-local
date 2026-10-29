import hashlib,io,json
import pytest
from pypdf import PdfWriter
from app import combined_import,documents,profile_import,db,import_values
from app.models import ExperienceItem
from test_combined_import import source,prepare,approve,text

@pytest.mark.parametrize('a,b,display',[
 ('202-555-0147','2025550147','(202) 555-0147'),
 ('+1 (202) 555-0147','1.202.555.0147','(202) 555-0147'),
 ('2025550147 x 12','(202) 555-0147 ext. 12','(202) 555-0147 ext. 12'),
 ('+44 20 7946 0123','+442079460123','+442079460123')])
def test_phone_equivalence(a,b,display):
 assert import_values.normalized('phone',a)==display
 assert import_values.same('phone',a,b)
 assert not import_values.phone_ambiguous(a)
 assert not import_values.same('phone',a,b+'8')

def test_wrapped_urls_are_repaired_only_from_source_evidence():
 a='www.linkedin.com/in/fictional-\nexample (LinkedIn)'
 assert import_values.repair_wrapped_links(a)=='www.linkedin.com/in/fictional-example (LinkedIn)'
 assert import_values.same('linkedin','https://linkedin.com/in/fictional-example/','https://www.linkedin.com/in/fictional-example?trk=profile')
 assert not import_values.same('linkedin','https://linkedin.com/in/fictional-','https://linkedin.com/in/fictional-example')
 assert import_values.repair_wrapped_links('https://linkedin.com/in/fictional-\nExperience')=='https://linkedin.com/in/fictional-\nExperience'
 # Two words and a new section must never be appended to a URL.
 assert 'in/fictional-\nNew Company' in import_values.repair_wrapped_links('https://linkedin.com/in/fictional-\nNew Company')

def test_multiple_emails_normalized_contacts_and_provenance(client,account):
 a=source(account['id'],'Alex Example\nalex@example.test; other@example.test\n202-555-0147\nhttps://linkedin.com/in/fictional-example/\nPROJECTS\nPractice dashboard\nBuilt a chart.')
 b=source(account['id'],'Alex Example\nalex@example.test\n2025550147\nwww.linkedin.com/in/fictional-\nexample (LinkedIn)\nPROJECTS\nPractice dashboard\nBuilt a chart.','linkedin_pdf')
 p=prepare(client,a,b);parsed=p['data']['resume_parse']
 assert {o['value'] for o in parsed['profile_conflicts']['email']}=={'alex@example.test','other@example.test'}
 assert parsed['profile']['phone']=='(202) 555-0147' and 'phone' not in parsed['profile_conflicts']
 assert parsed['profile']['linkedin']=='https://www.linkedin.com/in/fictional-example' and 'linkedin' not in parsed['profile_conflicts']
 phone=parsed['profile_sources']['phone'][0];assert len(phone['sources'])==2
 assert approve(client,p,[],profile_updates={'email':'alex@example.test'}).status_code==422
 r=approve(client,p,[],profile_updates={'email':'alex@example.test','phone':parsed['profile']['phone']},profile_choices={'email':'0'})
 assert r.status_code==200,r.text

def test_saved_profile_changes_require_explicit_resolution(client,account):
 db.update_settings(account['id'],{'email':'saved@example.test'})
 p=prepare(client,source(account['id'],'Alex Example\nnew@example.test\nPROJECTS\nPractice chart\nBuilt a chart.'))
 parsed=p['data']['resume_parse'];assert parsed['profile_states']['email']=='needs_choice'
 assert parsed['profile_conflicts']['email'][-1]['source']['kind']=='saved'
 assert approve(client,p,[],profile_updates={'email':'new@example.test'}).status_code==422
 assert db.settings(account['id'])['email']=='saved@example.test'
 r=approve(client,p,[],profile_updates={'email':'new@example.test'},profile_choices={'email':'0'});assert r.status_code==200,r.text

def test_format_only_dates_preserve_precision():
 assert import_values.same('start_date','Jan 2025','January 2025')
 assert import_values.same('dates','Jan 2025 – Present','January 2025 - Current')
 assert not import_values.same('dates','Jan 2025 - Present','2025 - Present')
 assert not import_values.same('dates','Jun–Aug 2025','June 2025 - August 2025')

def linkedin_fixture():
 return '''[[LinkedIn main]]
Alex Example
Graduate Student at Fictional University
Tucson, Arizona, United States
Experience
Fictional Company
3 years 6 months
Data Analyst II
August 2025 - Present (1 year)
Tucson, Arizona, United States
Data Analyst I
May 2023 - August 2025 (2 years)
Richmond, Virginia, United States
• Built fictional dashboards.
Other Company
Research Intern
June 2022 - August 2022 (3 months)
Glen Allen, Virginia, United States
• Reviewed fictional results.
Education
Fictional University
Master's degree, Data Science · (August 2025 - December 2026)
Fictional College
Bachelor of Science - BS, Cybersecurity and Management and
Analytics · (August 2021 - December 2025)
[[LinkedIn sidebar]]
Contact
alex@example.test
2025550147 (Mobile)
www.linkedin.com/in/fictional-
example (LinkedIn)
Top Skills
Jupyter
Exploratory Data Analysis
Kali Linux
Certifications
Amazon Web Services Cloud
Practitioner
AWS Certified AI Practitioner'''

def test_structured_linkedin_sections_grouped_jobs_education_skills_credentials():
 p=profile_import.parse(linkedin_fixture(),'linkedin_pdf')
 jobs=[e['data'] for e in p['entries'] if e['data']['category']=='employment']
 assert len(jobs)==3 and [j['organization'] for j in jobs]==['Fictional Company','Fictional Company','Other Company']
 assert jobs[0]['location']=='Tucson, Arizona, United States'
 assert not jobs[0]['description'] and jobs[1]['description']=='• Built fictional dashboards.'
 schools=[e['data'] for e in p['entries'] if e['data']['category']=='education'];assert len(schools)==2
 assert schools[0]['major']=='Data Science' and schools[0]['end_date']=='December 2026'
 skills=[e['data'] for e in p['entries'] if e['data']['skill_items']];assert [v['name'] for v in skills[0]['skill_items']]==['Jupyter','Exploratory Data Analysis','Kali Linux']
 names=[c['name'] for e in p['entries'] for c in e['data']['certification_items']]
 assert names==['Amazon Web Services Cloud Practitioner','AWS Certified AI Practitioner']
 assert p['profile']['name']=='Alex Example' and 'fictional-example' in p['profile']['linkedin']
 assert not any('Graduate Student' in n or 'Alex Example' in n for n in names)

def test_possible_saved_match_requires_new_or_update_choice(client,account):
 old=db.save(account['id'],'experience',ExperienceItem(category='employment',title='Data Analyst',organization='Fictional Labs',description='Older evidence',confirmed=True).model_dump())
 p=prepare(client,source(account['id'],text()));e=p['data']['resume_parse']['entries'][0]
 assert old['id'] in e['existing_matches']
 assert approve(client,p).status_code==422
 r=approve(client,p,record_choices={e['id']:'new'});assert r.status_code==200,r.text

def test_uncertain_records_require_review_but_unselected_issues_do_not_block(client,account):
 p=prepare(client,source(account['id'],'Alex Example\nExperience\nExample Centers | 2023 - Present\nBuilt a chart.\nPROJECTS\nPractice dashboard\nBuilt a local chart.'))
 uncertain=next(e for e in p['data']['resume_parse']['entries'] if e['review_state']=='needs_review')
 assert approve(client,p).status_code==422
 clean=[{'id':e['id'],'data':e['data']} for e in p['data']['resume_parse']['entries'] if e['id']!=uncertain['id']]
 assert approve(client,p,clean).status_code==200

def test_pdf_layout_geometry_and_saved_sources(monkeypatch,tmp_path):
 # Generate a fictional two-column PDF with explicit text matrices, including a
 # header below sidebar credentials to reproduce the real extraction-order bug.
 from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject,ArrayObject,FloatObject,TextStringObject
 writer=PdfWriter();page=writer.add_blank_page(612,792)
 font=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}))
 page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
 rows=[(22,740,'Contact'),(22,720,'alex@example.test'),(22,700,'Top Skills'),(22,680,'SQL'),(22,650,'Certifications'),(22,630,'Example Cloud'),(22,616,'Practitioner'),(224,740,'Alex Example'),(224,720,'Graduate Student'),(224,700,'Experience'),(224,680,'Fictional Company'),(224,662,'Data Analyst'),(224,644,'Jan 2024 - Present')]
 stream=DecodedStreamObject();stream.set_data(('\n'.join(f'BT /F1 11 Tf 1 0 0 1 {x} {y} Tm ({t}) Tj ET' for x,y,t in rows)).encode());page[NameObject('/Contents')]=writer._add_object(stream)
 action=writer._add_object(DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject('https://www.linkedin.com/in/fictional-complete')}))
 annotation=writer._add_object(DictionaryObject({NameObject('/Subtype'):NameObject('/Link'),NameObject('/A'):action,NameObject('/Rect'):ArrayObject([FloatObject(v) for v in [22,718,190,732]])}))
 page[NameObject('/Annots')]=writer._add_object(ArrayObject([annotation]))
 output=io.BytesIO();writer.write(output);raw=output.getvalue();derived=documents.linkedin_text(raw)
 assert '[[LinkedIn main]]' in derived
 parsed=profile_import.parse(derived,'linkedin_pdf');assert parsed['profile']['name']=='Alex Example'
 assert parsed['profile']['linkedin']=='https://www.linkedin.com/in/fictional-complete'
 assert parsed['entries'][0]['data']['organization']=='Fictional Company'
 from app import config
 monkeypatch.setattr(config,'DATA_DIR',tmp_path);folder=tmp_path/'uploads'/'fictional';folder.mkdir(parents=True);(folder/'doc').write_bytes(raw)
 d={'id':'doc','user_id':'fictional','data':{'format':'pdf','import_source_kind':'linkedin_pdf','text':'original extraction','reviewed':False}}
 assert profile_import.document_text(d)==derived and d['data']['text']=='original extraction'
 d['data']['source_text_corrected']=True;assert profile_import.document_text(d)=='original extraction'
 d['data'].pop('source_text_corrected');d['data']['reviewed']=True;assert profile_import.document_text(d)=='original extraction'


def test_legacy_grouped_credentials_are_skipped_without_rewriting_group(client,account):
 old=db.save(account['id'],'experience',ExperienceItem(category='skills',title='Certifications',certification_items=[{'name':'AWS Certified AI Practitioner','issuer':'Amazon'},{'name':'Example Cloud Fundamentals'}],confirmed=True).model_dump())
 p=prepare(client,source(account['id'],'Alex Example\nCERTIFICATIONS\nAWS Certified AI Practitioner; Example Cloud Fundamentals'))
 assert len(p['data']['resume_parse']['entries'])==2
 assert all(e['already_saved'] for e in p['data']['resume_parse']['entries'])
 r=approve(client,p);assert r.status_code==200 and r.json()['created']==0 and r.json()['skipped']==2
 assert db.get(account['id'],old['id'])==old


@pytest.mark.parametrize('raw,expected',[
 ('ALEX EXAMPLE-SMITH','Alex Example-Smith'),
 ('  alex   example-smith  ','Alex Example-Smith'),
 ("MARY O'NEILL","Mary O'Neill"),
 ('ÉLODIE D’ARCY','Élodie D’Arcy'),
 ('ALEX J. EXAMPLE III','Alex J. Example III'),
 ('ALEX J.R. EXAMPLE JR.','Alex J.R. Example Jr.'),
 ('ALEX MCDONALD','Alex McDonald'),
 ('AJ EXAMPLE','AJ Example'),
 ('Alex de la Cruz','Alex de la Cruz'),
 ('Alex van der Waals','Alex van der Waals'),
 ('Alex McDONALD','Alex McDONALD'),
 ('e. e. cummings','E. E. Cummings'),
 ('王小明','王小明'),
])
def test_imported_personal_name_capitalization(raw,expected):
 assert import_values.personal_name(raw)==expected
 assert import_values.personal_name(expected)==expected
 assert import_values.normalized('organization','NASA')=='NASA'


def test_combined_names_prefer_existing_casing_keep_original_sources(client,account):
 a=source(account['id'],text(name='ALEX DE LA CRUZ'));b=source(account['id'],text(name='Alex de la Cruz'),'linkedin_pdf')
 p=prepare(client,a,b);parsed=p['data']['resume_parse'];assert parsed['profile']['name']=='Alex de la Cruz'
 assert 'name' not in parsed['profile_conflicts']
 originals=[r['original_value'] for o in parsed['profile_sources']['name'] for r in o['sources']]
 assert originals==['ALEX DE LA CRUZ','Alex de la Cruz']
 assert 'ALEX DE LA CRUZ' in parsed['profile_evidence']['name']
 assert db.settings(account['id']).get('name','')==''
 r=approve(client,p,[],profile_updates={'name':parsed['profile']['name']});assert r.status_code==200,r.text
 assert db.settings(account['id'])['name']=='Alex de la Cruz'


def test_name_formatting_does_not_merge_different_names_or_rewrite_saved_profile(client,account):
 db.update_settings(account['id'],{'name':'ALEX EXAMPLE'})
 a=source(account['id'],text(name='Alex Example'));p=prepare(client,a)
 assert p['data']['resume_parse']['profile']['name']=='Alex Example'
 assert p['data']['resume_parse']['profile_states']['name']=='unchanged'
 assert db.settings(account['id'])['name']=='ALEX EXAMPLE'
 b=source(account['id'],text(name='Jordan Example'),'linkedin_pdf');p=prepare(client,a,b)
 assert 'name' in p['data']['resume_parse']['profile_conflicts']
