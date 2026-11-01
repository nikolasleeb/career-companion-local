import {useEffect,useState} from 'react';
import {ModelSelection} from './DocumentModelControl';
export function useDocumentEstimate(call:(path:string,method?:string,body?:any)=>Promise<any>,path:string,selection:ModelSelection|null,version:any){
 const [state,setState]=useState<any>(null);
 useEffect(()=>{let live=true;setState(null);if(!path||!selection?.valid)return;const timer=setTimeout(()=>{call(path,'POST',{...selection.pair,...(selection.resumeReviewMode?{resume_review_mode:selection.resumeReviewMode}:{})}).then(value=>{if(live)setState({...value,unsaved:selection.unsaved});}).catch(()=>{if(live)setState({unavailable:true,unsaved:selection.unsaved});});},150);return()=>{live=false;clearTimeout(timer);};},[path,JSON.stringify(selection),version]);
 return state;
}
