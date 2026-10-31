"""Editorial quality boundary tests use fictional evidence, never paid requests."""
import asyncio,copy
import pytest
from app import ai,resume_strategy as strategy,resume_builder,optimization,resume_conversation as guided,db
from app.network import ServiceError
from test_resume_strategy import scenario,source,provider,compose,bullet


def test_project_and_bullet_order_changes_without_mutating_source_indices(scenario):
 snap=source(scenario);original=copy.deepcopy(snap);rows=scenario[3];facts=strategy.catalog(snap)['facts']
 cloud=[f for f in facts if f['record_id']==rows['cloud']['id'] and f['field']=='description']
 energy=[f for f in facts if f['record_id']==rows['energy']['id'] and f['field']=='description']
 value={'headline':'','headline_evidence':[],'entries':[{'record_id':rows['cloud']['id'],'reason':'Strongest applied infrastructure evidence.','items':[bullet(f) for f in reversed(cloud)]},{'record_id':rows['energy']['id'],'reason':'Complementary analysis.','items':[bullet(energy[0])]}],'omissions':[],'keywords':[]}
 draft=strategy.materialize(value,strategy.catalog(snap),snap)
 expanded=optimization.apply(snap,draft);chosen=optimization.initial_selection(expanded,draft)
 out=resume_builder.select(expanded,chosen['content'],chosen['experience_ids'])
 projects=next(s for s in out['sections'] if s['title']=='Projects')['entries']
 assert [e['source_id'] for e in projects]==[rows['cloud']['id'],rows['energy']['id']]
 assert projects[0]['bullets']==[f['text'] for f in reversed(cloud)]
 assert snap==original
 for rid,indices in chosen['content'].items():
  original_ids=[strategy.entries(expanded)[rid]['content_items'][n]['item_id'] for n in indices]
  assert set(original_ids)=={i['item_id'] for i in strategy.entries(out)[rid]['content_items']}


@pytest.mark.parametrize('entry,expected',[
 ({'category':'employment','end_date':'Present'},(10000,12)),
 ({'category':'employment','end_date':'August 2026'},(2026,8)),
 ({'category':'employment','end_date':'2025-06'},(2025,6)),
 ({'category':'employment','dates':'June 2023 – Sep. 2024'},(2024,9)),
 ({'category':'education','expected_graduation':'May 2027'},(2027,5)),
 ({'category':'employment','start_date':'June 2026'},(2026,6)),
 ({'category':'employment','dates':'not provided'},(-1,-1)),
])
def test_reverse_chronology_uses_only_explicit_dates(entry,expected):
 assert resume_builder.chronological_key(entry)==expected


@pytest.mark.parametrize('text,removed',[
 ('Created Tableau charts from campaign practice data.',False),
 ('Improved campaign results with Tableau charts.',True),
 ('Delivered causal uplift through charts.',True),
 ('Reduced campaign cost by 10%.',True),
])
def test_absent_impact_disclaimer_can_be_omitted_only_without_effect_claim(text,removed):
 assert strategy.limitation_removed('Created Tableau charts; no causal uplift was established.',text)==removed


def test_negated_deployment_stays_protected_even_with_unrelated_disclaimer():
 assert strategy.limitation_removed('Did not deploy a production service; no impact was measured.','Deployed a production service.')


def test_editorial_receives_rendered_draft_and_full_canonical_sources(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario)
 user,job,session,rows=scenario
 out=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 editing=calls[2][1];assert editing['first_draft']['sections'] and editing['measured_layout']['pages']==1
 ids={f['id'] for f in editing['professional_evidence']['facts']}
 assert all(fid in ids for s in editing['first_draft']['sections'] for e in s['entries'] for i in e['items'] for fid in i['source_ids'])
 assert out['current']['data']['snapshot']['optimization']['strategy']['editorial_reviewed']


def test_editorial_cannot_publish_unsupported_numeric_rewrite(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);original=ai.structured
 async def revised(schema,payload,*a,**kw):
  out,meta=await original(schema,payload,*a,**kw)
  if payload.get('first_draft'):
   item=next(i for e in out['entries'] for i in e['items'] if 'Built a Python' in i['text']);item['text']='Built a Python prototype that cut costs by 91%.'
  return out,meta
 monkeypatch.setattr(ai,'structured',revised)
 with pytest.raises(ServiceError,match='unsupported number'):
  asyncio.run(guided.build(scenario[0],scenario[2]['id'],scenario[2]['data']['version'],'economy'))
 assert not db.list_entities(scenario[0],'resume_revision')


