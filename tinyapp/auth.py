from tinyapp.util import random_bytes

def xsrf_cookie(req, han):
    if '_xsrf' in req.cookies:
        req._xsrf = req.cookies['_xsrf'].value
    else:
        req._xsrf = random_bytes(16)
        req.set_cookie('_xsrf', req._xsrf, httponly=True)
    return han(req)
            
### make another with secure=True
