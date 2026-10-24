"""Free inline answer persistence and explicit batched AI review for both builders."""
import copy
from fastapi import HTTPException
from . import db,profile_answers as library
from .models import ConversationMessage,CoverMessage,CoverContent

def module(builder):
    if builder=='resume':
        from . import resume_conversation
        return resume_conversation,'resume_conversation'
    from . import cover_letters
    return cover_letters,'cover_workspace'

def save(user,id,builder,body):
    service,_=module(builder)
    def change(data,c):
        questions={q['id']:q for q in library.stable_questions(data,builder)}
        if len({a.question_id for a in body.answers})!=len(body.answers) or any(a.question_id not in questions for a in body.answers):raise HTTPException(400,'Choose each question from this conversation once.')
        for answer in body.answers:
            q=questions[answer.question_id]
            if answer.expected_answer_version is not None and q['answer_version']!=answer.expected_answer_version:raise HTTPException(409,'This answer changed in another window. Reload the saved answer before replacing it.')
            if answer.text!=q.get('answer',''):
                q['answer']=answer.text;q['answer_version']+=1;q['answered_at']=db.now()
            q['status']='skipped' if answer.skipped else 'reviewed' if q.get('reviewed_answer_version')==q['answer_version'] and q['answer_version'] else 'open'
        library.sync_questions(data,builder)
    service.mutate(user,id,body.expected_version,change)
    return service.state(user,id)

async def review(user,id,builder,body):
    service,kind=module(builder);record=db.get(user,id,kind)
    if not record:raise HTTPException(404,'Conversation not found.')
    data=record['data']
    if data['version']!=body.expected_version:raise HTTPException(409,'The conversation changed. Reload before reviewing answers.')
    questions={q['id']:q for q in library.stable_questions(data,builder)}
    if len(set(body.question_ids))!=len(body.question_ids) or set(body.question_ids)-set(questions):raise HTTPException(400,'Choose valid questions from this conversation.')
    selected=[questions[i] for i in body.question_ids]
    if any(not q['answer'].strip() or q['status']=='skipped' for q in selected):raise HTTPException(400,'Write an answer before requesting review.')
    if sum(len(q['answer'])+len(q['text']) for q in selected)>11000:raise HTTPException(400,'Review fewer answers together; their combined length exceeds 11,000 characters.')
    field='proposals' if builder=='resume' else 'context_proposals'
    matching=[p for p in data.get(field,[]) if p.get('question_ids') and set(p['question_ids'])<=set(body.question_ids) and all(p.get('answer_versions',{}).get(qid)==questions[qid]['answer_version'] for qid in p['question_ids']) and p['status'] in ('pending','approved')]
    if matching and all(any(q['id'] in p['question_ids'] for p in matching) for q in selected):return service.state(user,id)
    text=selected[0]['answer'] if len(selected)==1 else '\n\n'.join('Answer to question '+q['id']+':\n'+q['answer'] for q in selected)
    if builder=='resume':result=await service.send(user,id,ConversationMessage(expected_version=body.expected_version,text=text,mode=body.mode,question_answers=[{'question_id':q['id'],'answer':q['answer']} for q in selected]))
    else:result=await service.send(user,id,CoverMessage(expected_version=body.expected_version,text=text,content=CoverContent.model_validate(data['content']),instructions=data.get('instructions',''),mode=body.mode,request_token=body.request_token or db.uid(),question_answers=[{'question_id':q['id'],'answer':q['answer']} for q in selected]))
    # Associate exact answer excerpts on the server, independent of the model's question guesses.
    previous_ids={p['id'] for p in data.get(field,[])}
    def associate(current,c):
        now={q['id']:q for q in library.stable_questions(current,builder)}
        for q in selected:
            if now[q['id']]['answer_version']!=q['answer_version']:raise HTTPException(409,'An answer changed while reviewing it. Review the latest answer; no outdated detail was approved.')
        for p in current.get(field,[]):
            if p['status']!='pending' or p['id'] in previous_ids:continue
            quotes=[f['user_quote'] for f in p.get('fields',[])] if builder=='resume' else [p.get('user_quote','')]
            ids=[q['id'] for q in selected if any(quote.strip() and quote in q['answer'] for quote in quotes)]
            if ids and all(any(quote in q['answer'] for q in selected) for quote in quotes):
                p['question_ids']=ids;p['answer_versions']={qid:now[qid]['answer_version'] for qid in ids}
                from .project_context import bind_proposal
                bind_proposal(user,current,p,builder)
            else:p['status']='rejected';p['validation_reason']='The proposed detail did not quote the submitted answer text.'
        for q in selected:now[q['id']]['last_reviewed_input_version']=q['answer_version']
        library.sync_questions(current,builder)
    service.mutate(user,id,result['data']['version'],associate)
    return service.state(user,id)
