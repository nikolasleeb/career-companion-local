import React from 'react';
export type ProfileCourse={id:string;title:string;sources:string[]};
export function ProfileCoursePicker({courses,selected,onChange}:{courses:ProfileCourse[];selected:string[];onChange:(ids:string[])=>void}){
 return <ProfileSelectionPicker kind="courses" choices={courses} selected={selected} onChange={onChange}/>;
}
export function ProfileSkillPicker({skills,selected,onChange}:{skills:ProfileCourse[];selected:string[];onChange:(ids:string[])=>void}){
 return <ProfileSelectionPicker kind="skills" choices={skills} selected={selected} onChange={onChange}/>;
}
function ProfileSelectionPicker({kind,choices,selected,onChange}:{kind:'courses'|'skills';choices:ProfileCourse[];selected:string[];onChange:(ids:string[])=>void}){
 const count=choices.filter(c=>selected.includes(c.id)).length;
 const label=kind==='courses'?'Courses':'Skills';
 return <details className="career-course-picker"><summary><span>{label} from your Profile <small>(optional)</small></span><span className="career-profile-count">{count} of {choices.length} selected</span></summary>
  <fieldset><legend className="sr-only">{label} from your Profile</legend>
  <p className="small muted">{kind==='courses'?'Choose courses from your confirmed education and coursework records to include in this exploration. Nothing is selected automatically. A saved listing may include courses still in progress; selection does not claim completion.':'Choose explicitly listed skills from your confirmed Profile. Nothing is selected automatically. Find occupations listing any selected skill or an established alias. With studies, results must also have a study connection. These are exploration connections, not a proficiency or eligibility assessment.'}</p>
  {choices.length?<><div className="career-course-actions"><button type="button" className="button secondary" aria-label={'Select all Profile '+kind} disabled={count===choices.length} onClick={()=>onChange(choices.map(c=>c.id))}>Select all</button><button type="button" className="text-button" aria-label={'Clear Profile '+(kind==='courses'?'course':'skill')+' selection'} disabled={!count} onClick={()=>onChange([])}>Clear selection</button><span className="small muted" role="status">{count} of {choices.length} selected</span></div>
  <div className="career-course-grid">{choices.map(choice=><label key={choice.id}><input type="checkbox" checked={selected.includes(choice.id)} onChange={e=>onChange(e.target.checked?[...selected,choice.id]:selected.filter(id=>id!==choice.id))}/><span><strong>{choice.title}</strong><small>{choice.sources.join(' · ')}</small></span></label>)}</div></>:<p className="small muted">{kind==='courses'?'No courses are listed in your confirmed Profile yet. Add relevant classes in Profile → Resume content → Education & coursework, or enter subjects below.':'No skills are explicitly listed in your confirmed Profile yet. Add and confirm them in Profile → Resume content → Skills.'}</p>}
  </fieldset></details>;
}
