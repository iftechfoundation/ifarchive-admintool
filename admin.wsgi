import sys
import time
import os
import re

class TinyApp:
    def __init__(self, handlers):
        self.handlers = handlers

    def application(self, environ, start_response):
        request_method = environ.get('REQUEST_METHOD')
        path_info = environ.get('PATH_INFO')
        
        for han in self.handlers:
            if request_method != han.method:
                continue
            match = han.pat.match(path_info)
            if not match:
                continue
            status = '200 OK'
            ### environ.get('QUERY_STRING'), urllib.parse.parse_qs()
            output = han.handler(environ)
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
    def __init__(self, pat, handler, method='GET'):
        self.method = method
        self.pat = re.compile(pat)
        self.handler = handler

def uhan_Home(env):
    return 'Hello world...\n'

def uhan_DebugDump(env):
    ls = []
    for key, val in env.items():
        ls.append('%s: %s\n' % (key, val,))
    return ''.join(ls)


handlers = [
    ReqHandler('$', uhan_Home),
    ReqHandler('/debugdump$', uhan_DebugDump),
]

application = TinyApp(handlers).application
    
def xapplication(environ, start_response):
    status = '200 OK'
    output = 'Hello world!\n%s\n%s\ngetpid=%s\n' % (sys.version, time.ctime(), os.getpid())
    output += str(environ)
    boutput = output.encode()

    response_headers = [('Content-Type', 'text/plain'),
                        ('Content-Length', str(len(boutput)))]
    start_response(status, response_headers)

    yield boutput

