import re

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

class WrappedHandler:
    def __init__(self, han, wrapper):
        self.app = han.app
        self.pat = han.pat

        self.do_head = han.do_head
        self.do_get = lambda req: wrapper(req, han.do_get)
        self.do_post = lambda req: wrapper(req, han.do_post)

def before(wrapper):
    def func(han):
        def subfunc(self, req):
            return wrapper(req, lambda req2: han(self, req2))
        return subfunc
    return func
