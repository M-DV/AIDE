'''
    Main Bottle and routings for the UserHandling module.

    2019-24 Benjamin Kellenberger
'''

import os
import html
from bottle import request, response, abort, redirect, SimpleTemplate
from constants.version import AIDE_VERSION
from .backend.middleware import UserMiddleware
from .backend import exceptions


class UserHandler:
    '''
        Entry point for user administration, logging in/out, etc. Unlike other modules, this is one
        of the core classes and therefore does not inherit from the base module class.
    '''

    def __init__(self,
                 config,
                 app,
                 db_connector,
                 **_) -> None:
        self.config = config
        self.app = app
        self.static_dir = 'modules/UserHandling/static'
        self.middleware = UserMiddleware(config, db_connector)

        self.index_uri = self.config.get_property('Server',
                                                  'index_uri',
                                                  dtype=str,
                                                  fallback='/')

        create_account_token = self.config.get_property('UserHandler',
                                                        'create_account_token',
                                                        dtype=str,
                                                        fallback='')
        self.create_account_public = int(len(create_account_token.strip()) == 0)

        with open(os.path.abspath(os.path.join(self.static_dir,
                                               'templates/loginScreen.html')),
                  'r',
                  encoding='utf-8') as f_login:
            self.login_screen_template = SimpleTemplate(f_login.read())

        with open(os.path.abspath(os.path.join(self.static_dir,
                                               'templates/newAccountScreen.html')),
                  'r',
                  encoding='utf-8') as f_newaccount:
            self.new_account_screen_template = SimpleTemplate(f_newaccount.read())

        self._init_bottle()


    def _parse_parameter(self, request_instance, param):
        if not param in request_instance:
            raise exceptions.ValueMissingException(param)
        return request_instance.get(param)


    def _init_bottle(self):

        @self.app.route('/login')
        @self.app.route('/loginScreen')
        @self.middleware.csrf_token
        def show_login_page():
            return self.login_screen_template.render(
                version=AIDE_VERSION,
                _csrf_token=request.csrf_token,
                show_create_account=self.create_account_public
            )


        @self.app.route('/doLogin', method='POST')
        @self.app.route('/<project>/doLogin', method='POST')
        def do_login(project=None):
            #TODO: causes issues with Mapserver
            self.middleware.csrf_check(request.forms.get('_csrf_token'))

            # check provided credentials
            try:
                username = html.escape(self._parse_parameter(request.forms, 'username'))
                password = self._parse_parameter(request.forms, 'password')

                # check if session token already provided; renew login if correct
                session_token = self.middleware.decrypt_session_token(username, request)
                #request.get_cookie('session_token', secret=self.config.get_property('Project',
                #'secret_token'))
                if session_token is not None:
                    session_token = html.escape(session_token)

                session_token, _, expires = self.middleware.login(username,
                                                                  password,
                                                                  session_token)

                response.set_cookie('username', username, path='/')     #, expires=expires, same_site='strict')
                self.middleware.encrypt_session_token(username, response)
                # response.set_cookie('session_token', session_token, httponly=True, path='/',
                # secret=self.config.get_property('Project', 'secret_token'))    #, expires=expires,
                # same_site='strict')

                return {
                    'expires': expires.strftime('%H:%M:%S')
                }

            except Exception as exc:
                abort(403, str(exc))


        @self.app.route('/loginCheck', method='POST')
        @self.app.route('/<project>/loginCheck', method='POST')
        def login_check(project=None):
            try:
                username = request.get_cookie('username')
                if username is None:
                    username = self._parse_parameter(request.forms, 'username')
                username = html.escape(username)

                session_token = self.middleware.decrypt_session_token(username, request)
                # sessionToken = html.escape(request.get_cookie('session_token',
                # secret=self.config.get_property('Project', 'secret_token')))

                _, _, expires = self.middleware.get_login_data(username, session_token)

                response.set_cookie('username', username, path='/')   #, expires=expires, same_site='strict')
                self.middleware.encrypt_session_token(username, response)
                # response.set_cookie('session_token', session_token, httponly=True, path='/',
                # secret=self.config.get_property('Project', 'secret_token'))    #, expires=expires,
                # same_site='strict')
                return {
                    'expires': expires.strftime('%H:%M:%S')
                }

            except Exception as exc:
                abort(401, str(exc))


        @self.app.route('/logout', method='GET')
        @self.app.route('/logout', method='POST')
        @self.app.route('/<project>/logout', method='GET')
        @self.app.route('/<project>/logout', method='POST')
        def logout(project=None):
            try:
                username = html.escape(request.get_cookie('username'))
                session_token = self.middleware.decrypt_session_token(username, request)
                self.middleware.logout(username, session_token)
                response.set_cookie('username', '', path='/', expires=0)   #, expires=expires, same_site='strict')
                response.set_cookie('session_token', '',
                            httponly=True, path='/', expires=0)
                # self.middleware.encryptSessionToken(username, response)
                # response.set_cookie('session_token', session_token, httponly=True, path='/',
                # secret=self.config.get_property('Project', 'secret_token'))    #, expires=expires,
                # same_site='strict')

                # send redirect
                response.status = 303
                response.set_header('Location', self.index_uri)
                return response

            except Exception as exc:
                abort(403, str(exc))


        @self.app.route('/<project>/getPermissions', method='POST')
        def get_user_permissions(project):
            try:
                try:
                    username = html.escape(request.get_cookie('username'))
                except Exception:
                    username = None
                if not self.check_authenticated(project=project):
                    abort(401, 'not permitted')

                return {
                    'permissions': self.middleware.get_user_permissions(project, username)
                }
            except Exception:
                abort(400, 'bad request')


        @self.app.route('/getUserNames', method='POST')
        @self.app.route('/<project>/getUserNames', method='POST')
        def get_user_names(project=None):
            if project is None:
                try:
                    project = request.json['project']
                except Exception:
                    # no project specified (all users); need be superuser for this
                    project = None

            if self.check_authenticated(project, admin=True, superuser=(project is None),
                                            extend_session=True):
                return {
                    'users': self.middleware.get_user_names(project)
                }
            abort(401, 'forbidden')


        @self.app.route('/doCreateAccount', method='POST')
        def create_account():
            self.middleware.csrf_check(request.forms.get('_csrf_token'), regenerate=False)

            #TODO: make secret token match
            try:
                username = html.escape(self._parse_parameter(request.forms, 'username'))
                password = self._parse_parameter(request.forms, 'password')
                email = html.escape(self._parse_parameter(request.forms, 'email'))

                _, _, expires = self.middleware.create_account(
                    username, password, email
                )

                response.set_cookie('username', username, path='/')   #, expires=expires, same_site='strict')
                self.middleware.encrypt_session_token(username, response)
                # response.set_cookie('session_token', sessionToken, httponly=True, path='/',
                # secret=self.config.get_property('Project', 'secret_token'))    #, expires=expires,
                # same_site='strict')
                return {
                    'expires': expires.strftime('%H:%M:%S')
                }

            except Exception as exc:
                abort(403, str(exc))


        @self.app.route('/createAccount')
        @self.middleware.csrf_token
        def show_new_account_page():
            # check if token is required; if it is and wrong token provided, show login screen
            # instead
            try:
                target_token = html.escape(self.config.get_property('UserHandler',
                                                                    'create_account_token'))
            except Exception:
                # no secret token defined
                target_token = None
            if target_token is not None and target_token != '':
                try:
                    provided_token = html.escape(request.query['t'])
                    if provided_token == target_token:
                        page = self.new_account_screen_template.render(
                            version=AIDE_VERSION,
                            _csrf_token=request.csrf_token
                        )
                    else:
                        redirect('/login')
                except Exception:
                    redirect('/login')
            else:
                # no token required
                page = self.new_account_screen_template.render(
                    version=AIDE_VERSION,
                    _csrf_token=request.csrf_token
                )
            response.set_header('Cache-Control', 'public, max-age=0')
            return page


        @self.app.route('/accountExists', method='POST')
        def check_account_exists():
            self.middleware.csrf_check(request.forms.get('_csrf_token'), regenerate=False)
            username = ''
            email = ''
            try:
                username = html.escape(self._parse_parameter(request.forms, 'username'))
            except Exception:
                pass
            try:
                email = html.escape(self._parse_parameter(request.forms, 'email'))
            except Exception:
                pass
            try:
                user_available, email_available = self.middleware.account_available(username, email)
                return {
                    'response': {
                        'username': not user_available,
                        'email': not email_available
                    }
                }
            except Exception as exc:
                abort(401, str(exc))


        @self.app.get('/getAuthentication')
        @self.app.post('/getAuthentication')
        def get_authentication():
            if not self.check_authenticated():
                return { 'authentication': {
                        'canCreateProjects': False,
                        'isSuperUser': False
                    }
                }
            try:
                username = html.escape(request.get_cookie('username'))

                # optional: project
                # pylint: disable=no-member
                project = request.query.get('project', None)
                if project is not None:
                    project = html.escape(project)

                return { 'authentication': self.middleware.get_authentication(username, project) }

            except Exception:
                return { 'authentication': {
                        'canCreateProjects': False,
                        'isSuperUser': False
                    }
                }


        @self.app.post('/setPassword')
        def set_password():
            '''
                Routine for super users to set the password of a user.
            '''
            if self.check_authenticated(superuser=True):
                try:
                    data = request.json
                    username = data['username']
                    password = data['password']
                    result = self.middleware.set_password(username, password)
                    return result

                except Exception as exc:
                    return {
                        'success': False,
                        'message': str(exc)
                    }
            else:
                abort(404, 'not found')


        @self.app.get('/v')
        def user_verify():
            '''
                Reserve for future implementations that require unauthorized but token-protected
                user services.
            '''
            abort(404, 'not found')


    def check_authenticated(self,
                            project: str=None,
                            admin: bool=False,
                            superuser: bool=False,
                            can_create_projects: bool=False,
                            extend_session: bool=False,
                            return_all: bool=False) -> dict:
        '''
            Main entry point for all modules to check if a requestor is authenticated to get, post,
            put, etc. data.
        '''
        username = None
        session_token = None
        try:
            username = request.get_cookie('username', None)
            if username is not None:
                username = html.escape(username)
            elif hasattr(request, 'auth') and len(request.auth) > 0:
                # fallback: request.auth
                username = request.auth[0]
            session_token = self.middleware.decrypt_session_token(username, request)
        except Exception:
            pass

        try:
            return self.middleware.is_authenticated(username,
                                                    session_token,
                                                    project,
                                                    admin,
                                                    superuser,
                                                    can_create_projects,
                                                    extend_session,
                                                    return_all)
        except Exception:
            return False


    def get_login_check_fun(self) -> callable:
        '''
            Returns the function handle to check if a user is logged in.
        '''
        return self.check_authenticated
