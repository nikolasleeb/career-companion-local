import React from 'react';
import type {GuideQuestion,InterviewGuideData} from './InterviewGuide';
export function InterviewQuestionChoice({guide,value,onSelect,disabled=false}:{guide:InterviewGuideData;value:string;onSelect:(value:string)=>void;disabled?:boolean}){
 const selected=guide.questions.find(q=>q.id===value);
 return <section className="interview-question-choice"><label>Practice question<select aria-label="Practice question" value={value} disabled={disabled} onChange={e=>onSelect(e.target.value)}><option value="">Choose a guide question</option>{guide.questions.map(q=><option key={q.id} value={q.id}>{q.title}</option>)}</select></label>{value&&!selected&&<p role="alert">This guide question is unavailable. Choose another question.</p>}{selected&&<QuestionApproach question={selected}/>}</section>;
}
export function QuestionApproach({question}:{question:GuideQuestion}){return <div className="interview-selected-prompt"><h3>{question.title}</h3><p>{question.prompt}</p><h4>How to approach it</h4><ol>{question.structure.map(value=><li key={value}>{value}</li>)}</ol></div>;}
