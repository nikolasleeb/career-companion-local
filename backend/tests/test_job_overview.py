from conftest import onboard_test_account
import copy
from fastapi.testclient import TestClient
from app import db, job_parser
from app.main import app

POSTING='''Example Analytics
Analyst Internship - Richmond, VA
At a glance
$23–35/hr
Hybrid or onsite, based in Richmond, VA
Full-time
US work authorization requirements unknown
Job description
An internship in business analytics.
The Program
A 10-week program during the summer of 2027.
The Role
Analyze data to answer business questions.
Collaborate with stakeholders and present findings.
Core Competencies
Curiosity and critical thinking.
Requirements
Currently enrolled in a Bachelor’s or Master’s degree program, in an analytical/quantitative major preferred
Proficiency with SQL and/or Python preferred
Excellent written and verbal communication skills
Relevant project work or internship experience
Work Authorization
Applicants must be authorized to work in the United States. Sponsorship will not be considered.
Work Location:
This role is based in Richmond, VA. Associates work onsite 4 days per week.
About Example Analytics
The company has a headquarters in Seattle, WA and 200 full-time analysts.
'''

def test_groups_mixed_requirements_and_preserves_sources():
    x=job_parser.organize({'title':'Example Analytics Internship','description':POSTING})
    assert x['company']=='Example Analytics'
    assert x['facts']['location']['value']=='Richmond, VA'
    assert x['facts']['work_arrangement']['value']=='Hybrid / On-site'
    assert x['facts']['pay']['value']=='$23–35/hr'
    assert 'Full-time' in x['facts']['schedule']['value'] and '4 days per week' in x['facts']['schedule']['value']
    assert x['facts']['dates']['value']=='Summer 2027 · 10 weeks'
    assert len(x['sections']['required'])==2 and len(x['sections']['preferred'])==2
    assert len(x['sections']['eligibility'])==2
    assert len(x['sections']['responsibilities'])==2
    assert any('Sponsorship will not' in i['text'] for i in x['sections']['eligibility'])
    assert x['original_text']==POSTING and x['notes']
    for group in x['sections'].values():
        for item in group: assert item['source'] in POSTING
    for fact in x['facts'].values():
        for quote in fact['sources']: assert quote in POSTING


def test_wrapped_pdf_headers_and_footer_are_not_qualifications():
    text='''10/8/26, 4:30 PMExample job
Page 1 of 3https://example.com/job
Washington, DC
Basic Qualifications
• Bachelor’s degree in data science or a related
field and coursework in statistics.
• Experience using SQL to summarize datasets.
Preferred Qualifications
• Knowledge of Python.
10/8/26, 4:30 PMExample job
Page 2 of 3https://example.com/job
• Familiarity with Git.
As required by local law, the base pay range is:
$61,700 - $109,400 USD
What We Believe
Our company believes in teamwork.
Apply for this job
First Name*
Last Name*
Education
Required: upload a resume
'''
    x=job_parser.organize({'title':'Analyst','description':text})
    assert x['facts']['location']['value']=='Washington, DC'
    assert len(x['sections']['required'])==2 and len(x['sections']['preferred'])==2
    assert 'related field' in x['sections']['required'][0]['text']
    assert 'Page' not in str(x['sections']) and 'First Name' not in str(x['sections'])
    assert x['facts']['pay']['value']=='$61,700 - $109,400'


def test_work_model_is_not_location_and_state_metadata_is_kept():
    x=job_parser.organize({'title':'Intern','description':'''Work Model: On-Site
Company: Example
State/Province: Virginia
Qualifications
Rising junior pursuing a degree.
Your Future Starts Here
We have offices all over the world.
'''})
    assert x['facts']['location']['value']=='Virginia'
    assert x['facts']['work_arrangement']['value']=='On-site'
    assert len(x['sections']['required'])==0 and len(x['sections']['eligibility'])==1


def test_unknowns_not_guessed_from_hq_or_authorization():
    x=job_parser.organize({'title':'Analyst','description':'''Requirements
Knowledge of remote desktop troubleshooting.
Work Authorization
Authorized to work on a full-time basis.
About Example Company
Headquarters in Seattle, WA. Staff enjoy onsite fitness facilities.
'''})
    for key in ('location','pay','schedule','dates','deadline','work_arrangement'):assert x['facts'][key]['value']=='Not stated'
    assert x['sections']['required'][0]['text']=='Knowledge of remote desktop troubleshooting.'


def test_remote_negation_pay_period_and_dates():
    x=job_parser.organize({'title':'Analyst','description':'''Location: Tucson, AZ
Work arrangement: On-site, not a remote role.
Salary
The base salary is $60,000 to $75,000 per year.
Schedule
Full-time, 40 hours per week, Monday through Friday.
Program dates: Start date: June 1, 2027; End date: August 15, 2027
Application deadline: April 10, 2027
'''})
    assert x['facts']['work_arrangement']['value']=='On-site'
    assert x['facts']['pay']['value']=='$60,000 to $75,000 per year'
    assert '40 hours per week' in x['facts']['schedule']['value']
    assert 'April 10, 2027' in x['facts']['deadline']['value']
    assert 'June 1, 2027' in x['facts']['dates']['value']


