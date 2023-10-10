from tinyapp.constants import PLAINTEXT

class HTTPError(Exception):
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg

    def do_error(self, req):
        req.set_content_type(PLAINTEXT)
        yield '%s\n\n' % (self.status,)
        yield self.msg
        
class HTTPRedirectPost(Exception):
    def __init__(self, url):
        self.url = url
