# Archivo falso para engañar a Android
class WSGIServer:
    pass

def make_server(*args, **kwargs):
    return WSGIServer()
