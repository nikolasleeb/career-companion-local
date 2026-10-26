"""Private IPIP-50 reflection with published local scoring. Never part of applicant catalogs."""
import copy
import json
from fastapi import HTTPException
from pydantic import Field
from . import db, ai, work_style_neo as neo
from .models import StrictModel

VERSION='ipip-big-five-50-2026-10-22-v1'
URL='https://ipip.ori.org/new_ipip-50-item-scale.htm'
KEY_URL='https://ipip.ori.org/newBigFive5broadKey.htm'
SCORING_URL='https://ipip.ori.org/newScoringInstructions.htm'
# Exact sample item order and key, Goldberg (1992) Big-Five Factor Markers.
TEXTS=["Am the life of the party.","Feel little concern for others.","Am always prepared.","Get stressed out easily.","Have a rich vocabulary.","Don't talk a lot.","Am interested in people.","Leave my belongings around.","Am relaxed most of the time.","Have difficulty understanding abstract ideas.","Feel comfortable around people.","Insult people.","Pay attention to details.","Worry about things.","Have a vivid imagination.","Keep in the background.","Sympathize with others' feelings.","Make a mess of things.","Seldom feel blue.","Am not interested in abstract ideas.","Start conversations.","Am not interested in other people's problems.","Get chores done right away.","Am easily disturbed.","Have excellent ideas.","Have little to say.","Have a soft heart.","Often forget to put things back in their proper place.","Get upset easily.","Do not have a good imagination.","Talk to a lot of different people at parties.","Am not really interested in others.","Like order.","Change my mood a lot.","Am quick to understand things.","Don't like to draw attention to myself.","Take time out for others.","Shirk my duties.","Have frequent mood swings.","Use difficult words.","Don't mind being the center of attention.","Feel others' emotions.","Follow a schedule.","Get irritated easily.","Spend time reflecting on things.","Am quiet around strangers.","Make people feel at ease.","Am exacting in my work.","Often feel blue.","Am full of ideas."]
POSITIVE={1,3,5,7,9,11,13,15,17,19,21,23,25,27,31,33,35,37,40,41,42,43,45,47,48,50}
DIMENSIONS=[
 {'id':'1','name':'Extraversion','description':'Self-reported comfort with social interaction, speaking up and drawing attention. Different settings can bring out different approaches.','prompt':'Describe a time you chose to speak up or listen first. What did the situation need, what did you do, and what happened?'},
 {'id':'2','name':'Agreeableness','description':'Self-reported concern for others and approach to cooperation. Reflect on how you balance helping people with explaining disagreements.','prompt':'Recall a disagreement or a request for help. How did you understand the other person’s needs while explaining your own perspective?'},
 {'id':'3','name':'Conscientiousness','description':'Self-reported organization, preparation and follow-through. Consider the routines and conditions that help you complete work.','prompt':'Tell me about a project with competing priorities. What did you personally do to organize the work, and what would you improve?'},
 {'id':'4','name':'Emotional Stability','description':'Self-reported reactions to stress and emotional changes. This reflection is not a mental-health assessment or diagnosis.','prompt':'Recall a demanding deadline or unexpected setback. What actions helped you respond, and what did you learn?'},
 {'id':'5','name':'Intellect/Imagination','description':'Self-reported interest in ideas, reflection and imagination. This dimension is not an intelligence-test score.','prompt':'Describe a time you explored an unfamiliar idea or tried another approach. What did you test or learn, and how did it affect the work?'}]
OPTIONS=['Very Inaccurate','Moderately Inaccurate','Neither Accurate Nor Inaccurate','Moderately Accurate','Very Accurate']

def catalog():
    return {'version':VERSION,'title':'IPIP 50-item Big-Five Factor Markers','source_url':URL,'key_url':KEY_URL,'scoring_url':SCORING_URL,'attribution':'Public-domain IPIP items; Big-Five markers: Goldberg, L. R. (1992), Psychological Assessment, 4, 26–42.','instructions':'Describe yourself as you generally are now, rather than how you wish to be. Choose how accurately each statement describes you. You may pause and resume. Responses stay in this account on this installation.','options':[{'value':i+1,'label':t} for i,t in enumerate(OPTIONS)],'items':[{'id':str(i+1),'text':t} for i,t in enumerate(TEXTS)],'dimensions':copy.deepcopy(DIMENSIONS)}

def owned(user,id):
    value=db.get(user,id,'work_style')
    if not value:raise HTTPException(404,'Reflection attempt not found.')
    return value

def start(user):
    from .resume_conversation import write
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        current=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='work_style' ORDER BY created_at DESC",(user,)) if json.loads(r['payload'])['status']=='draft' and json.loads(r['payload'])['catalog_version']==neo.VERSION),None)
        if current:return current
        id=write(c,user,'work_style',{'version':1,'catalog_version':neo.VERSION,'catalog':catalog(),'status':'draft','answers':{},'comparison_answers':{},'page':0,'scores':[]})
    return owned(user,id)

