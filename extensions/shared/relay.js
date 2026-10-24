/* Runs in an ISOLATED extension world only. No window messages or page bridge. */
(()=>{
  if(globalThis.__careerCompanionRelay===2)return;
  globalThis.__careerCompanionRelay=2;
  const api=globalThis.browser||globalThis.chrome;
  const extensionRoot=api.runtime.getURL('');
  const approvedOrigins=new Set(['http://localhost:3000','http://127.0.0.1:3000']);
  // Additional localhost ports are explicitly configured and checked by background.
  const isLocal=/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(location.origin);
  if(!approvedOrigins.has(location.origin)&&!isLocal)return;
  const routes={overview:['GET','/status'],revoke:['DELETE',id=>`/pairings/${id}`],control:['POST',id=>`/runs/${id}/control`],pair:['POST','/pairings/request'],context:['POST','/relay/context'],create:['POST','/runs'],scan:['POST',id=>`/runs/${id}/scan`],progress:['POST',id=>`/runs/${id}/progress`],status:['POST',id=>`/runs/${id}/relay-status`]};
  api.runtime.onMessage.addListener((message,sender,reply)=>{
    if(sender.id!==api.runtime.id||!sender.url?.startsWith(extensionRoot)||message?.channel!=='career-companion-relay-v1')return;
    (async()=>{
      if(location.origin!==message.appOrigin)throw Error('App origin changed. Reconnect.');
      if(!routes[message.operation]||typeof message.body!=='object'||Array.isArray(message.body)||JSON.stringify(message).length>180000)throw Error('Unsupported relay operation.');
      const route=routes[message.operation];
      if(typeof route[1]==='function'&&!/^[a-f0-9]{32}$/.test(message.runId||''))throw Error('Invalid run ID.');
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),15000);
      try{
      const common={credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'X-Requested-With':'XMLHttpRequest'}};
      const me=await fetch('/api/me',common);
      if(!me.ok||me.redirected)throw Error('Sign in to Career Companion, then reconnect this browser.');
      let account;try{account=await me.json();}catch{throw Error('Sign in to Career Companion. Its login response could not be read.');}
      if(message.accountId&&message.accountId!==account.id)throw Object.assign(Error('Account changed. Reconnect and pair again.'),{code:'account_changed'});
      const response=await fetch('/api/application-agent'+(typeof route[1]==='function'?route[1](message.runId):route[1]),{method:route[0],...common,headers:{...common.headers,'Content-Type':'application/json','X-CSRF-Token':account.csrf},...(route[0]==='GET'?{}:{body:JSON.stringify(message.body)})});
      if(response.status===401||response.redirected)throw Error('Login expired. Sign in to Career Companion, then reconnect.');
      let result;try{result=await response.json();}catch{throw Error('App returned an unreadable response. Check your login and connection.');}
      if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:response.status===403?'Connection not approved, expired or revoked. Check Career Companion.':response.status===422?'Form scan was rejected. Review unsupported controls on the employer tab.':'Assistant request rejected ('+response.status+'). Refresh status before retrying.');
      reply({ok:true,result,accountId:account.id});
      }finally{clearTimeout(timeout);}
    })().catch(error=>reply({ok:false,errorCode:error.code||'',error:error.name==='AbortError'?'Request timed out after 15 seconds. Filling stopped. Check your connection before resuming.':error.message||'Relay connection failed. Check Career Companion, then resume explicitly.'}));
    return true;
  });
})();
