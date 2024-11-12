from tinyapp.constants import PLAINTEXT

# Exceptions which may be raised by request handlers.

class HTTPRawResponse(Exception):
    """This exception bypasses the normal app handler sequence that
    converts string output to bytes. If you raise this, you want
    to set the status, headers, and response bytes directly.
    (You are also responsible for setting Content-Length!) The
    outiter argument should be an iterator of byteses.
    """
    def __init__(self, status, headers, outiter):
        self.status = status
        self.headers = headers
        self.outiter = outiter

class HTTPError(Exception):
    """Abort the request and return an HTTP error instead.
    """
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg

    def handle(self, req):
        """Set up the request response info (status and output).
        """
        req.set_status(self.status)
        return self.do_error(req)

    def do_error(self, req):
        """By default, the user-visible error page is just a plaintext
        message line. If we want a fancier (HTML) error response, we
        could subclass HTTPError and customize this method.
        """
        req.set_content_type(PLAINTEXT)
        yield '%s\n\n' % (self.status,)
        yield self.msg
        
class HTTPRedirectPost(HTTPError):
    """Abort the request and return an HTTP redirect to another URL
    (or the same URL if you like). This is normally used when a POST
    action completes and wants to return the regular GET form of the
    page.
    """
    def __init__(self, url):
        self.status = '303 See Other'
        self.msg = url
        self.url = url

    def handle(self, req):
        """Set up the request response info (status and output).
        """
        req.set_status(self.status)
        req.add_header('Location', self.url)
        return self.do_error(req)
        
