"""Shared-core browser packages. Safari conversion is a separate step."""
import json,shutil,zipfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'packages'
def build():
    OUT.mkdir(exist_ok=True)
    for browser in ('chrome','safari'):
        dest=OUT/browser;dest.mkdir(exist_ok=True)
        for source in (ROOT/'shared').iterdir():
            if source.is_dir():shutil.copytree(source,dest/source.name,dirs_exist_ok=True)
            else:shutil.copy2(source,dest/source.name)
        manifest={'manifest_version':3,'name':'Career Companion','version':'1.0.5','description':'Account-connected application filling. Pauses for private questions and stops before submission.','permissions':['activeTab','scripting','storage'],'optional_host_permissions':['http://localhost/*','http://127.0.0.1/*','https://career-companion.austrich-server.com/*'],'icons':{str(n):f'icons/icon-{n}.png' for n in (32,48,128)},'action':{'default_title':'Career Companion','default_popup':'popup.html'},'background':{'service_worker':'background.js'} if browser=='chrome' else {'scripts':['background.js']},'content_security_policy':{'extension_pages':"script-src 'self'; object-src 'none'"}}
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        package=OUT/f'career-companion-{browser}.zip'
        with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for f in sorted(dest.rglob('*')):
                if f.is_file():archive.write(f,f.relative_to(dest))
        print(package.name,hashlib.sha256(package.read_bytes()).hexdigest())
if __name__=='__main__':build()
