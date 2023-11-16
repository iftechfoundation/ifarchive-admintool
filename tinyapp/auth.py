from tinyapp.util import random_bytes
from tinyapp.excepts import HTTPError

def xsrf_cookie(cookiename='_xsrf'):
    """Request filter which sets an XSRF cookie on any request. This cookie
    can be used with web forms to prevent cross-site scripting attacks.
    Add a hidden form field with name '_xsrf' and then check it in
    the POST response using the filter below.
    """
    def func(req, han):
        if cookiename in req.cookies:
            req._xsrf = req.cookies[cookiename].value
        else:
            req._xsrf = random_bytes(16)
            req.set_cookie(cookiename, req._xsrf, httponly=True)
        return han(req)
    return func


def xsrf_check_post(fieldname='_xsrf'):
    """Request filter which checks the XSRF field of a POST response against
    the user's XSRF cookie. (Has no effect on GET.)
    Note that the fieldname does not have to match the cookiename used
    by xsrf_cookie(). That's a HTTP cookie name; this is an HTML form
    field name.
    """
    def func(req, han):
        if req.request_method == 'POST':
            if (fieldname not in req.input
                or not req.input[fieldname]
                or req.input[fieldname][0] != req._xsrf):
                raise HTTPError('400 Bad Request', 'XSRF mismatch')
        return han(req)
    return func
    
