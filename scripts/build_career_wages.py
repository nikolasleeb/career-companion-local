"""Build reproducible wage data from official May 2025 BLS national/state/metro ZIPs.
Usage: python scripts/build_career_wages.py NATIONAL.zip STATE.zip METRO.zip
Download links: https://www.bls.gov/oes/tables.htm. No project/user data is read.
"""
import gzip,hashlib,io,json,re,sys,xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
FIELDS=[p+s for p in ('A_','H_') for s in ('PCT10','PCT25','MEDIAN','PCT75','PCT90')]
def rows(raw):
 with ZipFile(io.BytesIO(raw)) as book:
  strings=[''.join(el.itertext()) for el in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si',NS)] if 'xl/sharedStrings.xml' in book.namelist() else []
  header=None
  for _,row in ET.iterparse(book.open('xl/worksheets/sheet1.xml'),events=('end',)):
   if row.tag!='{'+NS['s']+'}row':continue
   values={}
   for cell in row:
    col=re.match('[A-Z]+',cell.get('r','')).group();v=cell.find('s:v',NS);text=v.text if v is not None else ''.join(cell.itertext());values[col]=strings[int(text)] if cell.get('t')=='s' else text
   if header is None:header=values
   else:yield {name:values.get(col,'') for col,name in header.items()}
   row.clear()
def build(paths):
 areas={};wages={};titles={};sources=[]
 for short,path in zip(('nat','st','ma'),paths):
  raw=Path(path).read_bytes();sources.append({'url':'https://www.bls.gov/oes/special-requests/oesm25'+short+'.zip','sha256':hashlib.sha256(raw).hexdigest()})
  with ZipFile(io.BytesIO(raw)) as archive:
   for name in sorted(archive.namelist()):
    if not name.endswith('.xlsx') or 'file_descriptions' in name:continue
    for row in rows(archive.read(name)):
     if row.get('NAICS')!='000000' or row.get('OWN_CODE')!='1235' or not re.fullmatch(r'\d{2}-\d{4}',row.get('OCC_CODE','')):continue
     area='US' if short=='nat' else ('state:' if short=='st' else 'metro:' if row['AREA_TYPE']=='4' else 'nonmetro:')+row['AREA']
     areas[area]={'id':area,'title':'United States' if short=='nat' else row['AREA_TITLE'],'type':area.split(':')[0] if ':' in area else 'national','state':row.get('PRIM_STATE','')}
     values=[]
     for field in FIELDS:
      value=row.get(field,'')
      try:value=round(float(value),2)
      except (ValueError,TypeError):value=value or None
      values.append(value)
     wages.setdefault(area,{})[row['OCC_CODE']]=values;titles[row['OCC_CODE']]=row['OCC_TITLE']
 result={'metadata':{'year':2025,'reference':'May 2025','source':'BLS Occupational Employment and Wage Statistics','url':'https://www.bls.gov/oes/tables.htm','sources':sources,'fields':FIELDS,'reporting_threshold':{'year':239200,'hour':115},'threshold_source':'https://www.bls.gov/oes/methods_25.pdf','markers':{'*':'Not released by BLS','**':'Annual or hourly estimate not available','#':'At or above the BLS reporting threshold'}},'areas':areas,'titles':titles,'wages':wages}
 target=Path(__file__).resolve().parents[1]/'backend/app/career_wage_data.json.gz'
 with target.open('wb') as f:
  with gzip.GzipFile(filename='',fileobj=f,mode='wb',mtime=0) as z:z.write(json.dumps(result,sort_keys=True,separators=(',',':')).encode())
 print(json.dumps({'areas':len(areas),'rows':sum(map(len,wages.values())),'bytes':target.stat().st_size,'sources':sources},indent=2))
if __name__=='__main__':build(sys.argv[1:])
