# Archivo falso para engañar a Android

class WSGIServer:
    pass

# ESTA es la clase que faltaba y causaba el error:
class WSGIRequestHandler:
    pass

def make_server(*args, **kwargs):
    return WSGIServer()
