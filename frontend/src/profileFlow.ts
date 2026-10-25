import {answerExperienceIds} from './answerReview';
// Profile presentation state only. Completion always comes from the server.
export const profilePanes=['personal','education','employment','project','volunteering','skills','eligibility'];
export type StoryScope={experienceId?:string;standalone?:boolean};
export type ProfileState={version:1;view:'resume'|'stories';scope:StoryScope;open:string[];returnY:number};
export function firstUnfinished(sections:any[]){return ['education','coursework','employment','project','volunteering','skills'].find(id=>sections.some(s=>s.id===id&&!['complete','empty'].includes(s.status)))||'';}
export function paneFor(section:string){return section==='coursework'?'education':section;}
export function restoreProfile(value:any,sections:any[]):ProfileState{
 const valid=value?.version===1;
 const first=paneFor(firstUnfinished(sections));
 return {version:1,view:valid&&value.view==='stories'?'stories':'resume',scope:valid?{...(typeof value.scope?.experienceId==='string'?{experienceId:value.scope.experienceId}:{}),...(value.scope?.standalone===true?{standalone:true}:{})}:{},open:valid&&Array.isArray(value.open)?profilePanes.filter(k=>value.open.includes(k)):(first?[first]:[]),returnY:valid&&Number.isFinite(value.returnY)&&value.returnY>=0?value.returnY:0};
}
// Explicit Profile navigation returns home; reload still restores the current subview.
export function profileHome(state:ProfileState):ProfileState{return {...state,view:'resume',scope:{},returnY:0};}
export function setupTarget(sections:any[]){const section=firstUnfinished(sections);return {pane:paneFor(section),heading:section==='coursework'?'profile-coursework-title':section?'profile-'+section+'-title':'profile-finish-title'};}
export function sectionStatus(section:any){if(!section)return 'Optional';return section.status==='complete'?`${section.confirmed_count} reviewed ${section.confirmed_count===1?'entry':'entries'}`:section.status==='empty'?'Nothing to add yet':section.status==='needs_review'?`${section.draft_count} ${section.draft_count===1?'draft needs':'drafts need'} review`:section.id==='education'?'Required · add school and qualification':'Not started';}
export function storyInScope(row:any,scope:StoryScope){return (!scope.experienceId||answerExperienceIds(row.data).includes(scope.experienceId))&&(!scope.standalone||(row.data.status==='confirmed'&&row.data.answer_kind==='experience'&&(row.data.category||'project')==='project'&&!answerExperienceIds(row.data).length&&!Object.keys(row.data.backed_fields||{}).length));}
// Explain only requirements the server reports as unfinished; never derive access locally.
export function setupBlockers(sections:any[],records:any[]){return sections.filter(s=>s.id==='education'&&s.status!=='complete').map(section=>{
 const drafts=records.filter(r=>r.data.category===section.id&&!r.data.confirmed).map(r=>r.data.title).filter(Boolean);
 const message=section.status==='needs_review'?(drafts.length?'Review and confirm: '+drafts.join(', ')+'.'+(section.draft_count>drafts.length?' Also review pending source findings.':''):'Review or remove pending drafts and source findings.'):
 section.id==='education'?'Add confirmed education with a school and qualification.':'Add reviewed information or choose “Nothing to add yet” in this section.';
 return {id:section.id,title:section.id==='skills'?'Skills & certifications':section.title||section.id,message,...setupTarget([section])};
});}

export function finishSetupReason(blockers:ReturnType<typeof setupBlockers>,busy:string){return [blockers.length?'Complete these items first:\n'+blockers.map(b=>'• '+b.title+': '+b.message).join('\n'):'',busy?'Please wait: '+busy+'.':''].filter(Boolean).join('\n');}
