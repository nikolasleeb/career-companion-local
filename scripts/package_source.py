"""Export only the exact committed source; never accounts, caches or signing secrets."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
names=subprocess.check_output(['git','ls-tree','-r','--name-only',revision],cwd=root,text=True).splitlines()
blocked={'.git','node_modules','dist','local-data','local-secrets','xcuserdata','DerivedData','qa'}
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
 for name in names:
  path=Path(name)
  assert not blocked.intersection(path.parts) and path.name!='.env' and path.suffix not in ('.key','.pem','.p12','.sqlite','.sqlite3'),name
  data=subprocess.check_output(['git','show',revision+':'+name],cwd=root)
  archive.writestr('career-companion-'+revision[:12]+'/'+name,data)
with zipfile.ZipFile(output) as archive:assert archive.testzip() is None and len(archive.namelist())==len(names)
print(json.dumps({'file':output.name,'revision':revision,'files':len(names),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
