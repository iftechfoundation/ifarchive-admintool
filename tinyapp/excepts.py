
class HTTPError(Exception):
    def __init__(self, status, msg):
        self.status = status
        self.msg = msg
        
