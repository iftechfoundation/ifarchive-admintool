import traceback
from http import cookies
import urllib.parse

from tinyapp.constants import PLAINTEXT, HTML
from tinyapp.excepts import HTTPError
from tinyapp.handler import ReqHandler, WrappedHandler

class TinyApp:
    def __init__(self, hanclasses, wrapall=None):
        self.handlers = []
        for pat, cla in hanclasses:
            han = cla(self, pat)
            if wrapall:
                for wrapper in wrapall:
                    han = WrappedHandler(han, wrapper)
            self.handlers.append(han)

    def application(self, environ, start_response):

        content_type = PLAINTEXT
        req = None
        
        try:
            req = TinyRequest(self, environ)
            ls = self.process(req)
            output = ''.join(ls)  # Gotta do this before looking at req
            status = req.status
            content_type = req.content_type
            boutput = output.encode()
        except HTTPError as ex:
            if not req:
                status = ex.status
                output = status + '\n\n' + ex.msg
                content_type = PLAINTEXT
            else:
                ls = ex.handle(req)
                output = ''.join(ls)  # Gotta do this before looking at req
                status = req.status
                content_type = req.content_type
            boutput = output.encode()
        except Exception as ex:
            status = '500 Internal Error'
            ls = traceback.format_exception(ex)
            output = status + '\n\n' + ''.join(ls)
            content_type = PLAINTEXT
            boutput = output.encode()
            if not environ.get('TinyAppSkipPrintErrors'):
                print(output)   # To Apache error log

        response_headers = [
            ('Content-Type', content_type),
            ('Content-Length', str(len(boutput)))
        ]
        if req and req.headers:
            response_headers.extend(req.headers)
        if req and len(req.newcookies):
            ls = str(req.newcookies).split('\n')
            for hdr in ls:
                key, _, val = hdr.strip().partition(':')
                response_headers.append( (key.strip(), val.strip()) )
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

    def test_dump(self, uri):
        env = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': uri,
            'REQUEST_URI': uri,
            'TinyAppSkipPrintErrors': 'True',
        }
        
        def start_response(status, headers):
            print(status)
            for key, val in headers:
                print(key+':', val)
                
        ls = self.application(env, start_response)
        val = b''.join(ls)
        print()
        print(val.decode())


class TinyRequest:
    def __init__(self, app, env):
        self.env = env
        self.app = app
        
        self.request_method = env.get('REQUEST_METHOD', '?')
        self.path_info = env.get('PATH_INFO', '')
        self.request_uri = env.get('REQUEST_URI', self.path_info)
        
        self.cookies = cookies.SimpleCookie()
        if 'HTTP_COOKIE' in env:
            try:
                self.cookies.load(env['HTTP_COOKIE'])
            except:
                pass
        self.newcookies = cookies.SimpleCookie()

        self.input = {}
        if 'wsgi.input' in env:
            try:
                val = env['wsgi.input'].read()
                if len(val):
                    self.input = urllib.parse.parse_qs(val.decode())
            except:
                pass
        # could check env['QUERY_STRING'] as well

        self._xsrf = None  # in case someone uses xsrf_cookie

        self.status = '200 OK'
        self.content_type = HTML
        self.headers = []

    def get_input_field(self, key):
        ls = self.input.get(key)
        if ls:
            return ls[0]
        raise KeyError(key)

    def set_status(self, val):
        self.status = val

    def set_content_type(self, val):
        self.content_type = val

    def add_header(self, key, val):
        self.headers.append( (key, val) )

    def set_cookie(self, key, val, httponly=False, secure=False, maxage=None):
        self.newcookies[key] = val
        if httponly:
            self.newcookies[key]['httponly'] = True
        if secure:
            self.newcookies[key]['secure'] = True
        if maxage is not None:
            self.newcookies[key]['max-age'] = maxage

