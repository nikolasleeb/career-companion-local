"""Published IPIP-NEO-120 scoring and separate, private technical-work guidance."""
import copy
import json
from pathlib import Path
from fastapi import HTTPException
VERSION='ipip-neo-120-2026-10-22-v1'
REPORT_VERSION='technical-work-report-v1'
SOURCE=json.loads(Path(__file__).with_name('ipip_neo120.json').read_text())
DOMAINS={'N':'Neuroticism','E':'Extraversion','O':'Openness to Experience','A':'Agreeableness','C':'Conscientiousness'}
# Original contextual guidance. These are response-scale descriptions, not norm groups.
GUIDANCE={
'N1':('less frequent worry','more frequent anticipation of difficulties','For uncertain requirements, write down risks and use a short check-in rather than repeatedly revisiting every possibility.'),
'N2':('less frequent irritation','more frequent frustration','During a difficult code review, pause before replying and separate the defect from the person.'),
'N3':('less endorsement of low mood or self-critical statements','more endorsement of low mood or self-critical statements','These personal responses do not establish a diagnosis or predict technical performance. No workplace recommendation is inferred from this facet.'),
'N4':('more ease with social exposure','more discomfort with social exposure','A written design proposal before a meeting can make it easier to contribute to a technical discussion.'),
'N5':('more restraint around impulses','more difficulty resisting impulses','Time-box side investigations and keep an explicit next task when a debugging session becomes distracting.'),
'N6':('less reported overwhelm','more reported overwhelm','A production-incident checklist, clear roles and an escalation path can reduce decisions made under pressure.'),
'E1':('a more reserved approach to new connections','a more readily connecting approach','Choose a sustainable way to build working relationships, such as a brief onboarding conversation or asynchronous introduction.'),
'E2':('a preference for less social stimulation','a preference for more social stimulation','Protect focused implementation time while agreeing when team discussion is useful; neither preference establishes collaboration skill.'),
'E3':('a preference for letting others lead','a preference for taking the lead','Make decision ownership explicit in design reviews so speaking frequency does not determine whose evidence is considered.'),
'E4':('a more measured activity preference','a busier activity preference','Set realistic work-in-progress limits for data pipelines or development tasks; activity preference is not output quality.'),
'E5':('less preference for excitement','more preference for excitement','Keep experimentation in a sandbox and use explicit deployment safeguards regardless of appetite for novelty.'),
'E6':('less outwardly cheerful expression','more outwardly cheerful expression','Use concrete progress and blocker updates; a communication style does not establish commitment or reliability.'),
'O1':('a more concrete imaginative style','a more expansive imaginative style','Pair architecture alternatives with small prototypes and acceptance criteria so ideas can be tested.'),
'O2':('less interest in artistic experiences','more interest in artistic experiences','This facet concerns artistic interests; it does not measure interface-design ability or technical creativity.'),
'O3':('less attention to emotional reactions','more attention to emotional reactions','When gathering stakeholder feedback, distinguish the underlying concern from the proposed technical solution.'),
'O4':('more preference for familiar approaches','more preference for variety','Use a bounded proof of concept to compare a new cloud service with an established tool before changing production systems.'),
'O5':('more preference for concrete material','more interest in abstract material','Connect theory to a worked example, benchmark or reproducible data experiment. This is not an intelligence score.'),
'O6':('less endorsement of the published liberalism-keyed items','more endorsement of the published liberalism-keyed items','These items concern personal political and value attitudes. They are not translated into technical-work recommendations or suitability judgments.'),
'A1':('a more questioning default toward others','a more trusting default toward others','Use evidence-based checks for data contracts and access permissions regardless of personal trust.'),
'A2':('less endorsement of the morality-keyed direction','more endorsement of the morality-keyed direction','These self-reports do not verify honesty or integrity. Use transparent documentation of limitations and decisions in technical work.'),
'A3':('more focus on personal priorities','more focus on helping others','Agree support windows and ownership so helping colleagues and completing your own engineering work remain manageable.'),
'A4':('a more confrontational response preference','a more accommodating response preference','In code review, state the evidence, impact and alternative; cooperation does not require accepting an unsafe change.'),
'A5':('more self-promoting self-description','more modest self-description','Describe your exact contribution in team updates, with enough detail to avoid either overstating or hiding your work.'),
'A6':('less endorsement of sympathetic concern','more endorsement of sympathetic concern','Ask about stakeholder constraints before settling a technical tradeoff, without assuming these responses establish empathy skill.'),
'C1':('less confidence in handling tasks','more confidence in handling tasks','Use a small reproducible test or staged milestone to calibrate confidence against results. This is not a competence test.'),
'C2':('more tolerance of disorder','more preference for order','Choose lightweight naming, version-control and dataset conventions that help others reproduce your work.'),
'C3':('less endorsement of obligation-following statements','more endorsement of obligation-following statements','Make data handling, review and operational responsibilities explicit rather than relying on an assumed work style.'),
'C4':('a more bounded effort preference','a more achievement-driven effort preference','Agree what done means and protect sustainable effort; ambition alone does not demonstrate results.'),
'C5':('more difficulty initiating or sustaining plans','more reported follow-through','Break a pipeline or implementation task into a visible next action and a checkable completion condition.'),
'C6':('a more immediate decision preference','a more deliberative decision preference','Match review depth to reversibility: a local experiment and a production migration need different decision checks.'),
}
DOMAIN_GUIDANCE={
'N':('less endorsement of emotional-reactivity statements','more endorsement of emotional-reactivity statements','Use clear escalation paths and predictable check-ins during incidents. Personal emotional responses are not a diagnosis or a measure of resilience at work.'),
'E':('a more reserved interaction style','a more outwardly engaged interaction style','Balance focused implementation with agreed collaboration points. Both quieter and more expressive styles can contribute to a technical team.'),
'O':('more preference for familiar or concrete experiences','more interest in varied or abstract experiences','Use reproducible experiments to connect exploration with dependable delivery. This domain includes personal interests and values, not just work preferences.'),
'A':('a more questioning or self-prioritizing style','a more accommodating or other-oriented style','Make disagreements evidence-based and responsibilities explicit. These responses do not prove integrity or teamwork skill.'),
'C':('a more flexible or less structured self-description','a more organized and persistent self-description','Use checklists and visible milestones for code, data and infrastructure changes. Self-description does not establish delivery performance.'),
}
DOMAIN_CONTEXT={
'N':[
 ('A calmer self-description may make uncertainty feel less intrusive; this does not establish incident-handling ability.','You may underestimate how much reassurance or detail other people need.','Explicit risk checks and time for teammates to raise concerns can complement a calmer preference.'),
 ('Sensitivity to uncertainty may encourage early attention to possible problems; this is a possibility to explore, not demonstrated risk-management skill.','Repeated uncertainty may consume attention during a difficult debugging session.','Clear incident roles, written next steps and predictable check-ins may help reduce uncertainty.')],
'E':[
 ('A quieter interaction preference may support time for reflection and independent thought.','Your reasoning may stay invisible if a team expects spontaneous discussion.','Written proposals, asynchronous review and planned discussion points may suit this preference.'),
 ('A more outward interaction preference may make frequent discussion feel natural.','Frequent discussion can interrupt your own or others’ concentration.','Collaborative sessions balanced with protected focus blocks may suit this preference.')],
'O':[
 ('Familiar and concrete approaches may make established workflows comfortable to maintain.','You may need an intentional opportunity to explore alternatives when a familiar tool stops fitting.','Worked examples and incremental trials may help you assess unfamiliar ideas.'),
 ('Varied or abstract experiences may make exploring alternatives feel engaging.','Exploration may become open-ended without a clear decision point.','Sandbox experiments, explicit hypotheses and a stopping criterion can support bounded exploration.')],
'A':[
 ('A questioning or self-prioritizing approach may make it natural to raise objections or protect a task boundary.','Direct disagreement may need extra explanation so others can engage with the concern.','A review process that asks for evidence, alternatives and respectful disagreement may help.'),
 ('An accommodating or other-oriented approach may make offering support feel natural.','Helping or accommodating others may crowd out your own priorities or an objection that needs to be heard.','Clear ownership, support windows and explicit invitations to challenge a design may help.')],
'C':[
 ('A flexible self-description may make loosely structured work feel comfortable.','Unclear next steps or long tasks may benefit from more external structure.','Lightweight checklists, short milestones and a visible next action may support follow-through.'),
 ('An organized and persistent self-description may make planning and completion routines feel natural.','Extra planning or polishing may continue after a change is already good enough.','Clear acceptance criteria, sustainable deadlines and explicit permission to stop polishing may help.')],
}