def test_overview_is_local_and_works_for_existing_jobs(client,account,monkeypatch):
    from app import ai
    async def forbidden(*args,**kwargs):raise AssertionError('No model request allowed')
    monkeypatch.setattr(ai,'call_api',forbidden)
    job=client.post('/api/jobs',json={'title':'Example Analytics Internship','description':POSTING}).json()
    before=copy.deepcopy(db.get(account['id'],job['id'],'job'))
    response=client.get('/api/jobs/'+job['id']+'/overview')
    assert response.status_code==200,response.text
    assert response.json()['facts']['pay']['value']=='$23–35/hr'
    assert db.get(account['id'],job['id'],'job')==before
    assert client.post('/api/jobs/parse',json={'title':'Example','description':POSTING}).status_code==200
    uploaded=client.post('/api/jobs/import-document',files={'file':('job.txt',POSTING.encode(),'text/plain')})
    assert uploaded.status_code==200 and uploaded.json()['overview']['facts']['location']['value']=='Richmond, VA'


def test_edit_preserves_application_snapshot_and_isolation(client,account):
    job=client.post('/api/jobs',json={'title':'Example','description':POSTING}).json()
    application=client.post('/api/applications',json={'title':'Example','job_id':job['id']}).json()
    response=client.put('/api/jobs/'+job['id'],json={'title':'Updated title','description':POSTING.replace('$23–35/hr','$25–40/hr')})
    assert response.status_code==200
    assert client.get('/api/jobs/'+job['id']+'/overview').json()['facts']['pay']['value']=='$25–40/hr'
    assert db.get(account['id'],application['id'],'application')['data']['posting_snapshot']['description']==POSTING
    other=TestClient(app,base_url='http://localhost');me=other.post('/api/auth/register',json={'username':'another','password':'another-fictional-password'}).json();other.headers['X-CSRF-Token']=me['csrf']
    onboard_test_account(me)
    assert other.get('/api/jobs/'+job['id']+'/overview').status_code==404
    assert other.put('/api/jobs/'+job['id'],json={'description':POSTING}).status_code==404
    assert client.get('/api/workspace').json()['analysis']==[]


def test_repeated_pdf_headings_are_displayed_once_with_exact_sources():
    text='''Job DescriptionJob DescriptionJob DescriptionJob Description
Duration: Duration: Duration: Duration: Permanent
Location: Location: Location: Location: Indianapolis, Indiana
What you’ll be doing:What you’ll be doing:What you’ll be doing:What you’ll be doing:
Build machine learning models.
Document findings for colleagues.
Who we’re looking for:Who we’re looking for:Who we’re looking for:Who we’re looking for:
Working towards a bachelor’s or master’s degree and graduation date May 2027
A strong passion for technology
Minimum GPA: Minimum GPA: Minimum GPA: Minimum GPA: 3.0
Work authorization eligibility: Work authorization eligibility: To be considered, you
must also be a U.S. Citizen.
What we offer:What we offer:What we offer:What we offer:
Mentoring and benefits.
Apply Today
Remind me to apply.
'''
    x=job_parser.organize({'title':'ML Engineer','description':text})
    assert x['facts']['location']['value']=='Indianapolis, Indiana' and x['facts']['dates']['value']=='Permanent'
    assert [r['text'] for r in x['sections']['required']]==['Minimum GPA: 3.0']
    assert len(x['sections']['responsibilities'])==2 and len(x['sections']['eligibility'])==2
    assert x['sections']['eligibility'][1]['text']=='To be considered, you must also be a U.S. Citizen.'
    assert x['sections']['other'][0]['text']=='A strong passion for technology'
    assert 'Mentoring' not in str(x['sections']) and x['original_text']==text
    for group in x['sections'].values():
        for row in group:assert row['source'] in text
    for fact in x['facts'].values():
        assert all(q in text for q in fact['sources'])


def test_company_identity_covers_common_page_titles_without_guessing_locations():
    cases=[('Analyst - Rolls-Royce Careers.pdf','Analyst','Rolls-Royce'),('Analyst|Example Careers.pdf','Analyst','Example'),('Example Careers - Junior Analyst.pdf','Junior Analyst','Example'),('Analyst at Example.pdf','Analyst','Example'),('Analyst - Richmond, VA.pdf','Analyst - Richmond, VA','')]
    for filename,title,company in cases:
        x=job_parser.document_identity(filename,'Requirements\nSQL experience.\nRichmond, VA')
        assert (x['title'],x['company'])==(title,company)
    x=job_parser.document_identity('Analyst - Example Labs.pdf','Employer: Example Labs\nRequirements\nSQL.')
    assert (x['title'],x['company'])==('Analyst','Example Labs')
    x=job_parser.organize({'title':'Analyst','company':'My reviewed employer','description':'Company: Other employer\nRequirements\nSQL.'})
    assert x['company']=='My reviewed employer'


