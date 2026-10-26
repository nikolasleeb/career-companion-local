// Present an existing GitHub profile in its dedicated field. Saving remains explicit.
export function separateGithubProfile<T extends Record<string,any>>(profile:T):T{
 if(!profile.website||profile.github)return profile;
 try{const url=new URL(profile.website);const reserved=['about','contact','enterprise','explore','features','issues','login','marketplace','new','notifications','orgs','organizations','pricing','pulls','search','settings','signup','sponsors','topics','trending'];const username=url.pathname.replace(/^\/|\/$/g,'');
  if(['https:','http:'].includes(url.protocol)&&['github.com','www.github.com'].includes(url.hostname.toLowerCase())&&/^\/[a-z0-9-]+\/?$/i.test(url.pathname)&&!url.username&&!url.password&&!url.search&&!url.hash&&!reserved.includes(username.toLowerCase()))return {...profile,website:'',github:profile.website};
 }catch{}
 return profile;
}
