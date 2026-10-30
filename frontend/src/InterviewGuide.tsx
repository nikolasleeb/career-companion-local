import React from 'react';
export type GuideQuestion={id:string;title:string;prompt:string;theme:string;field:string;structure:string[];look_for:string[];mistakes:string[];source_ids:string[]};
export type InterviewGuideData={id:string;title:string;intro:string;blocks:{title:string;text:string}[];source_ids:string[];questions:GuideQuestion[];further_reading_ids?:string[]};
export type InterviewGuideSource={id:string;publisher:string;title:string;url:string;supports:string;access_note?:string};
export type InterviewGuideCatalog={version:string;reviewed_at:string;note:string;sources:InterviewGuideSource[];guides:InterviewGuideData[]};
export function InterviewGuide({guide,catalog,onPractice,setup}:{guide:InterviewGuideData;catalog:InterviewGuideCatalog;onPractice:(question?:GuideQuestion)=>void;setup?:React.ReactNode}){
 const ids=new Set([...guide.source_ids,...guide.questions.flatMap(q=>q.source_ids)]);
 const sources=new Map(catalog.sources.map(source=>[source.id,source]));
 const reading=(guide.further_reading_ids||[]).flatMap(id=>{const source=sources.get(id);return source?[source]:[];});
 const readingIds=new Set(reading.map(source=>source.id));
 return <div className="interview-guide">
  <section className="interview-guide-intro" aria-labelledby="interview-guide-title"><div className="section-header"><div><span className="eyebrow">LEARN THE FORMAT</span><h2 id="interview-guide-title">{guide.title}</h2><p>{guide.intro}</p></div><button type="button" className="button primary" onClick={()=>onPractice()}>Start practice</button></div><p className="small muted">Reading this guide and choosing a question make no AI requests.</p></section>
  {setup}
  <section className="interview-guide-structures" aria-label="Answer structures">{guide.blocks.map(block=><article key={block.title}><h3>{block.title}</h3><p>{block.text}</p></article>)}</section>
  <section aria-labelledby="interview-guide-questions"><h2 id="interview-guide-questions">Typical themes &amp; practice questions</h2><p className="small muted">Original practice prompts. These are examples to learn from, not predictions of an employer’s questions.</p><div className="interview-guide-grid">{guide.questions.map(q=><article className="interview-guide-question" key={q.id}><span className="tag">{q.field||q.theme}</span><h3>{q.title}</h3><p>{q.prompt}</p><details><summary>How to approach it</summary><h4>Useful structure</h4><ol>{q.structure.map(x=><li key={x}>{x}</li>)}</ol><h4>What to address</h4><ul>{q.look_for.map(x=><li key={x}>{x}</li>)}</ul><h4>Common mistakes</h4><ul>{q.mistakes.map(x=><li key={x}>{x}</li>)}</ul></details><button type="button" className="button secondary" onClick={()=>onPractice(q)} aria-label={'Practice this question: '+q.title}>Practice this question</button></article>)}</div></section>
  {reading.length>0&&<section className="interview-guide-reading" aria-labelledby="interview-reading-title"><h2 id="interview-reading-title">Further reading</h2><ul>{reading.map(source=><li key={source.id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher} — {source.title} ↗</a><p className="small muted">{source.supports}{source.access_note&&<> {source.access_note}</>}</p></li>)}</ul></section>}
  <details className="interview-guide-sources"><summary>Sources &amp; editorial notes · Reviewed {catalog.reviewed_at}</summary><p className="small muted">{catalog.note}</p>{catalog.sources.filter(s=>ids.has(s.id)&&!readingIds.has(s.id)).map(s=><article key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.publisher} — {s.title} ↗</a><p className="small muted">{s.supports}</p></article>)}</details>
 </div>;
}
