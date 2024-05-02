'''
    Private file server wrapper, to be used explicitly by the backend. Note: this instance does not
    do any user verification or authentication check; it is therefore imperative that it may never
    be exposed to the frontend. An instance of this FileServer class may be provided to the AIModel
    instead, and serves as a gateway to the project's actual file server.

    2019-24 Benjamin Kellenberger
'''

import os
import warnings
from urllib import request
import urllib.parse
from urllib.error import HTTPError
import numpy as np

from util.helpers import is_localhost
from util import drivers
drivers.init_drivers()



class FileServer:
    '''
        Main access point to files for both Web frontend and AI models.
    '''
    def __init__(self, config):
        self.config = config

        # check if file server runs on the same machine
        self.is_local = self._check_running_local()

        # base URI
        if self.is_local:
            # URI is a direct file path
            self.base_uri = self.config.get_property('FileServer', 'staticfiles_dir')
        else:
            self.base_uri = self.config.get_property('Server', 'dataServer_uri')


    def _check_running_local(self) -> bool:
        '''
            For simpler projects one might run both the AIWorker(s) and the FileServer module on the
            same machine. In this case we don't route file requests through the (loopback) network,
            but load files directly from disk. This is the case if the configuration's
            'dataServer_uri' item specifies a local address, which we check for here.
        '''
        base_uri = self.config.get_property('Server', 'dataServer_uri')
        return is_localhost(base_uri)


    @staticmethod
    def _path_valid(path: str) -> bool:
        '''
            Returns True if a given "path" does not contain root ("/", "\\") or parent ("..")
            accessors (else returns False).
        '''
        if len(path) == 0:
            return True
        return '..' not in path and path[0] not in ('/', '\\', os.sep)


    def get_file(self,
                 project: str,
                 filename: str) -> bytes:
        '''
            Returns the file as a byte array. If FileServer module runs on same instance as
            AIWorker, the file is directly loaded from the local disk. Otherwise an HTTP request is
            being sent.
        '''
        try:
            #TODO: make generator that yields bytes?
            if not self.is_local:
                filename = urllib.parse.quote(filename)
            local_spec = ('files' if not self.is_local else '')
            if project is not None:
                query_path = os.path.join(self.base_uri,
                                          project,
                                          local_spec,
                                          filename)
            else:
                query_path = os.path.join(self.base_uri, filename)

            if not self._path_valid(query_path):
                raise ValueError('Parent accessors ("..") and absolute paths ' + \
                                 f'("{os.sep}path") are not allowed.')

            if self.is_local:
                # load file from disk
                driver = drivers.get_driver(query_path)      #TODO: try-except?
                bytea = driver.disk_to_bytes(query_path)
                # with open(queryPath, 'rb') as f:
                #     bytea = f.read()
            else:
                response = request.urlopen(query_path)
                bytea = response.read()

        except HTTPError as http_err:
            print('HTTP error')
            print(http_err)
            bytea = None

        except Exception as err:
            print(err)  #TODO: don't throw an exception, but let worker handle it?
            bytea = None

        return bytea


    # pylint: disable=invalid-name
    def getFile(self,
                project: str,
                filename: str) -> bytes:
        '''
            Legacy method for compatibility.
        '''
        warnings.warn('Function "getFile" is deprecated and will be removed ' + \
                       'in a future release of AIDE.\n' + \
                       'Please use "get_file" instead.',
                       DeprecationWarning,
                       stacklevel=2)
        return self.get_file(project, filename)


    def get_image(self,
                  project: str,
                  filename: str) -> np.ndarray:
        '''
            Returns an image as a NumPy ndarray. If FileServer module runs on same instance as
            AIWorker, the file is directly loaded from the local disk. Otherwise an HTTP request is
            being sent.
        '''
        img = None
        try:
            if not self.is_local:
                filename = urllib.parse.quote(filename)
            local_spec = ('files' if not self.is_local else '')
            if project is not None:
                query_path = os.path.join(self.base_uri,
                                         project,
                                         local_spec,
                                         filename)
            else:
                query_path = os.path.join(self.base_uri, filename)

            if not self._path_valid(query_path):
                raise ValueError('Parent accessors ("..") and absolute paths ' + \
                                 f'("{os.sep}path") are not allowed.')

            if self.is_local:
                # load file from disk
                qpath_stripped, window = drivers.strip_window(query_path)
                driver = drivers.get_driver(qpath_stripped)      #TODO: try-except?
                img = driver.load_from_disk(qpath_stripped, window=window)
            else:
                response = request.urlopen(query_path)
                bytea = response.read()
                img = drivers.load_from_bytes(bytea)

        except HTTPError as httpErr:
            print('HTTP error')
            print(httpErr)
        except Exception as err:
            print(err)  #TODO: don't throw an exception, but let worker handle it?

        return img


    # pylint: disable=invalid-name
    def getImage(self, project, filename) -> np.ndarray:
        '''
            Legacy method for compatibility.
        '''
        warnings.warn('Function "getFile" is deprecated and will be removed ' + \
                       'in a future release of AIDE.\n' + \
                       'Please use "get_file" instead.',
                       DeprecationWarning,
                       stacklevel=2)
        return self.get_image(project, filename)


    def put_file(self,
                 project: str,
                 bytea: bytes,
                 filename: str) -> None:
        '''
            Saves a file to disk.
            TODO: requires locally running FileServer instance for now.
        '''
        #TODO: What about remote file server? Might need to do authentication and sanity checks...
        if project is not None:
            path = os.path.join(self.base_uri, project, filename)
        else:
            path = os.path.join(self.base_uri, filename)

        if not self._path_valid(path):
            raise ValueError('Parent accessors ("..") and absolute paths ' + \
                             f'("{os.sep}path") are not allowed.')

        with open(path, 'wb') as f:
            f.write(bytea)
        print('Wrote file to disk: ' + filename)    #TODO


    def get_secure_instance(self, project: str) -> callable:
        '''
            Returns a wrapper class to the "get_file" and "put_file" functions that disallow access
            to other projects than the one included.
        '''
        this = self

        # pylint: disable=invalid-name,missing-function-docstring
        class _secure_file_server:
            def getFile(self, filename):
                return this.get_file(project, filename)
            def getImage(self, filename):
                return this.get_image(project, filename)
            def putFile(self, bytea, filename):
                return this.put_file(project, bytea, filename)

        return _secure_file_server()
