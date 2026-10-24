"""Test a release image with disposable data, no network and no provider key."""
import argparse
import json
import subprocess
import uuid

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('image')
args=p.parse_args()
name='career-companion-smoke-'+uuid.uuid4().hex[:12]
program=r'''
import http.cookiejar,json,os,time,urllib.error,urllib.request
from app import config,db
assert os.getuid()==10001
assert not config.OPENAI_KEY and not config.ALLOW_SERVER_AI_KEY
base='http://127.0.0.1:3000/api'
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
csrf=''
def request(path,method='GET',data=None):
 headers={'Content-Type':'application/json'}
 if csrf:headers['X-CSRF-Token']=csrf
 req=urllib.request.Request(base+path,method=method,headers=headers,data=json.dumps(data).encode() if data is not None else None)
 with opener.open(req,timeout=5) as response:return json.load(response)
for _ in range(40):
 try:
  assert request('/health')['status']=='ok';break
 except (OSError,AssertionError):time.sleep(.5)
else:raise AssertionError('App did not become healthy')
with db.connect() as c:
 assert c.execute('SELECT count(*) FROM users').fetchone()[0]==0,'Image contains existing account data'
 assert c.execute('SELECT count(*) FROM entities').fetchone()[0]==0,'Image contains existing records'
try:request('/me');raise AssertionError('Anonymous account API should require sign-in')
except urllib.error.HTTPError as error:assert error.code==401
account=request('/auth/register','POST',{'username':'release-smoke','password':'fictional-release-smoke-only'})
csrf=account['csrf']
assert account['capabilities']['openai_key_source']=='none'
request('/settings','PUT',{'mode':'custom','custom_model':'gpt-6.1-sol','custom_reasoning':'high','custom_speed':'fast'})
active=request('/me')['capabilities']['ai']['active']
assert active['speed']=='fast' and active['estimate']['usd']==.174
assert not request('/me')['capabilities']['openai']
profile=request('/private-application-profile')
assert isinstance(profile,dict)
with db.connect() as c:assert c.execute("SELECT count(*) FROM entities WHERE kind='usage_event'").fetchone()[0]==0
request('/auth/logout','POST')
print(json.dumps({'healthy':True,'nonroot':True,'clean_image':True,'account_creation':True,'account_key_required':True,'speed_settings':True,'private_profile_route':True,'provider_requests':0}))
'''
try:
    subprocess.run(['docker','run','-d','--name',name,'--network','none','--read-only',
                    '--tmpfs','/data:uid=10001,gid=10001','--tmpfs','/secrets:uid=10001,gid=10001',
                    '--tmpfs','/tmp:uid=10001,gid=10001','-e','OPENAI_API_KEY=',
                    '-e','ALLOW_SERVER_AI_KEY=false',args.image],check=True,stdout=subprocess.DEVNULL)
    result=subprocess.run(['docker','exec','-i',name,'python','-'],input=program,text=True,capture_output=True)
    if result.returncode:
        raise SystemExit('Image smoke test failed:\n'+result.stderr)
    print(result.stdout.strip())
finally:
    subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
