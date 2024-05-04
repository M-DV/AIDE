'''
    Performs immediate image querying operations, such as area selection
    (GrabCut, etc.).

    2021-24 Benjamin Kellenberger
'''

from bottle import request, abort
from .backend.middleware import ImageQueryingMiddleware


class ImageQuerier:

    def __init__(self, config, app, db_connector, verbose_start=False):
        self.config = config
        self.app = app

        self.login_check_fun = None

        self.middleware = ImageQueryingMiddleware(config, db_connector)
        self._initBottle()


    def login_check(self,
                    project: str=None,
                    admin: bool=False,
                    superuser: bool=False,
                    can_create_projects: bool=False,
                    extend_session: bool=False) -> bool:
        '''
            Login check function wrapper.
        '''
        return self.login_check_fun(project,
                                    admin,
                                    superuser,
                                    can_create_projects,
                                    extend_session)


    def add_login_check_fun(self, login_check_fun: callable) -> None:
        '''
            Entry point during module assembly to provide login check function.
        '''
        self.login_check_fun = login_check_fun


    def _initBottle(self):

        @self.app.post('/<project>/grabCut')
        def grab_cut(project):
            # if not self.loginCheck(extend_session=True):
            #     abort(401, 'forbidden')

            try:
                args = request.json
                img_path = args['image_path']
                coords = args['coordinates']
                return_polygon = args.get('return_polygon', False)
                num_iter = args.get('num_iter', 5)

                result = self.middleware.grabCut(project,
                                                img_path,
                                                coords,
                                                return_polygon,
                                                num_iter)
                return {
                    'status': 0,
                    'result': result
                }

            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        @self.app.post('/<project>/magic_wand')
        def magic_wand(project):
            # if not self.loginCheck(extend_session=True):
            #     abort(401, 'forbidden')

            try:
                args = request.json
                img_path = args['image_path']
                seed_coords = args['seed_coordinates']
                tolerance = args.get('tolerance', 32)
                max_radius = args.get('max_radius', None)
                if max_radius <= 0:
                    # no restriction in space
                    max_radius = None
                rgb_only = args.get('rgb_only', False)

                result = self.middleware.magicWand(project,
                                                img_path,
                                                seed_coords,
                                                tolerance,
                                                max_radius,
                                                rgb_only)
                return {
                    'status': 0,
                    'result': result
                }

            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        @self.app.post('/<project>/select_similar')
        def select_similar(project):
            # if not self.loginCheck(extend_session=True):
            #     abort(401, 'forbidden')

            try:
                args = request.json
                img_path = args['image_path']
                seed_polygon = args['seed_polygon']
                tolerance = args.get('tolerance', 32)
                return_polygon = args.get('return_polygon', False)
                num_max = args.get('num_max', 1e9)

                result = self.middleware.select_similar(project,
                                                        img_path,
                                                        seed_polygon,
                                                        tolerance,
                                                        return_polygon,
                                                        num_max)
                return {
                    'status': 0,
                    'result': result
                }

            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        #TODO: image metadata parsing; move to more suitable place than ImageQuerying
        @self.app.post('/getImageMetadata')
        def get_image_metadata():
            if not self.login_check(can_create_projects=True):
                abort(401, 'forbidden')

            try:
                files = request.files
                meta = self.middleware.get_image_metadata(files)
                return {'status': 0, 'meta': meta}
            except Exception as exc:
                return {'status': 1, 'message': str(exc)}
