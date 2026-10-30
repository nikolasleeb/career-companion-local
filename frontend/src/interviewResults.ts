export function interviewResults(attempts:any[],questionId:string){
 const selected=attempts.filter(row=>row.data.question_id===questionId);
 return {review:selected.filter(row=>row.data.operation==='review').at(-1),outline:selected.filter(row=>row.data.operation==='guide').at(-1),examples:selected.filter(row=>row.data.operation==='examples').at(-1)};
}

/** A review always uses its saved recording snapshot, never a later recording. */
export function interviewReviewRecording(review:any,recording:any){
 if(review)return review.data.voice_id?{id:review.data.voice_id,created_at:review.created_at,data:{reviewed_transcript:review.data.transcript_snapshot,reviewed_at:review.created_at,delivery:review.data.delivery,metrics:review.data.delivery_metrics}}:null;
 return recording?.data.state!=='processing'?recording:null;
}
