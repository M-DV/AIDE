'''
    Bottle routings for the model marketplace. Handles I/O for sharing a model state (either
    publicly or only within the author's projects) and selecting shared states from neighboring
    projects. Also supports model state import and export to and from the disk, as well as the web.

    2020-24 Benjamin Kellenberger
'''

import uuid
import html
from bottle import static_file, request, abort

from util.cors import enable_cors
from util.helpers import parse_boolean
from .backend.middleware import ModelMarketplaceMiddleware
from .backend.marketplaceWorker import ModelMarketplaceWorker
from ..module import Module



class ModelMarketplace(Module):
    '''
        Frontend entry point for Model Marketplace.
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

        self.middleware = ModelMarketplaceMiddleware(config,
                                                     db_connector,
                                                     task_coordinator)
        self.temp_dir = ModelMarketplaceWorker(self.config, db_connector).temp_dir  #TODO

        self._init_bottle()


    def _init_bottle(self):

        @self.app.get('/<project>/getModelsMarketplace')
        def get_models_marketplace(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))

                # pylint: disable=no-member
                model_ids = request.params.get('model_ids', None)
                if isinstance(model_ids, str) and len(model_ids) > 0:
                    model_ids = model_ids.split(',')
                else:
                    model_ids = None

                model_states = self.middleware.getModelsMarketplace(project,
                                                                    username,
                                                                    model_ids)
                return {'modelStates': model_states}
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.get('/<project>/getModelMarketplaceNameAvailable')
        def get_model_marketplace_name_available(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                model_name = request.params['name']

                available = self.middleware.getModelIdByName(model_name) is None
                return {'status': 0, 'available': available}
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.post('/<project>/importModel')
        def import_model(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            # pylint: disable=no-member
            try:
                # get data
                username = html.escape(request.get_cookie('username'))

                if request.json is not None:

                    model_id = str(request.json['model_id'])
                    try:
                        model_id = uuid.UUID(model_id)

                        # model_id is indeed a UUID; import from database
                        return self.middleware.importModelDatabase(project, username, model_id)

                    except Exception:
                        # model comes from network
                        public = request.json.get('public', True)
                        anonymous = request.json.get('anonymous', False)

                        name_policy = request.json.get('name_policy', 'skip')
                        custom_name = request.json.get('custom_name', None)

                        force_reimport = not model_id.strip().lower().startswith('aide://')

                        return self.middleware.importModelURI(project,
                                                                username,
                                                                model_id,
                                                                public,
                                                                anonymous,
                                                                force_reimport,
                                                                name_policy,
                                                                custom_name)

                else:
                    # file upload
                    file = request.files.get(list(request.files.keys())[0])
                    public = parse_boolean(request.params.get('public', True))
                    anonymous = parse_boolean(request.params.get('anonymous', False))

                    name_policy = request.params.get('name_policy', 'skip')
                    custom_name = request.params.get('custom_name', None)

                    return self.middleware.importModelFile(project,
                                                            username,
                                                            file,
                                                            public,
                                                            anonymous,
                                                            name_policy,
                                                            custom_name)

            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.post('/<project>/requestModelDownload')
        def request_model_download(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            # pylint: disable=no-member
            try:
                # get data
                username = html.escape(request.get_cookie('username'))
                model_id = request.json['model_id']
                source = request.json['source']
                assert source in ('marketplace', 'project'), 'invalid download source provided'

                # optional values (for project-specific model download)
                model_name = request.json.get('model_name', None)
                model_description = request.json.get('model_description', '')
                model_tags = request.json.get('model_tags', [])

                result = self.middleware.requestModelDownload(project,
                                                                username,
                                                                model_id,
                                                                source,
                                                                model_name,
                                                                model_description,
                                                                model_tags)
                return result

            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.post('/<project>/shareModel')
        def share_model(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            # pylint: disable=no-member
            try:
                # get data
                username = html.escape(request.get_cookie('username'))
                model_id = request.json['model_id']
                model_name = request.json['model_name']
                model_description = request.json.get('model_description', '')
                tags = request.json.get('tags', [])
                citation_info = request.json.get('citation_info', None)
                license_str = request.json.get('license', None)
                public = request.json.get('public', True)
                anonymous = request.json.get('anonymous', False)
                result = self.middleware.shareModel(project,
                                                    username,
                                                    model_id,
                                                    model_name,
                                                    model_description,
                                                    tags,
                                                    citation_info,
                                                    license_str,
                                                    public,
                                                    anonymous)
                return result
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.post('/<project>/reshareModel')
        def reshare_model(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                # get data
                username = html.escape(request.get_cookie('username'))
                model_id = request.json['model_id']

                result = self.middleware.reshareModel(project,
                                                       username,
                                                       model_id)
                return result
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @self.app.post('/<project>/unshareModel')
        def unshare_model(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                # get data
                username = html.escape(request.get_cookie('username'))
                model_id = request.json['model_id']

                result = self.middleware.unshareModel(project,
                                                       username,
                                                       model_id)
                return result
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}


        @enable_cors
        @self.app.route('/<project>/download/models/<filename:re:.*>')
        def download_model(project, filename):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
                abort(401, 'forbidden')

            return static_file(filename,
                               root=self.temp_dir,
                               download=True)
