import os
import time

def random_bytes(count):
    """Return N random bytes from a good source.
    """
    byt = os.urandom(count)
    return bytes.hex(byt)
        
def time_now():
    """Return the current time. (Rounded to the nearest second
    because that's good enough.)
    """
    return int(time.time())
