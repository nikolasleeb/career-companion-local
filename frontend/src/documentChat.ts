import {useState} from 'react';
export function chatBufferKey(account:string,builder:string,job:string,resume=''){return 'next-step-document-chat:'+account+':'+builder+':'+job+':'+resume;}
export function readChatBuffer(key:string,storage:Storage=localStorage){try{return storage.getItem(key)||'';}catch{return '';}}
export function writeChatBuffer(key:string,text:string,storage:Storage=localStorage){try{if(text)storage.setItem(key,text);else storage.removeItem(key);}catch{}}
export function useDocumentChatBuffer(account:string,builder:string,job:string,resume=''){
 const key=chatBufferKey(account,builder,job,resume);
 const [saved,setSaved]=useState(()=>({key,value:readChatBuffer(key)}));
 const value=saved.key===key?saved.value:readChatBuffer(key);
 const update=(next:string|((previous:string)=>string))=>setSaved(previous=>{
  const old=previous.key===key?previous.value:readChatBuffer(key),text=typeof next==='function'?next(old):next;
  writeChatBuffer(key,text);return {key,value:text};
 });
 return [value,update] as const;
}
