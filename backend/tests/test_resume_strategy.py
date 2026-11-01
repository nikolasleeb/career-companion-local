"""Fictional contract and lifecycle checks for evidence-planned resumes."""
import asyncio,copy,json
import pytest
from app import ai,db,resume_strategy as strategy,resume_conversation as guided,resume_layout,resume_builder,optimization
from app.models import ExperienceItem,ConversationStart,WorkingRender,ResumeRequest
from app.network import ServiceError
from resume_strategy_fixtures import strategy as fake_strategy,composition as fake_composition

POSTING='''Graduate development program
Information Digital Technologies, Commercial and Finance tracks.
Analyze problems, propose original solutions and collaborate with diverse teams.
Required qualifications
A degree in a relevant discipline.
Preferred qualifications
Python, SQL and cloud technologies.
Responsibilities
Build digital solutions and explain results to stakeholders.
'''

@pytest.fixture
def scenario(client,account,monkeypatch):
 user=account['id']
 def record(**d):return db.save(user,'experience',ExperienceItem(confirmed=True,**d).model_dump())
 degree=record(category='education',title='MS Data Science',degree='MS',major='Data Science',organization='Example University',expected_graduation='May 2027',gpa='4.0')
 intern=record(category='employment',title='Summer Intern',organization='Example Agency',start_date='June 2026',end_date='August 2026',description='Presented prototypes to planning stakeholders. Incorporated their feedback into the next iteration.')
 contractor=record(category='employment',title='Research Contractor',organization='Example University',start_date='September 2026',description='Expanded document-review rules after the internship.')
 project=record(category='project',title='Document review prototype',start_date='June 2026',description='Built a Python retrieval prototype. Initially tested approximately 10 documents.',contribution='A teammate prepared the source documents. The sponsor intended the prototype to inform broader AI adoption.',linked_employment_ids=[intern['id'],contractor['id']])
 cloud=record(category='project',title='Transport weather data pipeline',description='Designed AWS ingestion pipelines using EC2, Lambda, S3 and Glue. Built a Spark workload for distributed data cleaning.',contribution='Owned cloud architecture while a teammate handled predictive analytics.',linked_education_ids=[degree['id']])
 energy=record(category='project',title='Energy demand analysis',description='Analyzed gasoline prices using Python.',contribution='Completed course ABC123 independently except PowerPoint proofreading by a teammate.')
 skill=record(category='skills',title='Programming',skill_items=[{'name':'Python'},{'name':'SQL'}])
 from app import project_structure
 approved=[{**v,'scope':{'kind':'project','stage_ids':[]}} for v in project_structure.statements(project['data'])]
 project=db.save(user,'experience',{**project['data'],'project_stages':project_structure.stages(project['data']),'project_statements':approved},project['id'])
 job=db.save(user,'job',{'title':'Graduate Program','company':'Example Energy','description':POSTING})
 session=guided.start(user,ConversationStart(job_id=job['id']))
 return user,job,session,dict(degree=degree,intern=intern,contractor=contractor,project=project,cloud=cloud,energy=energy,skill=skill)


def source(scenario):return guided.source(scenario[0],scenario[2]['data'])

def bullet(fact,text=None):return {'source_ids':[fact['id']],'text':text or fact['text'],'priority':80,'reason':'Supports an employer priority.'}

def compose(snapshot,rid,items):
 return strategy.materialize({'headline':'','headline_evidence':[],'entries':[{'record_id':rid,'reason':'Posting relevance','items':items}],'omissions':[],'keywords':[]},strategy.catalog(snapshot),snapshot)


def test_linked_evidence_is_canonical_with_all_permitted_destinations(scenario):
 snap=source(scenario);rows=scenario[3];facts=strategy.catalog(snap)['facts']
 matches=[f for f in facts if f['text']=='Built a Python retrieval prototype.']
 assert len(matches)==1 and matches[0]['record_id']==rows['project']['id']
 assert set(matches[0]['allowed_destinations'])=={rows[k]['id'] for k in ('project','intern','contractor')}
 assert matches[0]['revision'] and matches[0]['dates'].startswith('June 2026')


