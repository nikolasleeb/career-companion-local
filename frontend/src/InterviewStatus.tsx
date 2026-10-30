import {useEffect,useState} from 'react';
import {processing} from './processing';
export function useGlobalInterviewProgress(){
 const [active,setActive]=useState(()=>processing.snapshot().length>0);
 useEffect(()=>processing.subscribe(()=>setActive(processing.snapshot().length>0)),[]);
 return active;
}
