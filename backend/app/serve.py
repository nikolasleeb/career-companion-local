"""Start the native server on loopback, or inside the supplied Docker network."""
import os
import uvicorn


if __name__ == '__main__':
    # Docker publishes this internal listener only to the host's loopback address.
    host = '0.0.0.0' if os.path.isfile('/.dockerenv') else '127.0.0.1'
    uvicorn.run('app.main:app', host=host, port=3000, workers=1,
                access_log=False, proxy_headers=False)
