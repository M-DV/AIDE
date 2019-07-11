'''
    Private file server wrapper, to be used explicitly by the backend.
    Note: this instance does not do any user verification or authentication
    check; it is therefore imperative that it may never be exposed to the
    frontend.
    An instance of this FileServer class may be provided to the AIModel instead,
    and serves as a gateway to the project's actual file server.

    2019 Benjamin Kellenberger
'''

import os
import socket
from urllib import request
from urllib.parse import urlsplit
from urllib.error import HTTPError
import netifaces


class FileServer:

    def __init__(self, config):
        self.config = config

        # check if file server runs on the same machine
        self.isLocal = self._check_running_local()

        # base URI
        if self.isLocal:
            # URI is a direct file path
            self.baseURI = self.config.getProperty('FileServer', 'staticfiles_dir')
        
        else:
            self.baseURI = self.config.getProperty('Server', 'dataServer_uri')

    
    def _check_running_local(self):
        '''
            For simpler projects one might run both the AIWorker(s) and the FileServer
            module on the same machine. In this case we don't route file requests through
            the (loopback) network, but load files directly from disk. This is the case if
            the configuration's 'dataServer_uri' item specifies a local address, which we
            check for here.
        '''
        baseURI = self.config.getProperty('Server', 'dataServer_uri')

        # check for explicit localhost or hostname appearance in URL
        localhosts = ['localhost', socket.gethostname()]
        interfaces = netifaces.interfaces()
        for i in interfaces:
            iface = netifaces.ifaddresses(i).get(netifaces.AF_INET)
            if iface != None:
                for j in iface:
                    localhosts.append(j['addr'])
        
        baseURI_fragments = urlsplit(baseURI)
        baseURI_stripped = baseURI_fragments.netloc
        for l in localhosts:
            if baseURI_stripped.startswith(l):
                return True
        
        # also check for local addresses that do not even specify the hostname (e.g. '/files' or just 'files')
        if not baseURI.startswith('http'):
            return True
        
        # all checks failed; file server is running on another machine
        return False

    

    def getFile(self, filename):
        '''
            Returns the file as a byte array.
            If FileServer module runs on same instance as AIWorker,
            the file is directly loaded from the local disk.
            Otherwise an HTTP request is being sent.
        '''

        try:
            #TODO: make generator that yields bytes?
            queryPath = os.path.join(self.baseURI, filename)
            if self.isLocal:
                # load file from disk
                with open(queryPath, 'rb') as f:
                    bytea = f.read()

            else:
                response = request.urlopen(queryPath)
                bytea = response.read()

        except HTTPError as httpErr:
            print('HTTP error')
            print(httpErr)
            bytea = None

        except Exception as err:
            print(err)  #TODO: don't throw an exception, but let worker handle it?
            bytea = None

        return bytea

    

    def putFile(self, bytea, filename):
        #TODO: implement for cases where model may want to add an image.
        # What about remote file server? Might need to do authentication and sanity checks...
        pass