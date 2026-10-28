import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('.',import.meta.url));
const hash=createHash('sha256');
function tree(folder,label){
 for(const entry of readdirSync(folder,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
  if(entry.name==='__pycache__')continue;
  const path=join(folder,entry.name),key=label+'/'+entry.name;
  if(entry.isDirectory())tree(path,key);
  else if(entry.isFile()){hash.update(key+'\0');hash.update(readFileSync(path));hash.update('\0');}
 }
}
for(const [path,label] of [['src','client'],['public','assets'],['../backend/app','server'],['../data','catalog']])tree(resolve(root,path),label);
for(const path of ['index.html','package.json','pnpm-lock.yaml','vite.config.mjs','../backend/requirements.lock']){hash.update(path+'\0');hash.update(readFileSync(resolve(root,path)));}
const buildId=hash.digest('hex').slice(0,32);
export default {
 define:{__APP_BUILD_ID__:JSON.stringify(buildId)},
 plugins:[{name:'workspace-build-identity',generateBundle(){this.emitFile({type:'asset',fileName:'build-info.json',source:JSON.stringify({build_id:buildId})});}}],
};
