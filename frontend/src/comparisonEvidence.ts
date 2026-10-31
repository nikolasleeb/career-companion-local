const authorizationLabels:Record<string,string>={
 us_citizen:'U.S. citizen',
 authorized_us:'Authorized to work in the U.S.',
 sponsorship_now:'Employer sponsorship required now',
 sponsorship_future:'Employer sponsorship required in the future',
};
const answerLabels:Record<string,string>={yes:'Yes',no:'No',unsure:'Unsure'};

/** Display only: retain the original evidence for validation and saved snapshots. */
export function comparisonEvidenceText(evidence:{record_id:string;quote:string}):string{
 const field=evidence.record_id.startsWith('profile:')?evidence.record_id.slice(8):'';
 if(!Object.hasOwn(authorizationLabels,field))return evidence.quote;
 const quote=evidence.quote.trim();
 const match=quote.match(/^([a-z_]+)\s*=\s*(yes|no|unsure)$/i);
 const answer=match?.[1].toLowerCase()===field?match[2].toLowerCase():quote.toLowerCase();
 return Object.hasOwn(answerLabels,answer)?`${authorizationLabels[field]}: ${answerLabels[answer]}`:evidence.quote;
}
