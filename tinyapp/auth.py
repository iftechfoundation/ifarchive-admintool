from tinyapp.util import random_bytes
from tinyapp.excepts import HTTPError

def xsrf_cookie(req, han):
    if '_xsrf' in req.cookies:
        req._xsrf = req.cookies['_xsrf'].value
    else:
        req._xsrf = random_bytes(16)
        req.set_cookie('_xsrf', req._xsrf, httponly=True)
    return han(req)

### make another with secure=True

def xsrf_check_post(req, han):
    if req.request_method == 'POST':
        if ('_xsrf' not in req.input
            or not req.input['_xsrf']
            or req.input['_xsrf'][0] != req._xsrf):
            raise HTTPError('400 Bad Request', 'XSRF mismatch')
    return han(req)
    
