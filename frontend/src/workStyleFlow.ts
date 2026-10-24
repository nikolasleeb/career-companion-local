export function assessmentLayout(catalog:any){
 const size=catalog.page_size||10,count=catalog.items.length,ratingPages=Math.ceil(count/size),comparisonPages=Math.ceil((catalog.comparisons?.length||0)/6);
 return {size,count,ratingPages,comparisonPages,pages:ratingPages+comparisonPages};
}
export function missingRatings(catalog:any,answers:Record<string,number>){return catalog.items.filter((q:any)=>!Number.isInteger(answers[q.id])||answers[q.id]<1||answers[q.id]>5);}
export function restoreResponses(row:any,saved:any){
 const base={answers:row.data.answers,pairs:row.data.comparison_answers||{},page:row.data.page||0,dirty:false,conflict:false};
 if(!saved||row.data.status!=='draft')return base;
 return {answers:saved.answers,pairs:saved.pairs||{},page:saved.page,dirty:true,conflict:saved.version!==row.data.version};
}
