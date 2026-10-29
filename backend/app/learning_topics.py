"""Concrete learning vocabulary shared by resource discovery and saved milestones."""
import re
from functools import lru_cache
from . import career_evidence
GENERIC={'education','projects','project','certification','certifications','credentials','training','engineering','science','research','career exploration','occupations','it and systems','data engineering','software engineering','public service','nursing','healthcare administration','management consulting','marketing','finance','accounting','design','journalism'}
# Broad disciplines remain filters; these labels describe things a person can practice.
CURATED={
 'Python':[], 'SQL':[], 'Statistics':['statistical analysis','stats'], 'Power BI':['dashboards'], 'Git':['version control'], 'Networking':['computer networking','network troubleshooting'], 'Linux':['command line'], 'Troubleshooting':[], 'AWS':['cloud infrastructure','aws infrastructure'], 'Azure':[], 'HTML':[], 'CSS':[], 'JavaScript':[], 'Excel':[], 'Tableau':[], 'Spark':[], 'R':[],
 'Business analysis':['business problem analysis'], 'Market research':[], 'Bookkeeping':[], 'Financial analysis':[], 'Project management':[], 'CAD':['computer aided design','autodesk'], 'Quality control analysis':['quality assurance'], 'Public health methods':[], 'Clinical research methods':['clinical research'], 'Operations analysis':[], 'Lesson planning':['instructional planning'], 'Writing':[], 'Interface design':['figma'], 'Reporting and interviewing':[], 'Experimental design':[], 'Research methods':['literature review','research methodology'], 'Environmental data analysis':[], 'PostgreSQL':[], 'Data modeling':[], 'Data validation':[], 'ETL':['extract transform load'], 'Communication':[], 'Portfolio development':[], 'Patient communication':[], 'Process improvement':[], 'Human resources practices':[],
}
RESOURCE_TOPICS={
 'sql_lemur':['SQL'], 'sql_bolt':['SQL'], 'python':['Python'], 'stats':['Statistics'], 'powerbi':['Power BI'], 'git':['Git'], 'net':['Networking'], 'linux':['Linux'], 'support':['Troubleshooting'],
 'explore':[], 'practice':['Portfolio development','Communication'], 'cert-choice':[], 'sql':['SQL'], 'cloud':['AWS'], 'microsoft':['Azure','Power BI','Excel'], 'it':['Networking','Troubleshooting'], 'software':['HTML','CSS','JavaScript'], 'consulting':['Business analysis'], 'marketing':['Market research'], 'accounting':['Bookkeeping'], 'finance':['Financial analysis'], 'operations':['Project management'], 'engineering':[], 'engineering-license':[], 'cad':['CAD'], 'nursing':['Patient communication'], 'public-health':['Public health methods'], 'clinical':['Clinical research methods','Research methods'], 'health-admin':['Operations analysis'], 'teaching':['Lesson planning'], 'public-service':[], 'writing':['Writing'], 'design':['Interface design'], 'journalism':['Reporting and interviewing','Writing'], 'science':['Experimental design'], 'research-methods':['Research methods'], 'environment':['Environmental data analysis'], 'networking':['Communication'], 'data-engineering':['PostgreSQL','SQL','Data modeling'], 'cfa':['Financial analysis'], 'cpa':['Bookkeeping'], 'marketing-cert':['Market research'], 'nursing-cert':[], 'lab-cert':[], 'quality-cert':['Quality control analysis'], 'hr-cert':['Human resources practices'], 'google-cert':['Project management'],
 'codecademy-python':['Python'],'codecademy-sql':['SQL'],'datacamp-python':['Python'],'datacamp-sql':['SQL'],
}
def key(label):return career_evidence.canonical(label)
def clean(values,limit=30):
 result=[];seen=set()
 for value in values:
  if not isinstance(value,str):continue
  value=' '.join(value.split())[:150];canonical=key(value)
  if not canonical or canonical in GENERIC or canonical in seen:continue
  seen.add(canonical);result.append(value)
  if len(result)==limit:break
 return result
@lru_cache(maxsize=1)
def vocabulary():
 from . import career_explorer
 rows={key(label):{'label':label,'aliases':set([label,*aliases,*career_evidence.ALIASES.get(key(label),[])])} for label,aliases in CURATED.items()}
 for occupation in career_explorer.OCCUPATIONS.values():
  for item in occupation['skills']:
   k=key(item['name'])
   if k not in GENERIC:rows.setdefault(k,{'label':item['name'],'aliases':{item['name']}})
 return rows

def mentions(text):
 from .role_catalog import phrase
 return [row['label'] for row in vocabulary().values() if any(phrase(alias,text) for alias in row['aliases'])]
def milestone(action):
 if 'learning_topics' in action and action['learning_topics'] is not None:return clean(action['learning_topics'],5)
 return clean(mentions(' '.join([action.get('title',''),*action.get('steps',[])])),5)
def labels(values):
 return [vocabulary().get(key(v),{'label':v})['label'] for v in clean(values)]
