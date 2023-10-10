import os

def random_bytes(count):
    byt = os.urandom(count)
    return bytes.hex(byt)
        