def test_editorial_cannot_hide_or_merge_explicit_wording_lock(scenario):
 snap=source(scenario);rid=scenario[3]['project']['id'];facts=[f for f in strategy.catalog(snap)['facts'] if f['record_id']==rid and f['field']=='description']
 result=compose(snap,rid,[bullet(f) for f in facts]);lock={'record_id':rid,'source_ids':[facts[0]['id']],'text':'Built a Python retrieval prototype for document review.'}
 checked=strategy.enforce_constraints(result,{'locked_items':{'x':lock}})
 assert checked['entries'][0]['items'][0]['text']==lock['text']
 merged=compose(snap,rid,[{'source_ids':[f['id'] for f in facts],'text':'Built a Python retrieval prototype and initially tested approximately 10 documents.','priority':90,'reason':'Applied work.'}])
 with pytest.raises(ServiceError,match='protected wording'):strategy.enforce_constraints(merged,{'locked_items':{'x':lock}})


@pytest.mark.parametrize('source,text,removed',[
 ('This was coursework, not investment advice.','Compared statements in finance coursework.',False),
 ('This was coursework, not investment advice.','Provided investment advice.',True),
 ('Did not own enterprise renewals.','Owned enterprise renewals.',True),
 ('No production deployment was performed.','Deployed the app to production.',True),
 ('Not only built a prototype but also tested it.','Built and tested a prototype.',False),
])
def test_material_negatives_are_scoped_to_the_actual_claim(source,text,removed):
 assert strategy.limitation_removed(source,text)==removed


def test_local_headline_edit_preserves_editorial_record_and_bullet_order(scenario,monkeypatch):
 from test_guided_resume import request
 from app.models import WorkingRender
 provider(monkeypatch,scenario);original=ai.structured
 async def ranked(schema,payload,*a,**kw):
  out,meta=await original(schema,payload,*a,**kw)
  if payload.get('first_draft'):
   out['entries'].reverse()
   for entry in out['entries']:entry['items'].reverse()
  return out,meta
 monkeypatch.setattr(ai,'structured',ranked)
 user,job,session,rows=scenario
 built=asyncio.run(guided.build(user,session['id'],session['data']['version'],'economy'))
 before=built['current']['data']['snapshot']
 body=request(built);body.headline='Reviewed project focus'
 edited=guided.render(user,built['id'],WorkingRender(expected_version=built['data']['version'],request_token='local-heading-order',resume=body))
 after=edited['current']['data']['snapshot']
 def ordered(snap):return [(s['title'],[(e['source_id'],[i['item_id'] for i in e['content_items']]) for e in s['entries']]) for s in snap['sections'] if s['entries']]
 assert ordered(after)==ordered(before)


def test_core_posting_skills_are_retained_without_inventing_or_stuffing(scenario):
 snap=source(scenario);ev=strategy.catalog(snap);rid=scenario[3]['cloud']['id'];fact=next(f for f in ev['facts'] if f['record_id']==rid and f['field']=='description')
 out=compose(snap,rid,[bullet(fact)])
 filled=strategy.retain_posting_skills(out,ev,snap,{})
 skills=[i['text'] for values in filled['composed_items'].values() for i in values if i['field']=='skill']
 assert skills==['Python','SQL']
 assert all(i['source_refs'] for values in filled['composed_items'].values() for i in values)
 assert 'Terraform' not in str(filled)
 # A deliberate user exclusion wins over the posting's terminology.
 sql=next(f for f in ev['facts'] if f['field']=='skill' and f['text']=='SQL')
 excluded=strategy.retain_posting_skills(compose(snap,rid,[bullet(fact)]),ev,snap,{'excluded_source_ids':[sql['id']]})
 assert 'SQL' not in [i['text'] for values in excluded['composed_items'].values() for i in values if i['field']=='skill']


def test_skill_matching_is_exact_and_recognizes_apache_product_short_name():
 evidence={'facts':[{'id':'a','field':'skill','text':'Apache Spark'},{'id':'b','field':'skill','text':'Java'},{'id':'c','field':'skill','text':'Python (intermediate, self-rated)'}]}
 assert [f['id'] for f in strategy.posting_skill_facts(evidence,{'description':'Python and Spark; JavaScript preferred.'})]==['c','a']



def test_high_reasoning_planner_has_bounded_automatic_allowance(scenario,monkeypatch):
 provider(monkeypatch,scenario);original=ai.structured;seen=[]
 async def capture(schema,payload,*a,**kw):
  seen.append((schema.__name__,kw.get('max_output_tokens')))
  return await original(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',capture);monkeypatch.setattr(ai,'effort',lambda mode:'high')
 asyncio.run(guided.build(scenario[0],scenario[2]['id'],scenario[2]['data']['version'],'economy'))
 assert seen[0]==('ResumeStrategy',32000)
 assert len(seen)==5
