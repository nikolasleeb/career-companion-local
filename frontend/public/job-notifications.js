/* Retired job alerts: never display queued push messages or cache account data. */
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
 try{const subscription=await self.registration.pushManager.getSubscription();if(subscription)await subscription.unsubscribe();}
 finally{await self.registration.unregister();}
})()));
self.addEventListener('push',()=>{});
self.addEventListener('notificationclick',event=>event.notification.close());
