import sys
import traceback
import logging
from http import cookies
import urllib.parse

from tinyapp.constants import PLAINTEXT, HTML
from tinyapp.excepts import HTTPError, HTTPRawResponse
from tinyapp.handler import ReqHandler, WrappedHandler

"""TinyApp: A very simple HTTP web framework that lives within a WSGI
application.

To make a TinyApp application, create a TinyApp with a list of *handlers*:

  appinstance = TinyApp([
    ('', han_Home),
    ('/hello', han_Hello),
  ])
  application = appinstance.application

The application global is WSGI's entry point.

The handlers (han_Home, han_Hello in the above example) should be
ReqHandler class objects. An incoming request for
  http://server/wsgiapp/hello
...will be directed to the do_get() method of han_Hello. That method
should yield some strings, which will become the request response. That's
pretty much the whole story.

To fancy up the story, we can apply *request filters*. Filters can be
applied to specific methods (do_get() or do_post()), or to an entire
handler, or globally to all handlers in the app.

When a request comes in, every applicable filter is called before
the handler method is called. The filter function should either

- Modify the request by adding some information for later handlers;
- Modify the request by setting response headers or cookies; or
- Abort by throwing an exception.
"""

class TinyApp:
    """Base class for the WSGI application handler.
    Initialize this with the list of URL handlers (RequestHandler classes).
    The wrapall argument, if supplied, should be a list of request filters
    to apply to every handler in the app.
    Pass secure_site=True if you know the app will only be used on HTTPS.
    This gets you more secure cookie settings.
    """
    def __init__(self, hanclasses, wrapall=None, secure_site=False):
        self.handlers = []
        for pat, cla in hanclasses:
            han = cla(self, pat)
            if wrapall:
                for wrapper in reversed(wrapall):
                    han = WrappedHandler(han, wrapper)
            self.handlers.append(han)

        self.secure_site = secure_site

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
            # Set up the request...
            req = self.create_request(environ)
            # Process it and call a handler...
            ls = self.process(req)
            if ls is None:
                raise Exception('handler returned None')
            # Run through the handler's output. Note that "ls" isn't
            # necessarily an array; it could be any iterator.
            output = ''.join(ls)  # Gotta do this before looking at req
            status = req.status
            content_type = req.content_type
            boutput = output.encode()
        except HTTPRawResponse as ex:
            # Special case: the handler wants to produce the complete
            # response without our self. Send it forth and exit.
            start_response(ex.status, ex.headers)
            for val in ex.outiter:
                yield val
            return
        except HTTPError as ex:
            # The handler threw an exception representing a particular
            # HTTP error.
            if not req:
                # Really, req should exist if we got this far. But we'll
                # cover the case where it doesn't.
                status = ex.status
                output = status + '\n\n' + ex.msg
                content_type = PLAINTEXT
            else:
                # Let the exception set up the request response info.
                ls = ex.handle(req)
                output = ''.join(ls)  # Gotta do this before looking at req
                status = req.status
                content_type = req.content_type
            boutput = output.encode()
        except Exception as ex:
            # An unforeseen exception occurred. By ancient tradition we
            # return an HTTP 500 error and show the traceback.
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

        # Complete the request by the usual path. The complete bytes output
        # is now in boutput, and any output headers have been stashed in the
        # request.
        
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
                req.match = match
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
        """Shortcut for logging at INFO level."""
        if not req:
            logging.info(msg, *args)
        else:
            val = req.lognote()
            logging.info('%s: '+msg, val, *args)

    def logwarning(self, req, msg, *args):
        """Shortcut for logging at WARNING level."""
        if not req:
            logging.warning(msg, *args)
        else:
            val = req.lognote()
            logging.warning('%s: '+msg, val, *args)

    def logerror(self, req, msg, *args):
        """Shortcut for logging at ERROR level."""
        if not req:
            logging.error(msg, *args)
        else:
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

        # GET or POST.
        self.request_method = env.get('REQUEST_METHOD', '?')
        # The path part of the request URL, after the app root.
        self.path_info = env.get('PATH_INFO', '')
        # The full request part of the URL. This is used only for
        # error reporting.
        self.request_uri = env.get('REQUEST_URI', self.path_info)

        # Incoming cookies.
        self.cookies = cookies.SimpleCookie()
        if 'HTTP_COOKIE' in env:
            try:
                self.cookies.load(env['HTTP_COOKIE'])
            except:
                pass
        # Outgoing cookies set by request handlers.
        self.newcookies = cookies.SimpleCookie()

        # Query string inputs.
        self.query = {}
        try:
            val = env.get('QUERY_STRING')
            if val:
                self.query = urllib.parse.parse_qs(val)
        except:
            pass
        
        # Form fields in a POST request. (Note that we store these
        # separately from query inputs.
        self.input = {}
        if 'wsgi.input' in env:
            try:
                val = env['wsgi.input'].read()
                if len(val):
                    self.input = urllib.parse.parse_qs(val.decode())
            except:
                pass

        # The handler's regex match on PATH_INFO.
        self.match = None
        
        self._xsrf = None  # in case someone uses xsrf_cookie

        # Set up a default response.
        self.status = '200 OK'
        self.content_type = HTML
        self.headers = []

    def lognote(self):
        """A string which will appear in any log line generated by this
        request. Subclasses can override this to be more interesting.
        """
        return 'req'
    
    def loginfo(self, msg, *args):
        """Shortcut for logging at INFO level."""
        self.app.loginfo(self, msg, *args)

    def logwarning(self, msg, *args):
        """Shortcut for logging at WARNING level."""
        self.app.logwarning(self, msg, *args)

    def logerror(self, msg, *args):
        """Shortcut for logging at ERROR level."""
        self.app.logerror(self, msg, *args)

    def get_query_field(self, key, default=None):
        """Get one field in the QUERY_STRING.
        """
        ls = self.query.get(key)
        if ls:
            return ls[0]
        return default

    def get_input_field(self, key, default=None):
        """Get one form field in a POST request.
        """
        ls = self.input.get(key)
        if ls:
            return ls[0]
        return default

    def set_status(self, val):
        """Set the response HTTP status.
        """
        self.status = val

    def set_content_type(self, val):
        """Set the response HTTP content type.
        """
        self.content_type = val

    def add_header(self, key, val):
        """Add a response HTTP header.
        """
        self.headers.append( (key, val) )

    def set_cookie(self, key, val, path='/', httponly=False, maxage=None):
        """Add a response HTTP cookie.
        Path defaults to "/"; you can set it to None if you really don't
        want a path attribute. (Turns out the "__Host-" cookie prefix
        requires an explicit path="/" -- you're not supposed to rely on
        the default.)
        """
        self.newcookies[key] = val
        if path:
            self.newcookies[key]['path'] = path
        if httponly:
            self.newcookies[key]['httponly'] = True
        if maxage is not None:
            self.newcookies[key]['max-age'] = maxage
        # Set this flag on HTTPS-only sites.
        if self.app.secure_site:
            # It would be nice to support SameSite=Strict, but that requires Py3.8.
            #self.newcookies[key]['samesite'] = 'Strict'
            self.newcookies[key]['secure'] = True

