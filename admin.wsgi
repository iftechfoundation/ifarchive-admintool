import sys
import time
import os
import re

class TinyApp:
    def __init__(self, handlers):
        self.handlers = handlers
        for han in self.handlers:
            han.setapp(self)

    def application(self, environ, start_response):
        request_method = environ.get('REQUEST_METHOD')
        path_info = environ.get('PATH_INFO')
        
        for han in self.handlers:
            match = han.pat.match(path_info)
            if not match:
                continue
            status = '200 OK'
            ### environ.get('QUERY_STRING'), urllib.parse.parse_qs()
            if request_method == 'GET':
                dofunc = han.do_get
            elif request_method == 'POST':
                dofunc = han.do_post
            elif request_method == 'HEAD':
                dofunc = han.do_head
            else:
                han = None
                status = '405 Method Not Allowed'
                val = environ.get('REQUEST_URI', path_info)
                output = 'Not allowed: %s, %s' % (request_method, val,)
                break
            output = []
            for ln in dofunc(environ):
                output.append(ln)
            output = ''.join(output)
            break
        else:
            han = None
            status = '404 Not Found'
            val = environ.get('REQUEST_URI', path_info)
            output = 'Not found: %s' % (val,)
            
        boutput = output.encode()

        response_headers = [('Content-Type', 'text/plain'),
                            ('Content-Length', str(len(boutput)))]
        start_response(status, response_headers)
        yield boutput

class ReqHandler:
    def __init__(self, pat):
        self.app = None
        
        if not pat.endswith('$'):
            pat += '$'
        self.pat = re.compile(pat)

    def setapp(self, app):
        self.app = app

    def do_get(self, env):
        raise NotImplementedError('GET not implemented')

    def do_post(self, env):
        raise NotImplementedError('GET not implemented')

    def do_head(self, env):
        raise NotImplementedError('GET not implemented')

class han_Home(ReqHandler):
    def do_get(self, env):
        yield 'Hello world...\n'

class han_DebugDump(ReqHandler):
    def do_get(self, env):
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in env.items():
            yield '  %s: %s\n' % (key, val,)

handlers = [
    han_Home(''),
    han_DebugDump('/debugdump'),
]

application = TinyApp(handlers).application
