import sys
import time
import os
import re
import traceback

PLAINTEXT = 'text/plain'
HTML = 'text/html; charset=utf-8'

class TinyRequest:
    def __init__(self, app, env):
        self.env = env
        self.app = app
        
        self.request_method = env.get('REQUEST_METHOD', '?')
        self.path_info = env.get('PATH_INFO', '')
        self.request_uri = env.get('REQUEST_URI', self.path_info)

        ### environ.get('QUERY_STRING'), urllib.parse.parse_qs()

        self.status = '200 OK'
        self.content_type = HTML

    def set_status(self, val):
        self.status = val

    def set_content_type(self, val):
        self.content_type = val

class HTTPError(Exception):
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg
        
class TinyApp:
    def __init__(self, hanclasses):
        self.handlers = []
        for pat, cla in hanclasses:
            han = cla(self, pat)
            self.handlers.append(han)

    def application(self, environ, start_response):

        content_type = PLAINTEXT
        req = None
        
        try:
            req = TinyRequest(self, environ)
            ls = self.process(req)
            output = ''.join(ls)
            status = req.status
            content_type = req.content_type
            boutput = output.encode()
        except HTTPError as ex:
            status = ex.status
            output = status + '\n\n' + ex.msg
            content_type = PLAINTEXT
            boutput = output.encode()
        except Exception as ex:
            status = '500 Internal Error'
            ls = traceback.format_exception(ex)
            ls.insert(0, status+'\n\n')
            output = ''.join(ls)
            content_type = PLAINTEXT
            boutput = output.encode()

        response_headers = [
            ('Content-Type', content_type),
            ('Content-Length', str(len(boutput)))
        ]
        ### more headers from req
        start_response(status, response_headers)
        yield boutput

    def process(self, req):
        for han in self.handlers:
            match = han.pat.match(req.path_info)
            if match:
                break
        else:
            msg = 'Not found: %s' % (req.request_uri,)
            raise HTTPError('404 Not Found', msg)
        
        if req.request_method == 'GET':
            dofunc = han.do_get
        elif req.request_method == 'POST':
            dofunc = han.do_post
        elif req.request_method == 'HEAD':
            dofunc = han.do_head
        else:
            msg = 'Not allowed: %s, %s' % (req.request_method, req.request_uri,)
            raise HTTPError('405 Method Not Allowed', msg)

        return dofunc(req)

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
        yield '<html>Hello world...\n</html>'

class han_DebugDump(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
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
