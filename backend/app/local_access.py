"""Accept only local browser hosts; never trust forwarding headers."""
from urllib.parse import urlsplit
from starlette.responses import JSONResponse


class LocalAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k, v in headers if k.lower() == b'host']
        forwarded = any(k.lower() in (b'forwarded', b'via', b'x-real-ip') or k.lower().startswith(b'x-forwarded-') for k, _ in headers)
        valid = False
        if len(hosts) == 1:
            try:
                host = urlsplit('http://' + hosts[0])
                valid = (host.hostname in ('localhost', '127.0.0.1', '::1')
                         and not host.username and not host.password
                         and not host.path and not host.query and not host.fragment
                         and (host.port is None or 1 <= host.port <= 65535))
            except ValueError:
                pass
        if not valid or forwarded:
            return await JSONResponse({'detail': 'This edition accepts localhost access only.'}, 403)(scope, receive, send)
        await self.app(scope, receive, send)