def test_dense_narrative_splits_into_exact_distinct_passages(scenario):
 snap=source(scenario);rid=scenario[3]['intern']['id'];facts=[f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description']
 assert [f['text'] for f in facts]==['Presented prototypes to planning stakeholders.','Incorporated their feedback into the next iteration.']
 result=compose(snap,rid,[bullet(f) for f in facts]);assert len(result['entries'][0]['items'])==2


def test_reviewed_supporting_detail_keeps_primary_owner_and_version(scenario):
 user,job,session,rows=scenario
 from app import profile_answers
 detail=db.save(user,'profile_answer',{'status':'confirmed','answer_kind':'experience','experience_id':rows['project']['id'],'experience_ids':[rows['project']['id'],rows['intern']['id']],'text':'Selected for prior practical AI experience.','title':'Assignment context','version':3,'sources':[]})
 facts=strategy.catalog(source(scenario))['facts'];found=[f for f in facts if f['text']==detail['data']['text']]
 assert len(found)==1 and found[0]['supporting_details'][0]['record_id']==detail['id'] and found[0]['supporting_details'][0]['version']==3


@pytest.mark.parametrize('case',['unrelated_origins','forbidden_destination','repeated_source','foreign_source','unsupported_number','negation','changed_skill','header_duplicate'])
def test_invalid_composition_rejects_without_changing_profile(scenario,case):
 snap=source(scenario);rows=scenario[3];facts=strategy.catalog(snap)['facts'];before=db.list_entities(scenario[0],'experience')
 fact=next(f for f in facts if f['record_id']==rows['project']['id'] and f['field']=='description');rid=rows['project']['id'];items=[bullet(fact)]
 if case=='unrelated_origins':items[0]['source_ids'].append(next(f['id'] for f in facts if f['record_id']==rows['cloud']['id'] and f['field']=='description'))
 if case=='forbidden_destination':rid=rows['energy']['id']
 if case=='repeated_source':items.append(bullet(fact))
 if case=='foreign_source':items[0]['source_ids']=['other-account-source']
 if case=='unsupported_number':items[0]['text']='Reduced review time by 75%.'
 if case=='negation':
  fact=copy.deepcopy(fact);fact['text']='Did not deploy a production service.'
  # Separate minimal source with a real explicit limitation.
  e=strategy.entries(snap)[rid];e['content_items']=[{'item_id':'limited','field':'description','original':fact['text'],'text':fact['text']}];e['bullets']=[fact['text']]
  for row in strategy.entries(snap).values():row['content_items']=[i for i in row['content_items'] if i.get('project_source',{}).get('project_id')!=rid]
  f=next(f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description');items=[bullet(f,'Deployed a production service.')]
 if case=='changed_skill':
  f=next(f for f in facts if f['record_id']==rows['skill']['id'] and f['field']=='skill');rid=rows['skill']['id'];items=[bullet(f,'Java')]
 if case=='header_duplicate':items=[bullet(next(f for f in facts if f['record_id']==rid and f['field']=='header'))]
 if case=='changed_skill':
  result=compose(snap,rid,items);assert result['entries'][0]['items'][0]['text']==f['text']
 else:
  with pytest.raises(ServiceError):compose(snap,rid,items)
 assert db.list_entities(scenario[0],'experience')==before and not db.list_entities(scenario[0],'resume_draft')


def test_compatible_sources_can_make_one_traceable_bullet(scenario):
 snap=source(scenario);rid=scenario[3]['project']['id'];facts=[f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description']
 result=compose(snap,rid,[{'source_ids':[f['id'] for f in facts],'text':'Built a Python retrieval prototype and initially tested approximately 10 documents.','priority':90,'reason':'Applied technical work.'}])
 value=result['composed_items'][rid][0]
 assert len(value['source_refs'])==2 and all(r['record_id']==rid for r in value['source_refs'])
 assert 'approximately' in value['text']


def test_mixed_structured_and_narrative_group_uses_separate_exact_sources(scenario):
 user,_,_,rows=scenario;row=rows['project'];rid=row['id']
 db.save(user,'experience',{**row['data'],'tools':'Python, SQL'},rid)
 snap=source(scenario);facts=[f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field'] in ('tools','description','contribution')]
 result=compose(snap,rid,[{'source_ids':[f['id'] for f in facts],'text':'Deployed the Python service and reduced review time by 75%.','priority':90,'reason':'Selected technical evidence.'}])
 values=result['composed_items'][rid]
 assert [v['text'] for v in values]==[f['text'] for f in facts]
 assert all(len(v['source_refs'])==1 and v['source_refs'][0]['record_id']==rid for v in values)
 assert any('approximately 10' in v['text'] for v in values)
 assert any('intended' in v['text'] for v in values)
 assert any('teammate' in v['text'] for v in values)
 assert all('75%' not in v['text'] and 'Deployed' not in v['text'] for v in values)


def test_structured_group_keeps_each_skill_and_rejects_duplicate_ids(scenario):
 snap=source(scenario);rid=scenario[3]['skill']['id'];facts=[f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='skill']
 item={'source_ids':[f['id'] for f in facts],'text':'Invented skill summary','priority':80,'reason':'Relevant skills.'}
 values=compose(snap,rid,[item])['composed_items'][rid]
 assert [v['text'] for v in values]==[f['text'] for f in facts]
 with pytest.raises(ServiceError,match='repeated evidence'):
  compose(snap,rid,[{**item,'source_ids':item['source_ids']+[facts[0]['id']]}])


@pytest.mark.parametrize('case',['other_origin','wrong_destination','header','unavailable','reused'])
def test_mixed_group_still_enforces_source_boundaries(scenario,case):
 user,_,_,rows=scenario;rid=rows['project']['id']
 db.save(user,'experience',{**rows['project']['data'],'tools':'Python, SQL'},rid)
 snap=source(scenario);facts=strategy.catalog(snap)['facts']
 selected=[f for f in facts if f['record_id']==rid and f['field'] in ('tools','description')]
 item={'source_ids':[f['id'] for f in selected],'text':'Combined selection','priority':80,'reason':'Relevant.'};items=[item]
 if case=='other_origin':item['source_ids'].append(next(f['id'] for f in facts if f['record_id']==rows['cloud']['id'] and f['field']=='description'))
 if case=='wrong_destination':rid=rows['energy']['id']
 if case=='header':item['source_ids'].append(next(f['id'] for f in facts if f['record_id']==rid and f['field']=='header'))
 if case=='unavailable':item['source_ids'].append('other-account-source')
 if case=='reused':items.append(bullet(selected[0]))
 with pytest.raises(ServiceError):compose(snap,rid,items)


def test_header_qualifications_count_without_repeating_degree_as_bullet(scenario):
 snap=source(scenario);rid=scenario[3]['degree']['id'];fid=strategy.digest([rid,'header'])[:24]
 plan={'priorities':[{'id':'degree','source_ids':[fid]}]}
 selected=resume_builder.select(snap,{rid:[]},[rid]);assert strategy.coverage(plan,selected)[0]['included']


def test_missing_evidence_stays_unresolved(scenario):
 ev=strategy.catalog(source(scenario));plan={'priorities':[{'id':'x','text':'Terraform','posting_quote':'cloud technologies','kind':'preferred','evidence':'unresolved','source_ids':[],'essential':False,'reason':'No reviewed evidence.'}],'constraints':[]}
 assert strategy.validate_strategy(plan,ev,{'description':POSTING},[])['priorities'][0]['evidence']=='unresolved'
 plan['priorities'][0]['essential']=True
 with pytest.raises(ServiceError):strategy.validate_strategy(plan,ev,{'description':POSTING},[])


def test_source_signature_changes_when_relationship_or_fact_revision_changes(scenario):
 first=strategy.signature(source(scenario));row=scenario[3]['project']
 db.save(scenario[0],'experience',{**row['data'],'linked_employment_ids':[]},row['id'])
 assert first!=strategy.signature(source(scenario))


def provider(monkeypatch,scenario,mutate=None):
 calls=[]
 async def model(schema,payload,mode='economy',**kwargs):
  calls.append((schema.__name__,payload));assert kwargs.get('retry_allowed') is False
  if schema.__name__=='ResumeStrategy':value=fake_strategy(payload)
  elif schema.__name__=='ResumeComposition':
   value=fake_composition(payload)
   # Fictional controlled selection: useful substantive work, not bookkeeping.
   rid=scenario[3]['energy']['id'];value['entries']=[e for e in value['entries'] if e['record_id']!=rid];value['omissions']=[{'record_id':rid,'reason':'Cloud architecture and stakeholder work better demonstrate this digital track.'}]
   if mutate:mutate(value)
  elif schema.__name__=='ResumeQualityReview':value={'strengths':['Relevant supported examples.'],'findings':[],'next_actions':[]}
  elif schema.__name__=='DraftAudit':value={'approved':True,'issues':[]}
  else:value=payload['proposal']
  return value,{'model':'fictional','estimated_token_cost_usd':.001}
 monkeypatch.setattr(ai,'structured',model)
 def render(snap):return {**copy.deepcopy(snap),'layout':{'pages':1,'validated':True,'issues':[]},'artifacts':{'pdf':'eA==','docx':'eA=='}}
 monkeypatch.setattr(resume_layout,'render',render)
 from app import resume_quality
 monkeypatch.setattr(resume_quality,'document',lambda snap:{'text':'\n'.join(i['text'] for e in strategy.entries(snap).values() for i in e['content_items']),'checks':{'pages':1}})
 return calls


def test_shell_like_selection_explanation_and_local_render_are_free(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);user,job,session,rows=scenario
 result=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 assert [c[0] for c in calls]==['ResumeStrategy','ResumeComposition','ResumeQualityReview','ResumeComposition','ResumeQualityReview','DraftAudit']
 snap=result['current']['data']['snapshot'];included=set(snap['experience_ids'])
 assert rows['cloud']['id'] in included and rows['energy']['id'] not in included
 assert snap['optimization']['strategy']['focus'] and snap['optimization']['strategy']['priorities'][0]['included']
 assert all(i.get('source_refs') for e in strategy.entries(snap).values() for i in e['content_items'])
 before=len(calls);guided.state(user,result['id']);assert len(calls)==before


def test_mixed_source_group_finishes_without_retrying_paid_stages(scenario,monkeypatch):
 user,_,session,rows=scenario;rid=rows['cloud']['id']
 db.save(user,'experience',{**rows['cloud']['data'],'tools':'AWS, Spark'},rid)
 calls=provider(monkeypatch,scenario);original=ai.structured
 async def grouped(schema,payload,*args,**kwargs):
  value,meta=await original(schema,payload,*args,**kwargs)
  if schema.__name__=='ResumeComposition':
   tool=next(f for f in payload['professional_evidence']['facts'] if f['record_id']==rid and f['field']=='tools')
   entry=next(e for e in value['entries'] if e['record_id']==rid)
   entry['items']=[i for i in entry['items'] if tool['id'] not in i['source_ids']]
   entry['items'][0]['source_ids'].append(tool['id'])
  return value,meta
 monkeypatch.setattr(ai,'structured',grouped)
 result=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 assert [c[0] for c in calls]==['ResumeStrategy','ResumeComposition','ResumeQualityReview','ResumeComposition','ResumeQualityReview','DraftAudit']
 values=strategy.entries(result['current']['data']['snapshot'])[rid]['content_items']
 assert any(i['field']=='tools' and i['text']=='Tools: AWS, Spark' for i in values)
 assert all(len(i['source_refs'])==1 for i in values if i['field']=='tools')


def test_mid_request_source_change_preserves_prior_records(scenario,monkeypatch):
 user,job,session,rows=scenario
 def changed(value):db.save(user,'experience',{**rows['cloud']['data'],'description':'Changed during the request.'},rows['cloud']['id'])
 provider(monkeypatch,scenario,changed)
 with pytest.raises((ServiceError,__import__('fastapi').HTTPException)):asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 assert not db.list_entities(user,'resume_revision') and not db.list_entities(user,'resume_draft')


def test_final_fitted_coverage_detects_removed_evidence(scenario):
 snap=source(scenario);rid=scenario[3]['cloud']['id'];f=next(f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description')
 plan={'priorities':[{'id':'cloud','source_ids':[f['id']]}]}
 output=compose(snap,rid,[bullet(f)]);expanded=strategy.install(snap,output['composed_items']);key=output['entries'][0]['items'][0]['item_id'];entry=strategy.entries(expanded)[rid]
 final=resume_builder.select(expanded,{rid:[n for n,i in enumerate(entry['content_items']) if i['item_id']==key]},[rid])
 assert strategy.coverage(plan,final)[0]['included']
 final=resume_builder.select(snap,{scenario[3]['degree']['id']:[]},[scenario[3]['degree']['id']]);assert not strategy.coverage(plan,final)[0]['included']


def test_backup_import_remaps_composed_sources_and_detaches_missing_history(scenario,monkeypatch,client):
 calls=provider(monkeypatch,scenario);user,job,session,rows=scenario
 result=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 backup=client.get('/api/account/export').json();old_id=result['current']['id'];old_source=rows['project']['id']
 response=client.post('/api/account/import',files={'file':('fictional-resumes.json',json.dumps(backup).encode(),'application/json')})
 assert response.status_code==200,response.text
 imported=next(r for r in db.list_entities(user,'resume_revision') if r['id']!=old_id)
 refs=[ref for e in strategy.entries(imported['data']['snapshot']).values() for i in e['content_items'] for ref in i.get('source_refs',[])]
 assert refs and all(ref['record_id']!=old_source for ref in refs)
 assert all(db.get(user,ref['record_id'],'experience') for ref in refs)
 assert len(calls)==6
 # A historical missing record can be imported read-only, but cannot become current evidence.
 ref={'source_id':'a'*24,'record_id':'deleted-source','quote':'Former reviewed source.','supporting_details':[]}
 value={'source_refs':[ref]};strategy.backup_markers(value,set());assert ref['unavailable_record']
 strategy.validate_backup({'kind':'resume_revision','data':value},{})
 ref['record_id']=rows['intern']['id']
 with pytest.raises(ValueError):strategy.validate_backup({'kind':'resume_revision','data':value},{ref['record_id']:'job'})


def test_explicit_user_override_survives_full_reoptimization(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);user,job,session,rows=scenario
 first=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 snap=first['current']['data']['snapshot'];entry=strategy.entries(snap)[rows['project']['id']];item=next(i for i in entry['content_items'] if 'Built a Python' in i['text'])
 parts=first['current']['data']['catalog'];content={r['id']:[n for n,i in enumerate(r['items']) if any(i['item_id']==v['item_id'] for v in strategy.entries(snap).get(r['id'],{}).get('content_items',[]))] for r in parts}
 reviewed='Built a Python prototype for retrieval.'
 changed=guided.render(user,first['id'],WorkingRender(expected_version=first['data']['version'],request_token=db.uid(),resume=ResumeRequest(job_id=job['id'],experience_ids=snap['experience_ids'],content=content,headline='Reviewed digital focus',overrides={item['item_id']:reviewed})))
 full=asyncio.run(guided.build(user,first['id'],changed['data']['version'],'economy',feedback={'refresh_linked_evidence':True}))
 after=full['current']['data']['snapshot'];assert after['headline']=='Reviewed digital focus'
 assert reviewed in [i['text'] for e in strategy.entries(after).values() for i in e['content_items']]
 assert full['data']['user_constraints']['locked_items']


def test_cancellation_ends_before_any_draft_is_published(scenario,monkeypatch):
 async def stop(*args,**kwargs):raise asyncio.CancelledError()
 monkeypatch.setattr(ai,'structured',stop);user,job,session,rows=scenario
 with pytest.raises(asyncio.CancelledError):asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 assert not db.list_entities(user,'resume_draft') and not db.list_entities(user,'resume_revision')


def test_other_account_and_unreviewed_claims_never_enter_catalog(scenario,client):
 user,job,session,rows=scenario
 db.save(user,'experience',ExperienceItem(category='project',title='Unreviewed',description='SECRET_UNREVIEWED_CLAIM',confirmed=False).model_dump())
 other=client.post('/api/auth/register',json={'username':'separate-fictional-account','password':'fictional-test-password'}).json()
 db.save(other['id'],'experience',ExperienceItem(category='project',title='Other account',description='SECRET_OTHER_ACCOUNT',confirmed=True).model_dump())
 payload=json.dumps(strategy.catalog(source(scenario)))
 assert 'SECRET_UNREVIEWED_CLAIM' not in payload and 'SECRET_OTHER_ACCOUNT' not in payload


def test_import_remaps_constraint_sources_across_records():
 old='old-profile-id';new='new-profile-id';fact=strategy.digest([old,'item','Reviewed fact.'])[:24]
 records=[{'kind':'resume_revision','data':{'source_refs':[{'source_id':fact,'record_id':old,'item_id':'item','quote':'Reviewed fact.'}]}}]
 mapping=strategy.import_fact_mapping(records,{old:new})
 conversation={'user_constraints':{'locked_items':{'bullet':{'source_ids':[fact]}}}}
 restored=strategy.remap_import(conversation,{old:new},mapping)
 assert restored['user_constraints']['locked_items']['bullet']['source_ids']==[strategy.digest([new,'item','Reviewed fact.'])[:24]]


def test_narrative_can_retain_its_original_project_date_without_inventing_numbers(scenario):
 snap=source(scenario);rid=scenario[3]['project']['id'];fact=next(f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description' and f['text'].startswith('Built'))
 value=compose(snap,rid,[bullet(fact,'Built a Python retrieval prototype in June 2026.')])
 assert value['composed_items'][rid][0]['source_refs'][0]['dates'].startswith('June 2026')
 with pytest.raises(ServiceError):compose(snap,rid,[bullet(fact,'Built a Python retrieval prototype in June 2030.')])


def test_explicitly_removed_evidence_stays_excluded_on_full_optimization(scenario,monkeypatch):
 provider(monkeypatch,scenario);user,job,session,rows=scenario
 first=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 snap=first['current']['data']['snapshot'];removed=rows['cloud']['id'];catalog_rows=first['current']['data']['catalog']
 parts={r['id']:[n for n,i in enumerate(r['items']) if any(i['item_id']==v['item_id'] for v in strategy.entries(snap).get(r['id'],{}).get('content_items',[]))] for r in catalog_rows}
 parts[removed]=[]
 changed=guided.render(user,first['id'],WorkingRender(expected_version=first['data']['version'],request_token=db.uid(),resume=ResumeRequest(job_id=job['id'],experience_ids=[rid for rid in snap['experience_ids'] if rid!=removed],content=parts,headline=snap['headline'])))
 assert changed['data']['user_constraints']['excluded_source_ids']
 rebuilt=asyncio.run(guided.build(user,first['id'],changed['data']['version'],'economy',feedback={'refresh_linked_evidence':True}))
 assert removed not in rebuilt['current']['data']['snapshot']['experience_ids']


def test_manual_selection_cannot_repeat_a_source_in_raw_and_composed_bullets(scenario):
 from app import linked_project_evidence
 snap=source(scenario);rid=scenario[3]['project']['id'];fact=next(f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description' and f['text'].startswith('Built'))
 composed=compose(snap,rid,[bullet(fact)]);expanded=strategy.install(snap,composed['composed_items'])
 # Select the raw original and its checked composition together.
 e=strategy.entries(expanded)[rid];original=next(i for i in e['content_items'] if i['item_id']==fact['item_id']);generated=e['content_items'][-1]
 minimal={'sections':[{'entries':[{**e,'content_items':[original,generated],'bullets':[original['text'],generated['text']]}]}]}
 with pytest.raises(ServiceError,match='same reviewed fact'):linked_project_evidence.validate_selected(minimal)


def test_all_composition_stages_use_owner_constrained_contract(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);original=ai.structured;schemas=[]
 async def constrained(schema,payload,*args,**kwargs):
  value,meta=await original(schema,payload,*args,**kwargs)
  if schema.__name__=='ResumeComposition':
   schemas.append(schema)
   for entry in value['entries']:
    for item in entry['items']:item.pop('item_id',None)
   value=schema.model_validate(value).model_dump()
   assert payload['professional_evidence']['source_groups']
  return value,meta
 monkeypatch.setattr(ai,'structured',constrained)
 user,_,session,rows=scenario
 result=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 assert result['current'] and len(schemas)==2 and schemas[0] is schemas[1]
 assert [c[0] for c in calls]==['ResumeStrategy','ResumeComposition','ResumeQualityReview','ResumeComposition','ResumeQualityReview','DraftAudit']
 assert result['current']['data']['snapshot']['separate_certifications']
