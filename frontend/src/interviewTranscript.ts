export type TranscriptDraft={text:string;revision:string};
export function transcriptState(row:any,draft:TranscriptDraft|null){
 const generated=typeof row.data.transcript==='string'?row.data.transcript:'';
 const approved=!!row.data.reviewed_at&&typeof row.data.reviewed_transcript==='string'&&!!row.data.reviewed_transcript.trim();
 const hasDraft=!!draft&&typeof draft.text==='string';
 return {text:hasDraft?draft!.text:approved?row.data.reviewed_transcript:generated,
  revision:hasDraft?draft!.revision:row.updated_at,reviewed:!hasDraft&&approved,
  stale:hasDraft&&draft!.revision!==row.updated_at,generated,
  processing:row.data.state==='processing',partial:row.data.state==='partial'||row.data.state==='interrupted'};
}
