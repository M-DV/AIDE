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
from ..module import Module



class Reception(Module):
    '''
        Entry point for frontend about available projects in general.
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

        self.static_dir = 'modules/Reception/static'
        self.middleware = ReceptionMiddleware(config, db_connector)

        with open(os.path.abspath(os.path.join(self.static_dir, 'templates/projects.html')),
                  'r',
                  encoding='utf-8') as f_proj:
            self.proj_template = SimpleTemplate(f_proj.read())

        self._init_bottle()


    def _init_bottle(self):

        @self.app.route('/')
        def projects():
            username = html.escape(request.get_cookie('username', ''))
            return self.proj_template.render(
                version=AIDE_VERSION,
                username=username
            )


        @self.app.get('/getCreateAccountUnrestricted')
        def get_create_account_unrestricted() -> dict:
            '''
                Responds True if there's no token required for creating an account, else False.
            '''
            token = self.config.get_property('UserHandler',
                                             'create_account_token',
                                             dtype=str,
                                             fallback=None)
            return {'response': token is None or token == ''}


        @self.app.get('/getProjects')
        def get_projects() -> dict:
            if self.login_check():
                username = html.escape(request.get_cookie('username', ''))
            else:
                username = ''
            is_super_user = self.login_check(superuser=True)

            # pylint: disable=no-member
            archived = helpers.parse_boolean(request.params.get('archived', None))
            project_info = self.middleware.get_project_info(username,
                                                            is_super_user,
                                                            archived)
            return {'projects': project_info}


        # pylint: disable=inconsistent-return-statements
        @self.app.get('/<project>/enroll/<token>')
        def enroll_in_project(project: str, token: str) -> HTTPResponse:
            '''
                Adds a user to the list of contributors to a project if it is set to "public", or
                else if the secret token provided matches.
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
            except Exception as exc:
                print(exc)
                abort(400)


        @self.app.get('/<project>/getSampleImages')
        def get_sample_images(project: str) -> dict:
            '''
                Returns a list of URLs for images in the project, if the project is public or the
                user is enrolled in it. Used for backdrops on the project landing page. Prioritizes
                golden question images.
            '''

            # check visibility of project
            permissions = self.login_check(project=project, return_all=True)

            if not (permissions['project']['isPublic'] or \
                permissions['project']['enrolled'] or \
                permissions['project']['demoMode']):
                abort(401, 'unauthorized')

            # pylint: disable=no-member
            limit = int(request.params.get('limit', 128))
            image_urls = self.middleware.get_sample_images(project, limit)
            return {'images': image_urls}
