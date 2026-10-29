"""Read-only, published wage distributions. No network or personal pay prediction."""
import gzip,json
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
@lru_cache(maxsize=1)
def data():
 with gzip.open(Path(__file__).with_name('career_wage_data.json.gz'),'rt') as f:return json.load(f)
def areas():return sorted(data()['areas'].values(),key=lambda a:(a['id']!='US',a['type'],a['title']))
def area(id):
 if id not in data()['areas']:raise HTTPException(422,'Choose a salary area from the list.')
 return data()['areas'][id]
def pay(code,id='US'):
 place=area(id);soc=code.split('.')[0];row=data()['wages'].get(id,{}).get(soc);national=data()['wages']['US'].get(soc)
 def decode(values):
  if values is None:return None
  annual=values[:5];hourly=values[5:];unit='year' if any(isinstance(v,(int,float)) or v=='#' for v in annual) else 'hour'
  chosen=annual if unit=='year' else hourly
  return {'unit':unit,'p10':chosen[0],'p25':chosen[1],'median':chosen[2],'p75':chosen[3],'p90':chosen[4],'annual':annual,'hourly':hourly}
 return {'area':place,'year':data()['metadata']['year'],'reference':data()['metadata']['reference'],'soc':soc,'occupation_title':data()['titles'].get(soc,''),'shared_specialty':not code.endswith('.00'),'values':decode(row),'national':decode(national),'source_url':data()['metadata']['url'],'markers':data()['metadata']['markers'],'reporting_threshold':data()['metadata'].get('reporting_threshold',{})}
def median(code,id):
 values=pay(code,id)['values'];v=values.get('median') if values else None
 return v if isinstance(v,(int,float)) else None

def sort_key(code,id):
 value=pay(code,id);v=value['values'];median=v['median'] if v else None
 # Bounds remain visibly labelled; use only their published floor for ordering.
 number=value['reporting_threshold'].get(v['unit']) if median=='#' else median
 return (not isinstance(number,(float,int)),v['unit']=='hour' if v else False,-number if isinstance(number,(float,int)) else 0)
