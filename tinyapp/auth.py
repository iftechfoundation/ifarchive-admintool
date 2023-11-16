from tinyapp.util import random_bytes
from tinyapp.excepts import HTTPError

def xsrf_cookie(req, han):
    """Request filter which sets an XSRF cookie on any request. This cookie
    can be used with web forms to prevent cross-site scripting attacks.
    Add a hidden form field with name '_xsrf' and then check it in
    the POST response using the filter below.
    """
    if '_xsrf' in req.cookies:
        req._xsrf = req.cookies['_xsrf'].value
    else:
        req._xsrf = random_bytes(16)
        req.set_cookie('_xsrf', req._xsrf, httponly=True)
    return han(req)


def xsrf_check_post(req, han):
    """Request filter which checks the XSRF field of a POST response against
    the user's XSRF cookie. (Has no effect on GET.)
    """
    if req.request_method == 'POST':
        if ('_xsrf' not in req.input
            or not req.input['_xsrf']
            or req.input['_xsrf'][0] != req._xsrf):
            raise HTTPError('400 Bad Request', 'XSRF mismatch')
    return han(req)
    
