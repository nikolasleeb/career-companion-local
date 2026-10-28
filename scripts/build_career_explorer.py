"""Build reviewed public occupation data; never execute code from the input ZIP.

Usage: python scripts/build_career_explorer.py TEAMMATE_SOURCE_ZIP
The compact BLS snapshot covers 378 college-preparation occupations. Other
occupations retain O*NET descriptions and skills, with missing outlook explicit.
"""
import csv,hashlib,io,json,sys
from pathlib import Path
from zipfile import ZipFile

def build(path):
 with ZipFile(path) as z:
  prefix='career-companion-local/'
  def data(name):return json.loads(z.read(prefix+'backend/app/'+name))
  def rows(name):return csv.DictReader(io.StringIO(z.read(prefix+'raw-data/onet-raw/'+name).decode('utf-8-sig')))
  source=data('onet_snapshot.json');titles=data('onet_titles.json')
  occupations={r['O*NET-SOC Code']:{'title':r['Title'],'description':r['Description'],'skills':[],'technologies':[]} for r in rows('occupation_data.csv')}
  for code,o in occupations.items():
   _,zone=source['catalog'][code];old=source['occupations'].get(code,{})
   o.update(job_zone=zone,related=old.get('related',[]),median_wage=old.get('wage'),wage_year=old.get('wage_year',''),wage_note=old.get('wage_note',''),growth=old.get('growth'),openings=old.get('openings'),growth_note=old.get('growth_note',''),sectors={source['sectors'][int(k)]['naics']:v for k,v in old.get('sectors',{}).items()},titles=titles.get(code,[]))
  for file in ('essential_skills.csv','transferable_skills.csv'):
   for r in rows(file):
    if r['O*NET-SOC Code'] in occupations and r['Scale ID']=='IM' and r.get('Recommend Suppress')!='Y':
     occupations[r['O*NET-SOC Code']]['skills'].append({'name':r['Element Name'],'importance':float(r['Data Value'])})
  for r in rows('software_skills.csv'):
   if r['O*NET-SOC Code'] in occupations:
    occupations[r['O*NET-SOC Code']]['technologies'].append({'name':r['Workplace Example'],'category':r['Element Name'],'hot':r['Hot Technology']=='Y','in_demand':r['In Demand']=='Y'})
  for o in occupations.values():o['related']=[]
  for r in rows('related_occupations.csv'):
   if r['O*NET-SOC Code'] in occupations and r['Relatedness Tier'] in ('Primary-Short','Primary-Long') and r['Related O*NET-SOC Code'] in occupations:occupations[r['O*NET-SOC Code']]['related'].append(r['Related O*NET-SOC Code'])
  for o in occupations.values():
   o['skills'].sort(key=lambda x:(-x['importance'],x['name']))
   o['technologies']=sorted({t['name']:t for t in o['technologies']}.values(),key=lambda t:(-t['in_demand'],-t['hot'],t['name']))[:40]
  meta={k:source[k] for k in ('version','attribution','source_url','crosswalk_url','license_url','wage_source','wage_source_url','growth_average','growth_period','growth_source','growth_source_url','sector_source','sector_source_url')}
  meta.update(snapshot_date='2026-10-27',outlook_coverage=378,archive_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
  result={'metadata':meta,'sectors':source['sectors'],'programs':source['programs'],'program_links':source['program_links'],'occupations':occupations}
  target=Path(__file__).resolve().parents[1]/'backend/app/career_explorer_data.json'
  target.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
  print(f'Built {len(occupations)} occupations; {sum(o["growth"] is not None for o in occupations.values())} with growth data. No keys or network requests used.')

if __name__=='__main__':build(sys.argv[1])
