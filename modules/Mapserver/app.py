'''
    Web Map server functionality.

    2023-24 Benjamin Kellenberger
'''

import os
import html
from urllib.parse import urljoin, urlparse
import requests
from bottle import request, response, abort

from modules.Mapserver.backend.middleware import MapserverMiddleware

from constants.version import AIDE_VERSION
from util.cors import enable_cors
from util import helpers, logDecorator
from ..module import Module



# pylint: disable=too-few-public-methods
class Mapserver(Module):
    '''
        Map server Web frontend entry point.
    '''
    def __init__(self,
                 config,
                 app,
                 db_connector,
                 user_handler,
                 task_coordinator,
                 verbose_start=False,
                 passive_mode=False) -> None:
        super().__init__(config,
                         app,
                         db_connector,
                         user_handler,
                         task_coordinator,
                         verbose_start,
                         passive_mode)

        self.middleware = MapserverMiddleware(self.config, self.db_connector)

        self.is_file_server = helpers.is_file_server(config)

        if verbose_start:
            print('Mapserver'.ljust(logDecorator.LogDecorator.get_ljust_offset()), end='')

        self.postgis_version = self.middleware.postgis_version
        try:
            self._init_bottle()
        except Exception as exc:
            if verbose_start:
                logDecorator.LogDecorator.print_status('fail')
            raise Exception(f'Could not launch Mapserver (message: "{str(exc)}").') from exc
        if self.postgis_version is None:
            logDecorator.LogDecorator.print_status('warn')
            print('PostGIS not configured in database. Mapserver has been disabled.')


    @staticmethod
    def _get_base_url(url):
        return urljoin(url, urlparse(url).path)

    @staticmethod
    def _get_versions(params: dict, default: str=None) -> tuple:
        if 'VERSION' in params:
            return (params['VERSION'],)
        if 'ACCEPTVERSIONS' in params:
            return params['ACCEPTVERSIONS'].strip().split(',')
        return (default,)

    @staticmethod
    def _get_spatial_metadata(params: dict) -> tuple:
        bbox, crs = None, None

        # find crs
        for key in ('CRS', 'SRS', 'SRSNAME'):
            if key in params:
                crs = params[key]
                break

        for key in ('BBOX', 'BOUNDINGBOX'):
            if key in params:
                bbox_meta = params[key].strip().split(',')
                bbox = tuple(float(coord) for coord in bbox_meta[:4])
                if crs is None and len(bbox_meta) == 5:
                    # CRS provided as last element of bbox string
                    crs = bbox_meta[-1]
                break
        flip_coordinates = crs is not None and bbox is not None and crs.lower().strip() != 'crs:84'
        return bbox, crs, flip_coordinates


    def _relay_request(self,
                       request_name: str,
                       project: str=None,
                       method: str='get',
                       headers: dict=None):
        '''
            TODO: untested. Also, make dedicated helper function.
        '''
        # pylint: disable=no-member

        # forward request to FileServer
        cookies = dict(request.cookies.items())
        params = dict(request.params.items())

        req_fun = getattr(requests, method.lower())
        if project is None:
            project = ''
        return req_fun(os.path.join(self.config.get_property('Server', 'dataServer_uri'),
                        project, request_name),
                    cookies=cookies, json=request.json,
                    params=params,
                    headers=headers if isinstance(headers, dict) else {},
                    auth=request.auth)


    def _init_bottle(self):

        @enable_cors
        @self.app.get('/parseCRS')
        def parse_crs():
            '''
                Receives a string resembling a coordinate reference system (description, EPSG code,
                WKT, etc.) and performs a lookup with PostGIS to retrieve (and return) details about
                the best match(es).
            '''
            # pylint: disable=no-member

            if not self.login_check(can_create_projects=True):
                abort(401, 'forbidden')
            if self.postgis_version is None:
                return {'status': 2, 'message': 'PostGIS not configured.'}
            try:
                crs = request.params.get('crs')
                crs_meta = self.middleware.find_crs_info(crs)
                return {'status': 0, 'meta': crs_meta}
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @enable_cors
        @self.app.get('/mapserver/version')
        @self.app.get('/<project>/mapserver/version')
        def is_available(project=None):
            if not self.login_check(project=project):
                abort(401, 'forbidden')
            details = {
                'AIDE': AIDE_VERSION,
                'PostGIS': self.postgis_version
            }
            if project is not None:
                # append project SRID, too (to check if project has geospatial data enabled)
                project_meta = self.middleware.get_project_meta(project)
                details['srid'] = project_meta.get('srid', None)

            return details


        if self.postgis_version is None:
            return


        @enable_cors
        @self.app.get('/mapserver')
        @self.app.post('/mapserver')
        @self.app.get('/<project>/mapserver')
        @self.app.post('/<project>/mapserver')
        def mapserver(project=None):
            # pylint: disable=no-member

            # check authentication
            username, password = None, None

            if request.auth is not None and len(request.auth) == 2:
                username, password = request.auth

            if not self.login_check(project):
                # user not logged in, but check request authentication
                try:
                    self.user_handler.middleware.login(username, password, None)
                    response.set_cookie('username', username, path='/')
                    self.user_handler.middleware.encrypt_session_token(username, response)
                except Exception:
                    # login data provided, but login failed
                    abort(401, 'forbidden')     #TODO: send proper WMS exception?
            else:
                username = request.get_cookie('username', None)
                if username is not None:
                    username = html.escape(username)

            if self.postgis_version is None:
                abort(405, 'No PostGIS available in this instance of AIDE')

            if not self.is_file_server:
                return self._relay_request('mapserver', project, 'post')

            # harmonize parameters to uppercase
            params = dict([key.upper(), value] for key, value in request.params.items())

            bbox, crs, flip_coordinates = self._get_spatial_metadata(params)
            params.update({
                'BBOX': bbox,
                'CRS': crs,
                'FLIP_COORDINATES': flip_coordinates
            })

            service = params.get('SERVICE', 'WMS')
            request_item = params.get('REQUEST', 'GetCapabilities').lower()

            # delegate service request to middleware
            response_item, headers = self.middleware.service(service,
                                                             request_item,
                                                             params,
                                                             project,
                                                             username,
                                                             self._get_base_url(request.url))
            for header, value in headers.items():
                response.set_header(header, value)
            return response_item
