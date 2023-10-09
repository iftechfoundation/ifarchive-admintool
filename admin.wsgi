import sys
import time
import os

from tinyapp import TinyApp, ReqHandler
from tinyapp import PLAINTEXT

class han_Home(ReqHandler):
    def do_get(self, req):
        yield '<html>Hello world...\n</html>'

class han_DebugDump(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)

handlers = [
    ('', han_Home),
    ('/debugdump', han_DebugDump),
]

application = TinyApp(handlers).application

if __name__ == '__main__':
    uri = ''
    if len(sys.argv) > 1:
        uri = sys.argv[1]
    application.__self__.test_dump(uri)
