"""Bound streamed requests and expensive operations before application handlers run."""
import threading
from starlette.responses import JSONResponse

class BodyLimit(Exception):pass

def request_limit(path):
    if __import__('re').fullmatch(r'/api/interview-practice/sessions/[^/]+/voice',path):return 20*1024*1024
    if __import__('re').fullmatch(r'/api/applications/[^/]+/documents',path):return 11*1024*1024
    return {'/api/jobs/from-document':51*1024*1024,'/api/jobs/import-document':51*1024*1024,'/api/analyses/from-document':51*1024*1024,'/api/account/import':257*1024*1024,'/api/job-search/ai/examples':11*1024*1024,'/api/project-sources/upload':33*1024*1024,'/api/documents':11*1024*1024,'/api/transcripts/parse':11*1024*1024,'/api/certificates':11*1024*1024}.get(path,1024*1024)

class ResourceBoundary:
    def __init__(self,app):self.app=app;self.lock=threading.Lock();self.active=0;self.expensive=0
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path=scope['path'];costly=scope['method'] not in ('GET','HEAD','OPTIONS') or any(x in path for x in ('/export/','/preview','/pages/','/documents/'))
        with self.lock:
            reject=self.active>=16 or (costly and self.expensive>=3)
            if not reject:self.active+=1;self.expensive+=int(costly)
        if reject:return await JSONResponse({'detail':'Server is busy. Try again shortly.'},503,headers={'Retry-After':'5'})(scope,receive,send)
        count=0;started=False
        async def bounded_receive():
            nonlocal count
            message=await receive()
            if message['type']=='http.request':
                count+=len(message.get('body',b''))
                if count>request_limit(path):raise BodyLimit()
            return message
        async def tracked_send(message):
            nonlocal started
            if message['type']=='http.response.start':started=True
            await send(message)
        try:
            await self.app(scope,bounded_receive,tracked_send)
        except BodyLimit:
            if not started:await JSONResponse({'detail':'This request exceeds the size limit.'},413)(scope,receive,send)
        finally:
            with self.lock:self.active-=1;self.expensive-=int(costly)
