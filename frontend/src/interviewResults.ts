export function interviewResults(attempts:any[],questionId:string){
 const selected=attempts.filter(row=>row.data.question_id===questionId);
 return {review:selected.filter(row=>row.data.operation==='review').at(-1),outline:selected.filter(row=>row.data.operation==='guide').at(-1),examples:selected.filter(row=>row.data.operation==='examples').at(-1)};
}
