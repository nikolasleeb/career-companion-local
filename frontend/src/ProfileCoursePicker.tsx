import React from 'react';
export type ProfileCourse={id:string;title:string;sources:string[]};
export function ProfileCoursePicker({courses,selected,onChange}:{courses:ProfileCourse[];selected:string[];onChange:(ids:string[])=>void}){
 const count=courses.filter(c=>selected.includes(c.id)).length;
 return <fieldset className="career-course-picker"><legend>Courses from your Profile (optional)</legend>
  <p className="small muted">Choose courses from your confirmed education and coursework records to include in this exploration. Nothing is selected automatically. A saved listing may include courses still in progress; selection does not claim completion.</p>
  {courses.length?<><div className="career-course-actions"><button type="button" className="button secondary" aria-label="Select all Profile courses" disabled={count===courses.length} onClick={()=>onChange(courses.map(c=>c.id))}>Select all</button><button type="button" className="text-button" aria-label="Clear Profile course selection" disabled={!count} onClick={()=>onChange([])}>Clear selection</button><span className="small muted" role="status">{count} of {courses.length} selected</span></div>
  <div className="career-course-grid">{courses.map(course=><label key={course.id}><input type="checkbox" checked={selected.includes(course.id)} onChange={e=>onChange(e.target.checked?[...selected,course.id]:selected.filter(id=>id!==course.id))}/><span><strong>{course.title}</strong><small>{course.sources.join(' · ')}</small></span></label>)}</div></>:<p className="small muted">No courses are listed in your confirmed Profile yet. Add relevant classes in Profile → Resume content → Education & coursework, or enter subjects below.</p>}
 </fieldset>;
}
