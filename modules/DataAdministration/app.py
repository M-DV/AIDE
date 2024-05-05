'''
    Bottle routings for data administration (i.e., image, annotation, and prediction down- and
    uploads). Needs to be run from instance responsible for serving files (i.e., FileServer module).

    2020-24 Benjamin Kellenberger
'''

from typing import Union, Tuple
import os
import datetime
import tempfile
import uuid
import json
import html
from bottle import static_file, request, response, abort
import requests

from util.cors import enable_cors
from util import helpers, drivers
from .backend.middleware import DataAdministrationMiddleware
from ..module import Module



class DataAdministrator(Module):
    '''
        Frontend interface for data administration (file up-/download).
    '''
    DEFAULT_SPLIT_PROPERTIES = {
        'patchSize': [800, 600],
        'stride': [800, 600],
        'tight': True,
        'virtualSplit': True
    }

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

        # set up either direct methods (if is FileServer) or relaying
        self.is_file_server = helpers.is_file_server(config)
        self.middleware = DataAdministrationMiddleware(config,
                                                       db_connector,
                                                       task_coordinator)

        self.temp_dir = self.config.get_property('FileServer',
                                                 'tempfiles_dir',
                                                 dtype=str,
                                                 fallback=tempfile.gettempdir())
        self._init_bottle()


    @staticmethod
    def _parse_range(params: dict,
                     param_name: str,
                     min_val: Union[int,float],
                     max_val: Union[int,float]) -> Tuple[Union[int,float]]:
        '''
            Parses "params" (dict) for a given keyword "param_name" (str), and expects a dict with
            keywords "min" and "max" there. One of the two may be missing, in which case the values
            of "min_val" and "max_val" will be used. Returns a tuple of (min, max) values, or None
            if "param_name" is not in "params."
        '''
        if params is None or not param_name in params:
            return None
        entry = params[param_name].copy()
        if not 'min' in entry:
            entry['min'] = min_val
        if not 'max' in entry:
            entry['max'] = max_val
        return (entry['min'], entry['max'])


    def relay_request(self,
                      project: str,
                      fun: callable,
                      method: str='get',
                      headers: dict=None) -> response:
        '''
            Used to forward requests to the FileServer instance, if it happens to be a different
            machine. Requests cannot go directly to the FileServer due to CORS restrictions.
        '''
        # pylint: disable=no-member,not-an-iterable

        if self.is_file_server:
            return None

        # forward request to FileServer
        cookies = request.cookies.dict
        for key in cookies:
            cookies[key] = cookies[key][0]
        files = {}
        if len(request.files):
            for key in request.files:
                files[key] = (request.files[key].raw_filename,
                              request.files[key].file,
                              request.files[key].content_type)
        params = {}
        if len(request.params.dict):
            for key in request.params.dict:
                params[key] = request.params.dict[key][0]

        req_fun = getattr(requests, method.lower())
        return req_fun(os.path.join(self.config.get_property('Server', 'dataServer_uri'),
                                    project,
                                    fun),
                       cookies=cookies, json=request.json, files=files,
                       params=params,
                       headers=headers if isinstance(headers, dict) else {})



    def _init_bottle(self):

        # pylint: disable=no-member,unsupported-membership-test,unused-argument

        @self.app.post('/<project>/verifyImages')
        def verify_images(project: str) -> dict:
            '''
                Launches a background task that verifies image integrity and entries in the database
                for a project. Only one such job can be run at a time for a particular project.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                username = html.escape(request.get_cookie('username'))
                image_list = request.json.get('image_list', [])
                quick_check = request.json.get('quick_check', False)
                result = self.middleware.verify_images(project, username,
                                image_list, quick_check)
                return {
                    'status': 0,
                    'messsage': result
                }
            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }

        @self.app.get('/<project>/getImageFolders')
        def get_image_folders(project: str) -> dict:
            '''
                Returns a dict that represents a hierarchical directory tree under which the images
                are stored in this project. This tree is obtained from the database itself, resp. a
                view that is generated from the image file names.
            '''
            if not self.login_check(project=project):
                abort(401, 'forbidden')

            try:
                result = self.middleware.getImageFolders(project)
                return {
                    'status': 0,
                    'tree': result
                }

            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        @enable_cors
        @self.app.post('/<project>/listImages')
        def list_images(project: str) -> dict:
            '''
                Returns a list of images and various properties and statistics (id, filename,
                viewcount, etc.), all filterable by date and value ranges.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            # parse parameters
            now = helpers.current_time()
            username = html.escape(request.get_cookie('username'))
            params = request.json

            folder = params.get('folder', None)

            image_added_range = self._parse_range(params,
                                                  'imageAddedRange',
                                                  datetime.time.min,
                                                  now)
            last_viewed_range = self._parse_range(params,
                                                  'lastViewedRange',
                                                  datetime.time.min,
                                                  now)
            viewcount_range = self._parse_range(params,
                                                'viewcountRange',
                                                0,
                                                1e9)
            num_anno_range = self._parse_range(params,
                                               'numAnnoRange',
                                               0,
                                               1e9)
            num_pred_range = self._parse_range(params,
                                               'numPredRange',
                                               0,
                                               1e9)
            order_by = params.get('orderBy', None)
            order = (params['order'].lower() if 'order' in params else None)
            if 'start_from' in params:
                start_fron = params['start_from']
                if isinstance(start_fron, str):
                    start_fron = uuid.UUID(start_fron)
            else:
                start_fron = None
            limit = params.get('limit', None)
            offset = params.get('offset', None)

            # get images
            result = self.middleware.listImages(project,
                                                username,
                                                folder,
                                                image_added_range,
                                                last_viewed_range,
                                                viewcount_range,
                                                num_anno_range,
                                                num_pred_range,
                                                order_by,
                                                order,
                                                start_fron,
                                                limit,
                                                offset)
            return {'response': result}


        @enable_cors
        @self.app.post('/<project>/initiateUploadSession')
        def initiate_upload_session(project: str) -> dict:
            '''
                Creates a new session of image and/or label files upload. Receives metadata
                regarding the upload (whether to import images, annotations; parameters; number of
                expected files) and creates a new session id. Then, the session's metadata gets
                stored in the "<temp folder>/aide_admin/<project>/<session id>" directory in a JSON
                file.

                The idea behind sessions is to inform the server about the expected number of files
                to be uploaded. Basically, we want to only parse annotations once every single file
                has been uploaded and parsed, to make sure we have no data loss.

                Returns the session ID as a response.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            if not self.is_file_server:
                return self.relay_request(project, 'initiateUploadSession', 'post')

            # gather parameters
            try:
                username = html.escape(request.get_cookie('username'))
                num_files = int(request.params.get('numFiles'))

                # images
                upload_images = helpers.parse_boolean(request.params.get('uploadImages', True))
                existing_files = request.params.get('existingFiles', 'keepExisting')
                match_num_bands_precisely = request.params.get('matchNumBandsPrecisely', False)
                try:
                    split_patches = helpers.parse_boolean(request.params.get('splitImages', False))
                    if split_patches:
                        split_props = self.DEFAULT_SPLIT_PROPERTIES.copy()
                        split_props.update(json.loads(request.params.get('splitParams')))
                    else:
                        split_props = None
                except Exception:
                    split_patches = False
                    split_props = None
                convert_unsupported = helpers.parse_boolean(
                                        request.params.get('convertUnsupported', True))

                # annotations
                parse_annotations = helpers.parse_boolean(
                                        request.params.get('parseAnnotations', False))
                assert not (parse_annotations and \
                    (upload_images and split_patches and \
                        not split_props.get('virtualSplit', True))), \
                    'cannot both split images into patches and parse annotations'
                skip_unknown_classes = helpers.parse_boolean(
                    request.params.get('skipUnknownClasses', True))
                mark_golden_questions = helpers.parse_boolean(
                    request.params.get('markAsGoldenQuestions', False))
                parser_id = request.params.get('parserID', None)
                if isinstance(parser_id, str) and \
                    parser_id.lower() in ('null', 'none', 'undefined'):
                    parser_id = None
                parser_kwargs = json.loads(request.params.get('parserArgs', '{}'))

                # create session
                session_id = self.middleware.createUploadSession(project, username, num_files,
                                                    upload_images, existing_files,
                                                    match_num_bands_precisely,
                                                    split_patches, split_props,
                                                    convert_unsupported, parse_annotations,
                                                    skip_unknown_classes, mark_golden_questions,
                                                    parser_id, parser_kwargs)
                return {'session_id': session_id}

            except Exception as e:
                return {'status': 1, 'message': str(e)}


        @enable_cors
        @self.app.post('/<project>/uploadData')
        def upload_data(project: str) -> dict:
            '''
                Upload image files and/or annotations through UI. Requires a session ID to be
                submitted as an argument along with one (or more) file(s). Proceeds to upload the
                files and save them to the session's temp dir, then parses the file and registers
                any identified and parseable images in the project (if defined as per session
                parameters). Appends uploaded file names and final file names as registered in the
                DB to a text file in the temp dir.

                Once the number of files uploaded matches the expected number of files ("numFiles"
                parameter in the session), and if annotation import has been enabled as per session
                parameter, that process will be started. Once this is done, all temporary files get
                removed.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            if not self.is_file_server:
                return self.relay_request(project, 'uploadData', 'post')

            try:
                username = html.escape(request.get_cookie('username'))
                session_id = request.params.get('sessionID')

                files = request.files

                # upload data
                result = self.middleware.uploadData(project, username, session_id, files)
                return {'result': result}
            except Exception as e:
                return {'status': 1, 'message': str(e)}


        @self.app.get('/<project>/scanForImages')
        @enable_cors
        def scan_for_images(project: str) -> dict:
            '''
                Search project file directory on disk for images that are not registered in
                database.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            username = html.escape(request.get_cookie('username'))
            skip_integrity_check = helpers.parse_boolean(
                request.params.get('skipIntegrityCheck', False))
            result = self.middleware.scanForImages(project,
                                                   username,
                                                   skip_integrity_check)
            return {'response': result}


        @enable_cors
        @self.app.post('/<project>/addExistingImages')
        def add_existing_images(project: str) -> dict:
            '''
                Add images that exist in project file directory on disk, but are not yet registered
                in database.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))
                skip_integrity_check = helpers.parse_boolean(
                    request.params.get('skipIntegrityCheck', False))
                props = request.json
                if isinstance(props, dict) and 'images' in props:
                    image_names = props['images']
                elif isinstance(props, str) and props.lower() == 'all':
                    image_names = 'all'
                    props = {}
                else:
                    return {'status': 2, 'message': 'Invalid parameters provided.'}

                # virtual view split parameters
                try:
                    split_patches = helpers.parse_boolean(props.get('splitImages', False))
                    if split_patches:
                        split_props = self.DEFAULT_SPLIT_PROPERTIES.copy()
                        split_props.update(json.loads(props.get('splitParams', '{}')))
                    else:
                        split_props = None
                except Exception:
                    split_patches = False
                    split_props = None

                result = self.middleware.addExistingImages(project,
                                                            username,
                                                            image_names,
                                                            skip_integrity_check,
                                                            split_patches,
                                                            split_props)
                return {'status': 0, 'response': result}
            except Exception as e:
                return {'status': 1, 'message': str(e)}


        @enable_cors
        @self.app.post('/<project>/removeImages')
        def remove_images(project: str) -> dict:
            '''
                Remove images from database, including predictions and annotations (if flag is set).
                Also remove images from disk (if flag is set).
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))
                data = request.json
                image_ids = data['images']
                force_remove = data.get('forceRemove', False)
                delete_from_disk = data.get('deleteFromDisk', False)

                images_deleted = self.middleware.removeImages(project,
                                                                username,
                                                                image_ids,
                                                                force_remove,
                                                                delete_from_disk)

                return {'status': 0, 'images_deleted': images_deleted}

            except Exception as e:
                return {'status': 1, 'message': str(e)}


        @enable_cors
        @self.app.get('/<project>/getValidImageExtensions')
        def get_valid_image_extensions(project: str=None) -> dict:
            '''
                Returns the file extensions for images currently
                supported by AIDE.
            '''
            return {'extensions': tuple(drivers.VALID_IMAGE_EXTENSIONS)}


        @enable_cors
        @self.app.get('/<project>/getValidMIMEtypes')
        def get_valid_mime_types(project: str=None) -> dict:
            '''
                Returns the MIME types for images currently
                supported by AIDE.
            '''
            return {'MIME_types': tuple(drivers.VALID_IMAGE_MIME_TYPES)}


        # data download
        @enable_cors
        @self.app.get('/<project>/getSupportedAnnotationFormats')
        def get_annotation_formats(project: str=None) -> dict:
            '''
                Returns all available annotation (prediction) parsers as well as their HTML markup
                for custom parser options to be set during annotation im- and export. See
                util.parsers.PARSERS for more infos.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            method = request.params.get('method', 'download')
            formats = self.middleware.getParserInfo(project, method)

            return {'formats': formats}


        @enable_cors
        @self.app.post('/<project>/requestAnnotations')
        def request_annotations(project: str) -> dict:
            '''
                Parses request parameters and initiates a parser that prepares annotations or
                predictions for download on the file server in a temporary directory (in a Zip
                file). Returns the Celery task ID accordingly.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            # parse parameters
            try:
                username = html.escape(request.get_cookie('username'))
                params = request.json
                # one of the supported formats. See util.parsers.PARSERS
                export_format = params['exportFormat']
                # {'annotation', 'prediction'}
                data_type = params['dataType']
                # subset of users (or model states) to export annotations (or predictions) from
                author_list = params.get('authorList', None)
                # optional start (+ optional end) date to export annotations/predictions from
                date_range = params.get('dateRange', None)
                # if True, annotations not created through the interface but batch-imported will be
                # skipped
                ignore_imported = params.get('ignoreImported', False)
                # optional dict of arguments for the parser chosen
                parser_args = params.get('parserArgs', {})

                # initiate task
                task_id = self.middleware.requestAnnotations(
                    project, username,
                    export_format, data_type,
                    author_list, date_range,
                    ignore_imported, parser_args
                )
                return {'response': task_id}

            except Exception as e:
                abort(401, str(e))


        @enable_cors
        @self.app.post('/<project>/requestDownload')
        def request_download(project):
            '''
                Parses request parameters and then assembles project- related metadata (annotations,
                predictions, etc.) by storing them as files on the server in a temporary directory.
                Returns the download links to those temporary files.
            '''
            #TODO: allow download for non-admins?
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            # parse parameters
            try:
                username = html.escape(request.get_cookie('username'))
                params = request.json
                data_type = params['dataType']
                if 'dateRange' in params:
                    date_range = []
                    if 'start' in params['dateRange']:
                        date_range.append(params['dateRange']['start'])
                    else:
                        date_range.append(0)
                    if 'end' in params['dateRange']:
                        date_range.append(params['dateRange']['end'])
                    else:
                        date_range.append(helpers.current_time())
                else:
                    date_range = None

                user_list = params.get('users', None)

                # extra query fields (TODO)
                extra_fields = params.get('extra_fields', {'meta': False})

                # advanced parameters for segmentation masks
                segmask_filename_opts = params.get('segmask_filename',
                                                   {
                                                    'baseName': 'filename',
                                                    'prefix': None,
                                                    'suffix': None
                                                   })
                segmask_encoding = params.get('segmask_encoding', 'rgb')

                task_id = self.middleware.prepareDataDownload(project,
                                                                username,
                                                                data_type,
                                                                user_list,
                                                                date_range,
                                                                extra_fields,
                                                                segmask_filename_opts,
                                                                segmask_encoding)
                return {'response': task_id}

            except Exception as e:
                abort(401, str(e))


        @enable_cors
        @self.app.route('/<project>/downloadData/<filename:re:.*>')
        def download_data(project: str, filename: str) -> response:
            #TODO: allow download for non-admins?
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
                abort(401, 'forbidden')

            if not self.is_file_server:
                #TODO: fix headers for relay requests
                headers = {}
                # headers[str("content-type")] = 'text/csv'
                headers['Content-Disposition'] = 'attachment'   #;filename="somefilename.csv"'
                return self.relay_request(project,
                                          os.path.join('downloadData', filename),
                                          'get',
                                          headers)

            return static_file(filename,
                               root=os.path.join(self.temp_dir, 'aide/downloadRequests', project),
                               download=True)
