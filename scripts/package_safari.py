"""Build a universal Developer ID Safari DMG without installing or changing permissions."""
import argparse,hashlib,json,os,shutil,subprocess,zipfile,tempfile,plistlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--identity',help='Developer ID Application identity name or SHA')
p.add_argument('--team')
p.add_argument('--notarized-app',help='An app already notarized and exported by Xcode Direct Distribution; produces a ZIP with the stapled app')
p.add_argument('--output',required=True)
p.add_argument('--notary-profile',help='Existing notarytool Keychain profile; credentials are never stored in this repository')
a=p.parse_args();root=Path(__file__).resolve().parents[1];out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
env={**os.environ,'DEVELOPER_DIR':os.environ.get('DEVELOPER_DIR','/Applications/Xcode.app/Contents/Developer')}
def run(*args,**kw):return subprocess.run(args,check=True,env=env,**kw)
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip(),'Commit the exact source before signing.'
with zipfile.ZipFile(root/'frontend/public/extensions/career-companion-safari.zip') as z:
 version=json.loads(z.read('manifest.json'))['version'];expected={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
if a.notarized_app:
 app=Path(a.notarized_app).resolve();extension=app/'Contents/PlugIns/Career Companion Extension.appex'
 for bundle,identifier in ((app,'com.austrich.careercompanion'),(extension,'com.austrich.careercompanion.Extension')):
  info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
  assert info['CFBundleIdentifier']==identifier and info['CFBundleShortVersionString']==version
  run('codesign','--verify','--strict','--verbose=2',str(bundle))
  signature=subprocess.run(['codesign','-dv','--verbose=4',str(bundle)],capture_output=True,text=True,check=True)
  assert 'Authority=Developer ID Application:' in signature.stderr
 for n,digest in expected.items():assert hashlib.sha256((extension/'Contents/Resources'/n).read_bytes()).hexdigest()==digest,n
 for binary in (app/'Contents/MacOS/Career Companion',extension/'Contents/MacOS/Career Companion Extension'):
  assert set(subprocess.check_output(['lipo','-archs',str(binary)],text=True).split())=={'arm64','x86_64'}
 run('xcrun','stapler','validate',str(app))
 run('spctl','--assess','--type','execute','--verbose=2',str(app))
 artifact=out/f'career-companion-safari-{version}-macos-universal.zip'
 run('ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(artifact))
 with tempfile.TemporaryDirectory(prefix='career-safari-extracted-') as temp:
  run('ditto','-x','-k',str(artifact),temp)
  extracted=Path(temp)/app.name
  run('codesign','--verify','--deep','--strict','--verbose=2',str(extracted))
  run('xcrun','stapler','validate',str(extracted))
  run('spctl','--assess','--type','execute','--verbose=2',str(extracted))
 receipt={'file':artifact.name,'artifact_type':'notarized_stapled_app_zip','notarization_scope':'contained_application','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'extension_version':version,'source_commit':revision,'architectures':['arm64','x86_64'],'signature_valid':True,'notarization_status':'Accepted','staple_valid':True,'gatekeeper_accepted':True,'archive_extraction_verified':True,'notarization_method':'Xcode Direct Distribution','installed':False,'provider_requests':0}
 (out/'safari-distribution-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2));raise SystemExit(0)
assert a.identity and a.team,'Provide --identity and --team when building, or --notarized-app for an Xcode export.'
project=root/'extensions/safari-xcode/Career Companion/Career Companion.xcodeproj'
build=out/'build'
with (out/'xcode-build.log').open('w') as log:
 run('xcodebuild','-project',str(project),'-scheme','Career Companion','-configuration','Release','-destination','generic/platform=macOS','-derivedDataPath',str(build),'ARCHS=arm64 x86_64','ONLY_ACTIVE_ARCH=NO','MACOSX_DEPLOYMENT_TARGET=12.0','CODE_SIGN_STYLE=Manual','CODE_SIGN_IDENTITY='+a.identity,'DEVELOPMENT_TEAM='+a.team,'ENABLE_HARDENED_RUNTIME=YES','CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO','MARKETING_VERSION='+version,'CURRENT_PROJECT_VERSION='+version.split('.')[-1],'build',stdout=log,stderr=subprocess.STDOUT)
app=build/'Build/Products/Release/Career Companion.app';extension=app/'Contents/PlugIns/Career Companion Extension.appex'
for bundle in (extension,app):run('codesign','--verify','--strict','--verbose=2',str(bundle))
resources=extension/'Contents/Resources'
for n,digest in expected.items():assert hashlib.sha256((resources/n).read_bytes()).hexdigest()==digest,n
for binary in (app/'Contents/MacOS/Career Companion',extension/'Contents/MacOS/Career Companion Extension'):
 archs=subprocess.check_output(['lipo','-archs',str(binary)],text=True).split();assert set(archs)=={'arm64','x86_64'},archs
notary_id=None
if a.notary_profile:
 archive=out/'safari-app-for-notarization.zip';run('ditto','-c','-k','--keepParent',str(app),str(archive))
 response=json.loads(subprocess.check_output(['xcrun','notarytool','submit',str(archive),'--keychain-profile',a.notary_profile,'--wait','--output-format','json'],env=env,text=True));(out/'app-notarization.json').write_text(json.dumps(response,indent=2))
 assert response['status']=='Accepted',response['status'];run('xcrun','stapler','staple',str(app));run('xcrun','stapler','validate',str(app))
folder=out/'dmg-root';folder.mkdir(exist_ok=True);shutil.copytree(app,folder/app.name,dirs_exist_ok=True)
applications=folder/'Applications'
if not applications.exists():applications.symlink_to('/Applications')
(folder/'INSTALL.txt').write_text('Drag Career Companion to Applications, open it, then enable the extension in Safari Settings. Pair with your Career Companion account explicitly. Installation never starts application filling.\n')
artifact=out/f'career-companion-safari-{version}-macos-universal.dmg'
run('hdiutil','create','-volname','Career Companion Safari','-srcfolder',str(folder),'-format','UDZO','-ov',str(artifact))
run('codesign','--force','--timestamp','--sign',a.identity,str(artifact));run('codesign','--verify','--strict',str(artifact))
if not a.notary_profile:
 print('Signed candidate prepared. RELEASE BLOCKED: configure an existing notarytool Keychain profile and rerun with --notary-profile. Candidate is not notarized or approved for publication.',flush=True);raise SystemExit(2)
response=json.loads(subprocess.check_output(['xcrun','notarytool','submit',str(artifact),'--keychain-profile',a.notary_profile,'--wait','--output-format','json'],env=env,text=True));(out/'dmg-notarization.json').write_text(json.dumps(response,indent=2))
assert response['status']=='Accepted',response['status'];run('xcrun','stapler','staple',str(artifact));run('xcrun','stapler','validate',str(artifact))
run('spctl','--assess','--type','execute','--verbose=2',str(app));run('spctl','--assess','--type','open','--context','context:primary-signature','--verbose=2',str(artifact))
receipt={'file':artifact.name,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'extension_version':version,'source_commit':revision,'architectures':['arm64','x86_64'],'signature_valid':True,'notarization_status':'Accepted','staple_valid':True,'gatekeeper_accepted':True,'installed':False,'provider_requests':0}
(out/'safari-distribution-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
