import sys
import traceback
import logging
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
                for wrapper in reversed(wrapall):
                    han = WrappedHandler(han, wrapper)
            self.handlers.append(han)

    def application(self, environ, start_response):
        """The WSGI application handler. This conforms to the WSGI
        protocol:
        - The arguments are the environment map and a start_response()
          handler. start_response() must be called, passing HTTP status
          and headers, to kick off the response.
        - Returns an iterable of bytes objects, perhaps by yielding them.
          (In fact this always yields exactly one bytes object, but the
          protocol permits any number.)
        """

        content_type = PLAINTEXT
        req = None
        
        try:
            req = self.create_request(environ)
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
            exinfo = sys.exc_info()  ### In Py3.10, we could skip this and just do traceback.format_exception(ex)
            ls = traceback.format_exception(*exinfo)
            if req:
                exfrom = '%s, %s %s' % (req.lognote(), req.request_method, req.request_uri,)
            else:
                exfrom = '(no request)'
            output = '%s (%s)\n\n%s' % (status, exfrom, ''.join(ls))
            content_type = PLAINTEXT
            boutput = output.encode()
            if not environ.get('TinyAppSkipPrintErrors'):
                print(output)   # To Apache error log
                logging.exception('Caught exception: %s', exfrom)  # To admin log

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

    def create_request(self, environ):
        """Create a request object.
        This can be overridden by the app to return a subclass of
        TinyRequest.
        """
        return TinyRequest(self, environ)

    def process(self, req):
        """Process the request.
        Returns an iterable of byteses (perhaps by yielding them).
        """
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

    def loginfo(self, req, msg, *args):
        val = req.lognote()
        logging.info('%s: '+msg, val, *args)

    def logwarning(self, req, msg, *args):
        val = req.lognote()
        logging.warning('%s: '+msg, val, *args)

    def logerror(self, req, msg, *args):
        val = req.lognote()
        logging.error('%s: '+msg, val, *args)

    def test_dump(self, uri):
        """Generate the page for the given URI and print it to stdout.
        """
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
    """A request object. This contains everything known about a given
    request. We also accumulate response stuff here as the request
    is handled.
    """
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

    def lognote(self):
        """A string which will appear in any log line generated by this
        request. Subclasses can override this to be more interesting.
        """
        return 'req'
    
    def loginfo(self, msg, *args):
        self.app.loginfo(self, msg, *args)

    def logwarning(self, msg, *args):
        self.app.logwarning(self, msg, *args)

    def logerror(self, msg, *args):
        self.app.logerror(self, msg, *args)

    def get_input_field(self, key):
        ls = self.input.get(key)
        if ls:
            return ls[0]
        return None

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

