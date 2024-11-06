'''
    This module handles everything about the setup and monitoring of AIDE (i.e., super user
    functionality).

    2020-24 Benjamin Kellenberger
'''

import os
import html
from bottle import SimpleTemplate, request, redirect, abort

from constants.version import AIDE_VERSION
from .backend.middleware import AdminMiddleware
from ..module import Module



class AIDEAdmin(Module):
    '''
        Frontend entry point for administration (super user) details of AIDE.
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

        self.static_dir = 'modules/AIDEAdmin/static'

        self.middleware = AdminMiddleware(config, db_connector)

        # ping connected AIController, FileServer, etc. servers and check version
        self.middleware.get_service_details(verbose_start, verbose_start)

        # read AIDE admin templates
        with open(os.path.abspath(os.path.join(self.static_dir, 'templates/aideAdmin.html')),
                  'r',
                  encoding='utf-8') as f_admin:
            self.admin_template = SimpleTemplate(f_admin.read())

        self.panel_templates = {}
        panel_names = os.listdir(os.path.join(self.static_dir, 'templates/panels'))
        for panel_name in panel_names:
            name, ext = os.path.splitext(panel_name)
            if ext.lower().startswith('.htm'):
                with open(os.path.join(self.static_dir,
                                       'templates/panels',
                                       panel_name),
                          'r',
                          encoding='utf-8') as f_panel:
                    self.panel_templates[name] = SimpleTemplate(f_panel.read())

        self._init_bottle()


    def _init_bottle(self):
        # pylint: disable=inconsistent-return-statements

        @self.app.route('/admin/config/panels/<panel>')
        def send_static_panel(panel):
            if self.login_check(superuser=True):
                try:
                    return self.panel_templates[panel].render(
                        version=AIDE_VERSION
                    )
                except Exception:
                    abort(404, 'not found')
            else:
                abort(401, 'forbidden')


        @self.app.get('/exec')
        def aide_exec():
            '''
                Reserve for future implementations that require unauthorized but token-protected
                services.
            '''
            abort(404, 'not found')


        @self.app.route('/admin')
        @self.user_handler.middleware.csrf_token
        def send_aide_admin_page():
            if not self.login_check():
                return redirect('/login?redirect=/admin')
            if not self.login_check(superuser=True):
                return redirect('/')

            # render configuration template
            try:
                username = html.escape(request.get_cookie('username'))
                if len(username.strip()) == 0:
                    return redirect('/login?redirect=/admin')
            except AttributeError:
                return redirect('/login?redirect=/admin')

            return self.admin_template.render(
                    version=AIDE_VERSION,
                    username=username,
                    _csrf_token=request.csrf_token)


        @self.app.get('/getServiceDetails')
        def get_service_details():
            try:
                if not self.login_check(superuser=True):
                    return redirect('/')
                return {'details': self.middleware.get_service_details()}
            except Exception:
                abort(404, 'not found')


        @self.app.get('/getCeleryWorkerDetails')
        def get_celery_worker_details():
            try:
                if not self.login_check(superuser=True):
                    return redirect('/')
                return {'details': self.middleware.get_celery_worker_details()}
            except Exception:
                abort(404, 'not found')


        @self.app.get('/getProjectDetails')
        def get_project_details():
            try:
                if not self.login_check(superuser=True):
                    return redirect('/')
                return {'details': self.middleware.get_project_details()}
            except Exception:
                abort(404, 'not found')


        @self.app.get('/getUserDetails')
        def get_user_details():
            try:
                if not self.login_check(superuser=True):
                    return redirect('/')
                return {'details': self.middleware.get_user_details()}
            except Exception:
                abort(404, 'not found')


        @self.app.post('/setCanCreateProjects')
        def set_can_create_projects():
            try:
                if not self.login_check(superuser=True):
                    return redirect('/')

                try:
                    data = request.json
                    status = self.middleware.set_can_create_projects(data['username'],
                                                                     data['canCreateProjects'])
                    return {'response': status}
                except Exception as exc:
                    return {
                        'response': {
                            'success': False,
                            'message': str(exc)
                        }
                    }
            except Exception:
                abort(404, 'not found')
