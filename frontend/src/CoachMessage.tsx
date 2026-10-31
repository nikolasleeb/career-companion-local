import {chatBlocks} from './assistantText';
export default function CoachMessage({text}:{text:string}){
 return <div className="coach-message-prose">{chatBlocks(text).map((block,i)=>block.kind==='code'?<pre key={i}><code>{block.parts[0].text}</code></pre>:<p className="preserve" key={i}>{block.parts.map((part,j)=>part.kind==='code'?<code key={j}>{part.text}</code>:part.text)}</p>)}</div>;
}
