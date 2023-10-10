import os
import time

def random_bytes(count):
    byt = os.urandom(count)
    return bytes.hex(byt)
        
def time_now():
    return int(time.time())
