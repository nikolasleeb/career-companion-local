"""Manual catalog refresh helper: fetch concrete public learning pages without AI."""
import concurrent.futures,datetime,json,re,time,urllib.request,urllib.parse
from pathlib import Path
from html import unescape
ROOT=Path(__file__).resolve().parents[2]
SOURCES=Path(__file__).with_name('sources.json')
OUTPUT=Path(__file__).with_name('source_checks.json')
def check(row):
 url=row['url'];started=time.monotonic()
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; LearningCatalogReview/1.0)'}),timeout=22) as response:
   html=response.read(3500000).decode('utf-8','replace');final=response.url;status=response.status
  title=re.search(r'<title[^>]*>(.*?)</title>',html,re.S|re.I)
  heading=re.search(r'<h1[^>]*>(.*?)</h1>',html,re.S|re.I)
  clean=lambda v:unescape(re.sub('<[^>]+>',' ',v or '')).strip()
  title=clean(title.group(1) if title else '')
  heading=clean(heading.group(1) if heading else '')
  valid=status==200 and len(html)>1500 and not re.search(r'^404\b|page not found|access denied|^error\b|^just a moment',title,re.I)
  # Redirects to a provider home page do not establish learning-page coverage.
  if urllib.parse.urlsplit(final).path in ('','/') and urllib.parse.urlsplit(url).path not in ('','/'):valid=False
  return {'url':url,'final_url':final,'status':status,'title':title,'heading':heading,'bytes':len(html),'checked_at':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'valid':bool(valid)}
 except Exception as exc:return {'url':url,'valid':False,'error':str(exc),'checked_at':datetime.datetime.now(datetime.timezone.utc).date().isoformat()}
if __name__=='__main__':
 urls={r['url']:r for r in json.loads(SOURCES.read_text())};old={r['url']:r for r in json.loads(OUTPUT.read_text())} if OUTPUT.exists() else {}
 todo=[r for u,r in urls.items() if not old.get(u,{}).get('valid')]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for i,row in enumerate(pool.map(check,todo)):
   old[row['url']]=row
   if i%30==0:print(i,len(todo),row.get('status'),row.get('url'),flush=True);OUTPUT.write_text(json.dumps(list(old.values()),indent=2))
 OUTPUT.write_text(json.dumps(list(old.values()),indent=2));print('valid',sum(old[u]['valid'] for u in urls),'of',len(urls),flush=True)
