/** Display-only, conservative cleanup. No HTML parsing and no saved-text mutation. */
export type ChatPart={kind:'text'|'code'|'literal';text:string};
export type ChatBlock={kind:'paragraph'|'code';parts:ChatPart[]};
export function inlineChat(text:string):ChatPart[]{
 const result:ChatPart[]=[];
 // Protect code, public URLs and quoted text before recognizing paired emphasis.
 const protectedText=/(`+)([^\n]*?)\1|https?:\/\/[^\s<>]+|"[^"\n]*"|“[^”\n]*”/g;
 let last=0;
 const prose=(value:string)=>value.replace(/(^|[^\w\\])\*\*(?=\S)([^*\n]*?\S)\*\*(?!\w)/g,'$1$2').replace(/(^|[^\w\\])__(?=\S)([^_\n]*?\S)__(?!\w)/g,'$1$2').replace(/(^|[^\w\\])\*(?=\S)([^*\n]*?\S)\*(?!\w)/g,'$1$2').replace(/(^|[^\w\\])_(?=\S)([^_\n]*?\S)_(?!\w)/g,'$1$2');
 for(const match of text.matchAll(protectedText)){
  if(match.index!>last)result.push({kind:'text',text:prose(text.slice(last,match.index))});
  result.push({kind:match[1]?'code':'literal',text:match[1]?match[2]:match[0]});last=match.index!+match[0].length;
 }
 if(last<text.length)result.push({kind:'text',text:prose(text.slice(last))});
 return result;
}
export function chatBlocks(source:string):ChatBlock[]{
 const blocks:ChatBlock[]=[];let lines:string[]=[];let fence='';let code:string[]=[];
 const flush=()=>{if(lines.length){blocks.push({kind:'paragraph',parts:lines.flatMap((line,i)=>[...(i?[{kind:'text' as const,text:'\n'}]:[]),...(line.trimStart().startsWith('>')?[{kind:'literal' as const,text:line}]:inlineChat(line.replace(/^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$/,'$1')))])});lines=[];}};
 for(const line of source.split('\n')){
  const marker=line.match(/^ {0,3}(`{3,}|~{3,})([^`]*)$/);
  if(fence){if(marker&&marker[1][0]===fence[0]&&marker[1].length>=fence.length){blocks.push({kind:'code',parts:[{kind:'code',text:code.join('\n')}]});fence='';code=[];}else code.push(line);continue;}
  if(marker){flush();fence=marker[1];continue;}
  if(!line.trim())flush();else lines.push(line);
 }
 flush();if(fence)blocks.push({kind:'code',parts:[{kind:'code',text:code.join('\n')}]});
 return blocks;
}
export function coachResearchLabel(data:any):string{
 const outcome=data.research_diagnostics?.outcome;
 if(outcome==='saved_sources')return 'Saved relevant web sources';
 if(outcome==='relevant_sources')return 'Relevant web sources checked';
 if(outcome==='limited_evidence')return 'Limited relevant web evidence';
 if(outcome==='unavailable')return 'Research unavailable · no relevant verified sources';
 if(outcome==='clarification')return 'Public subject needs clarification · no web search';
 if(data.research_used)return 'Saved web research · relevance not assessed';
 if(data.local_lookup_used)return 'Published local BLS / occupation tables checked';
 return data.reply?.references?.some((s:any)=>s.kind==='writing_guidance')?'Reviewed writing resources + eligible saved context':'Saved account context / general guidance';
}
