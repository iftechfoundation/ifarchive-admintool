import sys
import time
import os
import re

class TinyRequest:
    def __init__(self, app, env):
        self.env = env
        self.app = app
        
        self.request_method = env.get('REQUEST_METHOD', '?')
        self.path_info = env.get('PATH_INFO', '')
        self.request_uri = env.get('REQUEST_URI', self.path_info)

class TinyApp:
    def __init__(self, hanclasses):
        self.handlers = []
        for pat, cla in hanclasses:
            han = cla(self, pat)
            self.handlers.append(han)

    def application(self, environ, start_response):
        req = TinyRequest(self, environ)
        
        for han in self.handlers:
            match = han.pat.match(req.path_info)
            if not match:
                continue
            status = '200 OK'
            ### environ.get('QUERY_STRING'), urllib.parse.parse_qs()
            if req.request_method == 'GET':
                dofunc = han.do_get
            elif req.request_method == 'POST':
                dofunc = han.do_post
            elif req.request_method == 'HEAD':
                dofunc = han.do_head
            else:
                han = None
                status = '405 Method Not Allowed'
                output = 'Not allowed: %s, %s' % (req.request_method, req.request_uri,)
                break
            output = []
            for ln in dofunc(req):
                output.append(ln)
            output = ''.join(output)
            break
        else:
            han = None
            status = '404 Not Found'
            output = 'Not found: %s' % (req.request_uri,)
            
        boutput = output.encode()

        response_headers = [('Content-Type', 'text/plain'),
                            ('Content-Length', str(len(boutput)))]
        start_response(status, response_headers)
        yield boutput

class ReqHandler:
    def __init__(self, app, pat):
        self.app = app
        
        if not pat.endswith('$'):
            pat += '$'
        self.pat = re.compile(pat)

    def do_get(self, req):
        raise NotImplementedError('GET not implemented')

    def do_post(self, req):
        raise NotImplementedError('POST not implemented')

    def do_head(self, req):
        for val in self.do_get(req):
            # Accumulate total size?
            pass
        yield ''

class han_Home(ReqHandler):
    def do_get(self, req):
        yield 'Hello world...\n'

class han_DebugDump(ReqHandler):
    def do_get(self, req):
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)

handlers = [
    ('', han_Home),
    ('/debugdump', han_DebugDump),
]

application = TinyApp(handlers).application
