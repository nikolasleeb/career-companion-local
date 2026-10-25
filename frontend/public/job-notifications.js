/* Push only: never cache account pages, API replies or private documents. */
self.addEventListener('push',event=>{
 let data={};try{data=event.data.json();}catch{}
 event.waitUntil(self.registration.showNotification('Career Companion: new job matches',{body:typeof data.body==='string'?data.body.slice(0,180):'Open Job Search to review newly found matches.',tag:typeof data.tag==='string'?data.tag:'job-digest',data:{url:'/?view=jobs&alerts=1'}}));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();const url=new URL('/?view=jobs&alerts=1',self.location.origin).href;
 event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(windows=>{const existing=windows.find(w=>new URL(w.url).origin===self.location.origin);if(existing)return existing.navigate(url).then(w=>w?.focus());return clients.openWindow(url);}));
});