DOMAIN_MIDDLE={
'N':('Your broad responses are mixed; particular kinds of pressure may feel different.','A calm response in one setting may not generalize to a production incident or an unclear deadline.','Use the individual facets to reflect on the kind of uncertainty involved, and agree an escalation path.'),
'E':('A mixed interaction preference may allow different balances of conversation and reflection.','A team may still need you to make your preferred communication mode explicit.','Alternate focused implementation blocks with planned discussion, and check which mix helps you contribute.'),
'O':('Your responses combine familiar and exploratory preferences rather than pointing to one consistent extreme.','A single openness label may hide differences between abstract ideas, variety and personal interests.','Use the facets to distinguish interest in theory from interest in changing tools; test new approaches in a bounded experiment.'),
'A':('Your responses mix accommodation with questioning or prioritizing your own needs.','Supporting a teammate and challenging a design may pull in different directions.','Use explicit ownership and evidence-based review criteria so disagreement and cooperation can coexist.'),
'C':('Your responses combine structure and flexibility; individual facets may show where each feels natural.','Confidence, orderliness and follow-through may differ even when their broad average is near the middle.','Choose one practical aid for the current task, such as a definition of done, a short milestone or a deployment checklist.'),
}

PAIRS=[
('Collaboration','I like to work through a debugging problem independently before comparing notes.','I like to compare hypotheses with a teammate early in a debugging problem.'),
('Collaboration','I prefer an individually owned implementation task with a later review.','I prefer a shared implementation session with decisions made together.'),
('Structure','I prefer a clear sequence of steps before building a data pipeline.','I prefer a flexible outline that develops as I inspect the data.'),
('Structure','I prefer a well-defined ticket before starting a change.','I prefer to clarify a broad goal through a small initial implementation.'),
('Exploration','I prefer to deepen an established tool before trying an alternative.','I prefer to test alternative tools before committing to an approach.'),
('Exploration','I enjoy improving a familiar cloud workflow.','I enjoy investigating a new cloud workflow.'),
('Decision-making','I prefer to collect more evidence before an architecture decision.','I prefer to make a reversible architecture decision and learn from a trial.'),
('Decision-making','I prefer to compare several possible causes before testing a bug fix.','I prefer to test the most plausible cause first and iterate.'),
('Communication','I prefer to write out a technical proposal before discussing it.','I prefer to discuss a technical proposal before writing it out.'),
('Communication','I prefer asynchronous progress updates with time to reflect.','I prefer a brief live conversation for progress updates.'),
('Pace','I prefer longer uninterrupted blocks on one technical task.','I prefer alternating between shorter technical tasks.'),
('Pace','I prefer a steady delivery rhythm with predictable milestones.','I prefer a variable delivery rhythm organized around emerging priorities.'),
]

