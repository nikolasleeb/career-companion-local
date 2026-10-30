"""Bundled editorial interview guides; browsing and starter questions use no AI."""
import json
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException

@lru_cache(maxsize=1)
def catalog():
 return json.loads((Path(__file__).parent/'data'/'interview_guides.json').read_text())

def starter(kind,question_id):
 for guide in catalog()['guides']:
  for question in guide['questions']:
   if question['id']==question_id:
    if ('behavioral' if kind=='star' else kind)!=guide['id']:raise HTTPException(422,'Choose a guide question for this interview type.')
    return {
     'question':question['prompt'],'topic':question['title'],
     'evaluation_focus':question['look_for'],'constraints':[],
     'examples':[],'hints':[],'references':[],'origin':'guide','code_execution':False,
     'guide_provenance':{'guide_id':guide['id'],'guide_title':guide['title'],
      'question_id':question['id'],'catalog_version':catalog()['version'],
      'reviewed_at':catalog()['reviewed_at'],'source_ids':question['source_ids']},
    }
 raise HTTPException(422,'This guide question is unavailable. Choose another guide question.')


def approach(kind, question):
 """Editorial structure is guidance, never evidence about the applicant."""
 guide=next((g for g in catalog()['guides'] if g['id']==('behavioral' if kind=='star' else kind)),None)
 selected=next((q for q in (guide or {}).get('questions',[]) if q['id']==question.get('guide_provenance',{}).get('question_id')),None)
 return {'structure':selected['structure'] if selected else [b['text'] for b in (guide or {}).get('blocks',[])],
         'use_star':kind in ('behavioral','star') and (not selected or selected['theme'] not in ('Introduction','Motivation','Strengths','Development'))}
