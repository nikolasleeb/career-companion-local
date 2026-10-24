/* Runs in an ISOLATED extension world only. No window messages or page bridge. */
(()=>{
  if(globalThis.__careerCompanionRelay)return;
  globalThis.__careerCompanionRelay=true;
  const api=globalThis.browser||globalThis.chrome;
  const extensionRoot=api.runtime.getURL('');
  const approvedOrigins=new Set(['http://localhost:3000','http://127.0.0.1:3000']);
  // Additional localhost ports are explicitly configured and checked by background.
  const isLocal=/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(location.origin);
  if(!approvedOrigins.has(location.origin)&&!isLocal)return;
  const routes={revoke:['DELETE',id=>`/pairings/${id}`],control:['POST',id=>`/runs/${id}/control`],pair:['POST','/pairings/request'],context:['POST','/relay/context'],create:['POST','/runs'],scan:['POST',id=>`/runs/${id}/scan`],progress:['POST',id=>`/runs/${id}/progress`],status:['POST',id=>`/runs/${id}/relay-status`]};
  api.runtime.onMessage.addListener((message,sender,reply)=>{
    if(sender.id!==api.runtime.id||!sender.url?.startsWith(extensionRoot)||message?.channel!=='career-companion-relay-v1')return;
    (async()=>{
      if(location.origin!==message.appOrigin)throw Error('App origin changed. Reconnect.');
      if(!routes[message.operation]||typeof message.body!=='object'||Array.isArray(message.body)||JSON.stringify(message).length>180000)throw Error('Unsupported relay operation.');
      const route=routes[message.operation];
      if(typeof route[1]==='function'&&!/^[a-f0-9]{32}$/.test(message.runId||''))throw Error('Invalid run ID.');
      const me=await fetch('/api/me',{credentials:'same-origin',cache:'no-store'});
      if(!me.ok)throw Error('Sign in to Career Companion and pair again.');
      const account=await me.json();
      if(message.accountId&&message.accountId!==account.id)throw Error('Account changed. Reconnect and pair again.');
      const response=await fetch('/api/application-agent'+(typeof route[1]==='function'?route[1](message.runId):route[1]),{method:route[0],credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':account.csrf},...(route[0]==='GET'?{}:{body:JSON.stringify(message.body)})});
      const result=await response.json();
      if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Assistant request rejected.');
      reply({ok:true,result,accountId:account.id});
    })().catch(error=>reply({ok:false,error:error.message||'Relay connection failed.'}));
    return true;
  });
})();
