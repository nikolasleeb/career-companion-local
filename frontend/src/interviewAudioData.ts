export function encodeWav(samples:Float32Array,rate=24000){
 if(samples.length/rate>300||samples.length/rate<.5)throw Error('Record between 0.5 seconds and 5 minutes.');
 const buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
 const str=(offset:number,text:string)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
 str(0,'RIFF');view.setUint32(4,36+samples.length*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,samples.length*2,true);
 for(let i=0;i<samples.length;i++){const v=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,v<0?v*32768:v*32767,true);}
 return new Blob([buffer],{type:'audio/wav'});
}
export async function recordingWav(blob:Blob){
 const context=new AudioContext();try{
  const decoded=await context.decodeAudioData(await blob.arrayBuffer());if(decoded.duration>300.05)throw Error('Recordings must be no longer than five minutes.');
  const offline=new OfflineAudioContext(1,Math.floor(Math.min(decoded.duration,300)*24000),24000),source=offline.createBufferSource();source.buffer=decoded;source.connect(offline.destination);source.start();return encodeWav((await offline.startRendering()).getChannelData(0));
 }finally{await context.close();}
}
export const audioActionKey=(account:string,session:string,question:string)=>'interview-audio-action:'+account+':'+session+':'+question;
