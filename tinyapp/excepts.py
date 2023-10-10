from tinyapp.constants import PLAINTEXT

class HTTPError(Exception):
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg

    def handle(self, req):
        req.set_status(self.status)
        return self.do_error(req)

    def do_error(self, req):
        req.set_content_type(PLAINTEXT)
        yield '%s\n\n' % (self.status,)
        yield self.msg
        
class HTTPRedirectPost(HTTPError):
    def __init__(self, url):
        self.status = '303 See Other'
        self.msg = url
        self.url = url

    def handle(self, req):
        req.set_status(self.status)
        req.set_header('Location', self.url)
        return self.do_error(req)
        
