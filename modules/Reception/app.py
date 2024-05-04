'''
    The Reception module handles project overviews
    and the like.

    2019-24 Benjamin Kellenberger
'''

import os
import html
from bottle import request, redirect, abort, SimpleTemplate, HTTPResponse
from constants.version import AIDE_VERSION
from util import helpers
from .backend.middleware import ReceptionMiddleware


class Reception:

    def __init__(self, config, app, dbConnector, verbose_start=False):
        self.config = config
        self.app = app
        self.static_dir = 'modules/Reception/static'
        self.middleware = ReceptionMiddleware(config, dbConnector)
        self.login_check_fun = None

        self._init_bottle()


    def login_check(self,
                    project: str=None,
                    admin: bool=False,
                    superuser: bool=False,
                    can_create_projects: bool=False,
                    extend_session: bool=False,
                    return_all: bool=False) -> bool:
        '''
            Login check function wrapper.
        '''
        return self.login_check_fun(project,
                                    admin,
                                    superuser,
                                    can_create_projects,
                                    extend_session,
                                    return_all)


    def add_login_check_fun(self, login_check_fun: callable) -> None:
        '''
            Entry point during module assembly to provide login check function.
        '''
        self.login_check_fun = login_check_fun


    def _init_bottle(self):

        with open(os.path.abspath(os.path.join(self.static_dir, 'templates/projects.html')), 'r', encoding='utf-8') as f:
            self.proj_template = SimpleTemplate(f.read())

        @self.app.route('/')
        def projects():
            try:
                username = html.escape(request.get_cookie('username'))
            except Exception:
                username = ''
            return self.proj_template.render(
                version=AIDE_VERSION,
                username=username
            )


        @self.app.get('/getCreateAccountUnrestricted')
        def get_create_account_unrestricted():
            '''
                Responds True if there's no token required for creating
                an account, else False.
            '''
            try:
                token = self.config.get_property('UserHandler',
                                                 'create_account_token',
                                                 dtype=str,
                                                 fallback=None)
                return {'response': token is None or token == ''}
            except Exception:
                return {'response': False}


        @self.app.get('/getProjects')
        def get_projects():
            try:
                if self.login_check():
                    username = html.escape(request.get_cookie('username'))
                else:
                    username = ''
            except Exception:
                username = ''
            is_super_user = self.login_check(superuser=True)
            archived = helpers.parse_boolean(request.params.get('archived', None))
            project_info = self.middleware.get_project_info(
                                username, is_super_user,
                                archived)
            return {'projects': project_info}


        @self.app.get('/<project>/enroll/<token>')
        def enroll_in_project(project, token):
            '''
                Adds a user to the list of contributors to a project
                if it is set to "public", or else if the secret token
                provided matches.
            '''
            try:
                if not self.login_check():
                    return redirect(f'/login?redirect={project}/enroll/{token}')
                
                username = html.escape(request.get_cookie('username'))

                # # try to get secret token
                # try:
                #     providedToken = html.escape(request.query['t'])
                # except Exception:
                #     providedToken = None

                success = self.middleware.enroll_in_project(project, username, token)
                if not success:
                    abort(401)
                return redirect(f'/{project}/interface')
            except HTTPResponse as res:
                return res
            except Exception as e:
                print(e)
                abort(400)


        @self.app.get('/<project>/getSampleImages')
        def get_sample_images(project):
            '''
                Returns a list of URLs for images in the project,
                if the project is public or the user is enrolled
                in it. Used for backdrops on the project landing
                page.
                Prioritizes golden question images.
            '''

            # check visibility of project
            permissions = self.login_check(project=project, return_all=True)

            if not (permissions['project']['isPublic'] or \
                permissions['project']['enrolled'] or \
                permissions['project']['demoMode']):
                abort(401, 'unauthorized')
            
            try:
                limit = int(request.params.get('limit'))
            except Exception:
                limit = 128
            imageURLs = self.middleware.getSampleImages(project, limit)
            return {'images': imageURLs}