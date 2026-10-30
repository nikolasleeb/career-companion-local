// Text-only list editing: the API continues to receive ordinary strings.
const marker=/^([\t ]*)[•*-](?:[\t ]+|$)/;
export type BulletEdit={start:number;end:number;text:string;exit?:boolean};
export function bulletDefault(value:string){return !value.trim()||marker.test(value.trimStart());}
export function bulletFormat(value:string,on:boolean){
 let inList=false;
 return value.split('\n').map(line=>{
  const prefix=line.match(marker);
  if(!on)return prefix?line.slice(0,prefix[1].length)+line.slice(prefix[0].length):line;
  if(!line.trim()){inList=false;return line;}
  if(prefix){inList=true;return line;}
  if(inList&&/^(?: {2}|\t)/.test(line))return line;
  inList=false;return '• '+line;
 }).join('\n');
}
export function bulletSelection(value:string,on:boolean,start:number,end:number){
 const before=value.split('\n'),after=bulletFormat(value,on).split('\n');
 const map=(position:number)=>{let oldOffset=0,newOffset=0;for(let i=0;i<before.length;i++){
  if(position<=oldOffset+before[i].length){const at=position-oldOffset,difference=after[i].length-before[i].length;
   const indent=before[i].match(marker)?.[1].length??0;
   return newOffset+(difference<0?at<=indent?at:Math.max(indent,at+difference):at+difference);
  }oldOffset+=before[i].length+1;newOffset+=after[i].length+1;
 }return newOffset-1;};return {start:map(start),end:map(end)};
}
function lineAt(value:string,at:number){const start=at<=0?0:value.lastIndexOf('\n',at-1)+1,end=value.indexOf('\n',at);return {start,end:end<0?value.length:end,text:value.slice(start,end<0?value.length:end)};}
function listAt(value:string,at:number){const line=lineAt(value,at);if(marker.test(line.text))return true;if(!/^(?: {2}|\t)/.test(line.text))return false;let p=line.start-1;while(p>=0){const previous=lineAt(value,p);if(marker.test(previous.text))return true;if(!/^(?: {2}|\t)\S|^ {2,}\S/.test(previous.text))return false;p=previous.start-1;}return false;}
export function bulletEnter(value:string,start:number,end:number,continuation=false):BulletEdit{
 const remaining=value.slice(0,start)+value.slice(end),line=lineAt(remaining,start),prefix=line.text.match(marker);
 if(prefix&&!line.text.slice(prefix[0].length).trim())return {start:line.start,end:line.end+(end-start),text:'',exit:true};
 if(continuation&&listAt(remaining,start))return {start,end,text:'\n  '};
 if(!line.text.trim())return {start,end,text:'\n'};
 return {start,end,text:'\n• '};
}
export function bulletBackspace(value:string,start:number,end:number):BulletEdit|null{
 if(start!==end)return null;const line=lineAt(value,start),prefix=line.text.match(marker);
 return prefix&&start===line.start+prefix[0].length?{start:line.start,end:start,text:'',exit:true}:null;
}
export function bulletInsert(value:string,start:number,end:number,text:string):BulletEdit{
 const line=lineAt(value,start),left=value.slice(line.start,start),right=value.slice(end,line.end),rows=text.replace(/\r\n?/g,'\n').split('\n');
 let inList=marker.test(rows[0]);
 rows[0]=!left.trim()&&!right.trim()&&!listAt(value,start)&&rows[0].trim()&&!marker.test(rows[0])?'• '+rows[0]:marker.test(left)&&!left.replace(marker,'').trim()?rows[0].replace(marker,''):rows[0];
 for(let i=1;i<rows.length;i++){
  if(!rows[i].trim()){inList=false;continue;}
  if(marker.test(rows[i])){inList=true;continue;}
  if(inList&&/^(?: {2}|\t)/.test(rows[i]))continue;
  inList=false;rows[i]='• '+rows[i];
 }
 return {start,end,text:rows.join('\n')};
}
export function editValue(value:string,edit:BulletEdit){return value.slice(0,edit.start)+edit.text+value.slice(edit.end);}
