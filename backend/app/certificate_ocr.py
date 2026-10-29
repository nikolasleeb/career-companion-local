"""Bounded local OCR for private certificates; no provider or URL requests."""
import io,os,shutil,subprocess,tempfile,threading,time
from pathlib import Path
from PIL import Image,ImageOps

_slots=threading.BoundedSemaphore(2)

def extract(raw,mime,page_numbers=(1,)):
    warnings=[];pages=[];incomplete=False
    executable=shutil.which('tesseract');renderer=shutil.which('pdftoppm')
    if not executable or mime=='application/pdf' and not renderer:
        return {'pages':[],'incomplete':True,'warnings':['Local OCR is unavailable in this installation. Enter details manually or use a text-based PDF.']}
    if not _slots.acquire(timeout=1):
        return {'pages':[],'incomplete':True,'warnings':['Local certificate processing is busy. Retry extraction when it finishes.']}
    try:
        deadline=time.monotonic()+90;characters_left=60000
        with tempfile.TemporaryDirectory(prefix='career-certificate-') as folder:
            root=Path(folder);image_path=root/'page.png';source=root/'source.pdf'
            env={'PATH':os.defpath,'LANG':'C.UTF-8','HOME':folder,'OMP_THREAD_LIMIT':'1'}
            if mime=='application/pdf':source.write_bytes(raw)
            else:
                try:
                    with Image.open(io.BytesIO(raw)) as original:
                        if original.format not in ('PNG','JPEG') or original.width*original.height>40_000_000:raise ValueError()
                        original.thumbnail((3500,3500))
                        image=ImageOps.exif_transpose(original).convert('RGBA')
                        background=Image.new('RGBA',image.size,'white');background.alpha_composite(image)
                        image=background.convert('L');image.thumbnail((3500,3500))
                        if max(image.size)<1800:image=image.resize(tuple(max(1,round(v*1800/max(image.size))) for v in image.size))
                        image.save(image_path)
                except Exception:
                    return {'pages':[],'incomplete':True,'warnings':['The certificate image could not be read. Try a clear PNG/JPG or enter details manually.']}
            for number in list(page_numbers)[:30]:
                remaining=deadline-time.monotonic()
                if remaining<1:
                    incomplete=True;warnings.append('Local OCR reached its processing limit. Completed pages are retained; review remaining pages manually.');break
                try:
                    if mime=='application/pdf':
                        subprocess.run([renderer,'-f',str(number),'-l',str(number),'-singlefile','-scale-to','3000','-png',str(source),str(root/'page')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=min(15,remaining),env=env)
                    remaining=deadline-time.monotonic()
                    if remaining<1:raise subprocess.TimeoutExpired('local OCR',90)
                    result=subprocess.run([executable,str(image_path),'stdout','-l','eng','--psm','3'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,timeout=min(20,remaining),env=env)
                    text=result.stdout.decode('utf-8','replace')[:min(20000,characters_left)];characters_left-=len(text)
                    pages.append((number,[line.strip() for line in text.splitlines() if line.strip()]))
                    if characters_left<=0:
                        incomplete=True;warnings.append('OCR text reached its 60,000-character limit. Completed text is retained.');break
                except (OSError,subprocess.SubprocessError):
                    incomplete=True;warnings.append('OCR could not finish page '+str(number)+'. Retry with a clearer file or enter its details manually.')
            return {'pages':pages,'incomplete':incomplete,'warnings':warnings}
    finally:_slots.release()