def test_company_can_use_employer_statement_but_not_generic_client_language():
    assert job_parser.company_hint('Example Labs is an equal opportunity employer.')[0]=='Example Labs'
    assert not job_parser.company_hint('Our client is an equal opportunity employer.')[0]
    assert not job_parser.company_hint('Remote\nRequirements\nSQL.','Analyst - Remote')[0]


# Browser-printed lists can lose their bullet glyphs. Keep each requirement
# separate and retain the untouched source for review and evidence citations.
UNMARKED_POSTING="""Integration Solutions Engineer
Position Summary
Our community includes major systems like the Mayo Clinic,
and Kaiser Permanente, as well as leading academic medical centers at the University of
Wisconsin and many more.
Epic is located just outside Madison, Wisconsin.
Requirements
Bachelor's or greater in engineering, math, information systems, or a related ﬁeld
A history of academic and professional success
Strong analytical and reasoning skills
Eligible to work in the U.S. without visa sponsorship
Relocation to the Madison, WI area (reimbursed)
COVID-19 vaccination
 Keep lookingApply Now
EPIC.COM  ABOUT EPIC  CONTACT
10/23/26, 5:07 PM Integration Solutions Engineer - Careers
https://epic.avature.net/Careers/FolderDetail/Integration-Solutions-Engineer/30063 2/3

1979 Milky Way | Verona, WI careers@epic.com | 608.271.9000
10/23/26, 5:07 PM Integration Solutions Engineer - Careers
https://epic.avature.net/Careers/FolderDetail/Integration-Solutions-Engineer/30063 3/3
"""


def test_unmarked_requirements_keep_qualifications_eligibility_and_relocation_separate():
    result=job_parser.organize({'title':'Integration Solutions Engineer','description':UNMARKED_POSTING})
    assert result['company']=='Epic'
    assert [r['text'] for r in result['sections']['required']]==[
        "Bachelor's or greater in engineering, math, information systems, or a related field",
        'A history of academic and professional success',
        'Strong analytical and reasoning skills']
    assert [r['text'] for r in result['sections']['eligibility']]==[
        'Eligible to work in the U.S. without visa sponsorship','COVID-19 vaccination']
    assert result['facts']['location']['value']=='Madison, WI'
    assert result['facts']['location']['sources']==['Relocation to the Madison, WI area (reimbursed)']
    assert result['notes']==['Relocation to the Madison, WI area (reimbursed)']
    assert result['original_text']==UNMARKED_POSTING
    for rows in result['sections'].values():
        for row in rows:
            assert row['source'] in UNMARKED_POSTING
            assert not any(noise in row['text'] for noise in ('https://','Milky Way','CONTACT','Apply Now','2/3','3/3'))
    assert len(job_parser.criteria({'description':UNMARKED_POSTING}))==5


def test_generic_careers_suffix_and_prose_at_phrase_are_not_an_employer():
    identity=job_parser.document_identity('Integration Solutions Engineer - Careers.pdf',UNMARKED_POSTING)
    assert identity['title']=='Integration Solutions Engineer'
    assert identity['company']=='Epic'
    assert identity['identity_sources']['company']['quote']=='Epic is located just outside Madison, Wisconsin.'
    assert not job_parser.company_hint('Academic medical centers at the University of Wisconsin.')[0]
    assert job_parser.document_identity('Analyst at The University.pdf','')['company']=='The University'
    assert not job_parser.company_hint('Our office is located in Boston, MA.')[0]


def test_footer_filter_does_not_remove_contact_or_url_requirements():
    text="""Requirements
Experience maintaining https://example.com/api integrations.
Must contact support@example.com when issues arise.
Knowledge of the CONTACT protocol.
"""
    result=job_parser.organize({'description':text})
    assert len(result['sections']['required'])==3
    assert 'support@example.com' in result['sections']['required'][1]['text']


def test_line_wrapping_preserves_degree_and_eligibility_continuations():
    text="""Requirements
Bachelor's or greater in engineering, math,
information systems, or a related field
A history of academic and professional success
Eligible to work in the U.S. without
visa sponsorship
Relocation to the Madison, WI area
(reimbursed)
COVID-19 vaccination
"""
    result=job_parser.organize({'description':text})
    assert len(result['sections']['required'])==2
    assert result['sections']['eligibility'][0]['text']=='Eligible to work in the U.S. without visa sponsorship'
    assert result['facts']['location']['value']=='Madison, WI'
    assert 'reimbursed' in result['facts']['location']['sources'][0]


def test_vaccination_research_experience_stays_a_professional_qualification():
    result=job_parser.organize({'description':'Requirements\nExperience analyzing vaccination outcomes.\nCOVID-19 vaccination required'})
    assert [r['text'] for r in result['sections']['required']]==['Experience analyzing vaccination outcomes.']
    assert [r['text'] for r in result['sections']['eligibility']]==['COVID-19 vaccination required']
