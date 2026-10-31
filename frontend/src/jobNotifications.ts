type BrowserWorkers={getRegistrations:()=>Promise<readonly any[]>};
export async function retireJobNotifications(workers:BrowserWorkers|undefined=globalThis.navigator?.serviceWorker){
 if(!workers)return;
 try{for(const registration of await workers.getRegistrations()){
  const scripts=[registration.active,registration.waiting,registration.installing].filter(Boolean);
  if(!scripts.length||!scripts.every(worker=>new URL(worker.scriptURL).pathname==='/job-notifications.js'))continue;
  try{const subscription=await registration.pushManager?.getSubscription();if(subscription)await subscription.unsubscribe();}catch{/* Revoked subscriptions can already be unavailable. */}
  try{await registration.unregister();}catch{/* Best effort; the server no longer delivers alerts. */}
 }}catch{/* Browser policy can prevent service-worker access. */}
}