def catalog():
    facets=copy.deepcopy(SOURCE['facets'])
    # Interleave facets so consecutive pages do not focus on one domain. IDs are stable.
    items=[dict(f['items'][i],facet_id=f['id']) for i in range(4) for f in facets]
    return {'version':VERSION,'title':'IPIP-NEO-120','source_url':SOURCE['source_url'],'key_url':SOURCE['source_url'],'scoring_url':'https://ipip.ori.org/newScoringInstructions.htm','attribution':'Public-domain IPIP items and Johnson (2014) IPIP-NEO-120 scoring key. Technical-work explanations and comparisons are original app guidance, not part of the published measure.','instructions':'Describe yourself as you generally are now. Rate each statement independently, rather than how you wish to be. The original questionnaire includes personal, emotional and political statements. Answers and results stay private on this installation. Pause and resume whenever you need.','page_size':8,'options':[{'value':i+1,'label':v} for i,v in enumerate(['Very Inaccurate','Moderately Inaccurate','Neither Inaccurate nor Accurate','Moderately Accurate','Very Accurate'])],'items':items,'facets':facets,'dimensions':[{'id':k,'name':v} for k,v in DOMAINS.items()],'comparisons':[{'id':f'p{i+1}','theme':p[0],'left':p[1],'right':p[2]} for i,p in enumerate(PAIRS)]}

def validate(answers,comparisons):
    ids={q['id'] for q in catalog()['items']}
    if any(k not in ids or type(v)!=int or not 1<=v<=5 for k,v in answers.items()):raise HTTPException(422,'Choose ratings 1–5 for the published question IDs.')
    if any(k not in {f'p{i+1}' for i in range(12)} or v not in ('left','right') for k,v in comparisons.items()):raise HTTPException(422,'Choose a listed left or right work preference, or leave it unanswered.')

