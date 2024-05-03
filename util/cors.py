'''
    Decorator that enables Cross-Origin Resource Sharing (CORS).

    2019-24 Benjamin Kellenberger
'''

from urllib.parse import urlparse
import bottle
from bottle import response
from util.configDef import Config

# CORS is only required if the FileServer URI is a valid URL
fileServerURI = Config().get_property('Server', 'dataServer_uri')
result = urlparse(fileServerURI)
cors_required = all([result.scheme, result.netloc]) #TODO: might be too strict...



def enable_cors(fn) -> None:
    '''
        Use as a decorator for functions requiring CORS headers to be sent.
    '''
    def _enable_cors(*args, **kwargs):
        # set CORS headers
        if cors_required:
            response.set_header('Access-Control-Allow-Origin', fileServerURI)
            response.set_header('Access-Control-Allow-Credentials', 'true')
            response.add_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
            response.add_header('Access-Control-Allow-Headers',
                                'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token, *')

        if bottle.request.method != 'OPTIONS':
            # actual request; reply with the response
            return fn(*args, **kwargs)

    return _enable_cors
