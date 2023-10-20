import re

class ReqHandler:
    """Base class for a URL handler.
    """
    def __init__(self, app, pat):
        self.app = app
        
        if not pat.endswith('$'):
            pat += '$'
        self.pat = re.compile(pat)

    def do_get(self, req):
        """Handle GET.
        """
        raise NotImplementedError('%s: GET not implemented' % (self.__class__.__name__,))

    def do_post(self, req):
        """Handle POST.
        """
        raise NotImplementedError('%s: POST not implemented' % (self.__class__.__name__,))

    def do_head(self, req):
        """Handle HEAD.
        This defaults to doing a GET but then responding with no data.
        Not really ideal, since we wind up doing all the database work
        (or whatever).
        """
        for val in self.do_get(req):
            # Accumulate total size?
            pass
        yield ''

class WrappedHandler:
    """A class that wraps a ReqHandler, applying a request filter to all
    GET and POST requests.
    (We don't have to filter HEAD requests because those will invoke
    GET anyway.)
    """
    def __init__(self, han, wrapper):
        self.app = han.app
        self.pat = han.pat

        self.do_head = han.do_head
        self.do_get = lambda req: wrapper(req, han.do_get)
        self.do_post = lambda req: wrapper(req, han.do_post)

def before(wrapper):
    """Handler decorator which applies a filter. Use within a Handler:

      @before(wrapper)
      def do_get(self, req):
        ...
    """
    def func(han):
        def subfunc(self, req):
            return wrapper(req, lambda req2: han(self, req2))
        return subfunc
    return func

def beforeall(wrapper):
    """Handler class decorator which applies a filter. Use on the entire
    class:

      @beforeall(wrapper)
      class han_Foo(ReqHandler):
        ...
    """
    def func(cla):
        def subfunc(app, pat):
            inst = cla(app, pat)
            return WrappedHandler(inst, wrapper)
        return subfunc
    return func

