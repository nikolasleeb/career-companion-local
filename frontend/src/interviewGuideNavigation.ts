const guideTypes=['behavioral','case','domain','presentation','other'];
export function interviewPage(tab=''):{type:string;setup:boolean}{
 if(tab==='coding')return {type:'coding',setup:true};
 const type=tab.replace(/-setup$/,'');
 return guideTypes.includes(type)?{type,setup:tab.endsWith('-setup')}:{type:'',setup:false};
}
export function guideTab(kind:string,setup=false){
 const type=kind==='star'?'behavioral':kind;
 return type==='coding'?'coding':guideTypes.includes(type)?type+(setup?'-setup':''):'';
}