def validate(answers):
    if any(k not in {str(i) for i in range(1,51)} or type(v)!=int or not 1<=v<=5 for k,v in answers.items()):raise HTTPException(422,'Choose response values 1–5 for question IDs 1–50.')

def mutate(user,id,version,answers,page,complete=False,comparisons=None):
    from .resume_conversation import write
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='work_style'",(id,user)).fetchone())
        if not row:raise HTTPException(404,'Reflection attempt not found.')
        data=row['data'];current=data['catalog_version'] in (neo.VERSION,neo.LEGACY_VERSION)
        if data['catalog_version'] not in (VERSION,neo.VERSION,neo.LEGACY_VERSION):raise HTTPException(409,'This questionnaire version is unavailable. Its history is preserved.')
        if data['version']!=version:raise HTTPException(409,'This assessment changed in another window. Your typed responses are retained; reload its version before retrying.')
        if data['status']!='draft':raise HTTPException(409,'Completed results are immutable. Start a new assessment for a retake.')
        comparisons=data.get('comparison_answers',{}) if comparisons is None else comparisons
        if current:neo.validate(answers,comparisons)
        else:
            validate(answers)
            if comparisons:raise HTTPException(422,'This historical questionnaire has no comparison section.')
        if page<0 or page>(16 if current else 4):raise HTTPException(422,'Choose a page in this questionnaire.')
        data.update(answers=answers,page=page,version=version+1)
        if current:data['comparison_answers']=comparisons
        if complete:
            if current:
                report=neo.score(answers,comparisons,neo.catalog_for(data['catalog_version']))
                data.update(report=report,scores=report['domains'],scoring_key={'version':neo.VERSION,'source_url':neo.SOURCE['source_url']})
            else:
                data.update(scores=score(answers),scoring_key={'positive':sorted(POSITIVE),'version':VERSION})
            data.update(status='completed',completed_at=db.now())
        write(c,user,'work_style',data,id)
    return owned(user,id)

def score(answers):
    validate(answers)
    if len(answers)!=50:raise HTTPException(400,'All 50 responses are required.')
    totals=[0]*5
    for i in range(1,51):totals[(i-1)%5]+=answers[str(i)] if i in POSITIVE else 6-answers[str(i)]
    return [{'dimension_id':d['id'],'name':d['name'],'total':totals[i],'maximum':50,'minimum':10,'description':d['description']} for i,d in enumerate(DIMENSIONS)]

class StoryPrompts(StrictModel):
    questions:list[str]=Field(min_length=1,max_length=3)

async def prompts(user,body):
    selected=[d for d in DIMENSIONS if d['id'] in body.themes]
    if not selected or len(selected)!=len(set(body.themes)):raise HTTPException(400,'Choose one to five reflection themes.')
    posting=db.get(user,body.job_id,'job') if body.job_id else None
    if body.job_id and not posting:raise HTTPException(404,'Posting not found.')
    # Deliberately no result ID, raw responses, numeric scores, or automatic trait interpretation.
    output,meta=await ai.structured(StoryPrompts,{'task':'Ask up to three questions helping the applicant recall genuine professional examples. General practice unless a posting is supplied. Use selected reflection THEMES only as topics, never evidence of applicant traits or skills. Do not invent examples, accomplishments or psychological conclusions. Ask individual actions, decisions, useful outcomes or learning; do not demand metrics. Do not answer the questions.','themes':[{'name':d['name'],'example_question':d['prompt']} for d in selected],'posting':posting['data'] if posting else None},body.mode)
    return db.save(user,'story_prompts',{'questions':output['questions'],'themes':[d['id'] for d in selected],'job_id':body.job_id,'ai':meta})

# Preserve the published legacy measure for saved attempts and compatibility callers.
legacy_catalog=catalog
def catalog():return neo.catalog()

def validate_backup(data):
    if data.get('status') not in ('draft','completed'):raise ValueError()
    version=data.get('catalog_version')
    if version==VERSION:
        validate(data['answers'])
        if data.get('catalog')!=legacy_catalog():raise ValueError()
        if data['status']=='completed' and data['scores']!=score(data['answers']):raise ValueError()
    elif version in (neo.VERSION,neo.LEGACY_VERSION):
        neo.validate(data['answers'],data.get('comparison_answers',{}))
        if data.get('catalog')!=neo.catalog_for(version):raise ValueError()
        if data['status']=='completed':
            report=neo.score(data['answers'],data.get('comparison_answers',{}),neo.catalog_for(version))
            if data.get('report')!=report or data['scores']!=report['domains']:raise ValueError()
    else:raise ValueError()
    if type(data.get('version'))!=int or data['version']<1:raise ValueError()
    if type(data.get('page'))!=int or not 0<=data['page']<=(16 if version in (neo.VERSION,neo.LEGACY_VERSION) else 4):raise ValueError()