def description(mean,guide):
    low,high,tip=guide
    direction=low if mean<2.5 else high if mean>3.5 else f'a mix between {low} and {high}'
    return {'pattern':'Your responses suggest '+direction+'.','suggestion':tip,'lower_end':low,'upper_end':high}

def score(answers,comparisons,catalog_data=None):
    validate(answers,comparisons)
    if len(answers)!=120:raise HTTPException(400,'Answer all 120 statements to calculate results. Your saved progress remains available.')
    facets=[]
    for f in SOURCE['facets']:
        total=sum(answers[q['id']] if q['positive'] else 6-answers[q['id']] for q in f['items'])
        facets.append({'facet_id':f['id'],'name':f['name'],'total':total,'minimum':4,'maximum':20,'mean':total/4,**description(total/4,GUIDANCE[f['id']])})
    domains=[]
    for code,name in DOMAINS.items():
        total=sum(f['total'] for f in facets if f['facet_id'].startswith(code))
        context=DOMAIN_CONTEXT[code]
        lower,upper=context
        potential,friction,environment=(lower if total/24<2.5 else upper) if not 2.5<=total/24<=3.5 else DOMAIN_MIDDLE[code]
        domains.append({'potential':potential,'friction':friction,'environment':environment,'dimension_id':code,'name':name,'total':total,'minimum':24,'maximum':120,'mean':total/24,**description(total/24,DOMAIN_GUIDANCE[code])})
    preferences=[dict(p,choice=comparisons[p['id']],selected=p[comparisons[p['id']]]) for p in (catalog_data or catalog())['comparisons'] if p['id'] in comparisons]
    return {'version':REPORT_VERSION,'domains':domains,'facets':facets,'preferences':preferences,'explanation':'Means run from 1 to 5 after reverse scoring. The descriptive middle spans 2.5–3.5; these are response-scale descriptions, not population norms. No score is a percentile, diagnosis, technical-ability measure or hiring prediction. The app’s technical-work guidance is interpretive and has not been validated as a job-performance assessment.'}

# Version only the app-authored interpretation and comparison scenarios. The
# published 120 item texts, item IDs and scoring key stay unchanged.
LEGACY_VERSION=VERSION
LEGACY_CATALOG=catalog()
_base_score=score
VERSION='ipip-neo-120-2026-10-25-v2'
def neutral(text):
 replacements={'Technical-work':'Work','technical team':'team','technical discussion':'discussion','technical solution':'solution','technical tradeoff':'professional tradeoff','technical performance':'job performance','technical creativity':'professional creativity','technical-ability':'professional-ability','focused implementation':'focused work','shared implementation':'shared work','initial implementation':'initial practical step','implementation task':'work task','data pipeline':'project','code, data and infrastructure changes':'projects and process changes','deployment safeguards':'review safeguards','deployment checklist':'review checklist','a sandbox':'a bounded trial','pipeline or implementation task':'project','technical-work':'work','technical work':'work','technical task':'work task','technical proposal':'proposal','technical ability':'professional ability','a bug fix':'a proposed change','architecture decision':'important decision','cloud workflow':'work process','software':'work','debugging':'problem-solving','code review':'peer review','engineering team':'team'}
 for a,b in replacements.items():text=text.replace(a,b)
 return text
NEW_CATALOG=copy.deepcopy(LEGACY_CATALOG)
NEW_CATALOG.update(version=VERSION,title='IPIP-NEO-120',guidance_version='cross-discipline-work-v2')
NEW_CATALOG['attribution']=neutral(NEW_CATALOG['attribution'])
NEW_CATALOG['comparisons']=[{k:neutral(v) if isinstance(v,str) else v for k,v in p.items()} for p in NEW_CATALOG['comparisons']]
def catalog():return copy.deepcopy(NEW_CATALOG)
def catalog_for(version):return copy.deepcopy(LEGACY_CATALOG if version==LEGACY_VERSION else NEW_CATALOG)
def score(answers,comparisons,catalog_data=None):
 selected=catalog_data or catalog();value=_base_score(answers,comparisons,selected)
 if selected['version']==LEGACY_VERSION:return value
 def transform(v):
  if isinstance(v,str):return neutral(v)
  if isinstance(v,list):return [transform(x) for x in v]
  if isinstance(v,dict):return {k:transform(x) for k,x in v.items()}
  return v
 value=transform(value);value['version']='cross-discipline-work-report-v2';return value
