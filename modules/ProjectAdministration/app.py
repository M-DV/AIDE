'''
    Bottle routings for the ProjectConfigurator web frontend,
    handling project setup, data import requests, etc.
    Also handles creation of new projects.

    2019-24 Benjamin Kellenberger
'''

import os
import html
import json
import bottle
from bottle import request, redirect, abort, SimpleTemplate
from constants.version import AIDE_VERSION
from .backend.middleware import ProjectConfigMiddleware


class ProjectConfigurator:

    def __init__(self, config, app, dbConnector, verbose_start=False):
        self.config = config
        self.app = app
        self.static_dir = 'modules/ProjectAdministration/static'
        self.middleware = ProjectConfigMiddleware(config, dbConnector)

        self.login_check = None

        self._initBottle()


    def loginCheck(self, project=None, admin=False, superuser=False, canCreateProjects=False, extend_session=False, return_all=False):
        return self.login_check(project, admin, superuser, canCreateProjects, extend_session, return_all)


    def addLoginCheckFun(self, loginCheckFun):
        self.login_check = loginCheckFun


    def __redirect(self, loginPage=False, redirect=None):
        location = ('/login' if loginPage else '/')
        if loginPage and redirect is not None:
            location += '?redirect=' + redirect
        response = bottle.response
        response.status = 303
        response.set_header('Location', location)
        return response


    def _initBottle(self):

        # read project configuration templates
        with open(os.path.abspath(os.path.join(self.static_dir,
                'templates/projectLandingPage.html')), 'r', encoding='utf-8') as f_template:
            self.projLandPage_template = SimpleTemplate(f_template.read())

        with open(os.path.abspath(os.path.join(self.static_dir,
                'templates/projectConfiguration.html')), 'r', encoding='utf-8') as f_template:
            self.projConf_template = SimpleTemplate(f_template.read())

        with open(os.path.abspath(os.path.join(self.static_dir,
                'templates/projectConfigWizard.html')), 'r', encoding='utf-8') as f_template:
            self.projSetup_template = SimpleTemplate(f_template.read())


        self.panel_templates = {}
        panel_files = os.listdir(os.path.join(self.static_dir, 'templates/panels'))
        for panel_file in panel_files:
            panel_name, ext = os.path.splitext(panel_file)
            if ext.lower().startswith('.htm'):
                with open(os.path.join(self.static_dir, 'templates/panels', panel_file), 'r',
                    encoding='utf-8') as f_panel:
                    self.panel_templates[panel_name] = SimpleTemplate(f_panel.read())


        @self.app.route('/<project>/config/panels/<panel>')
        def send_static_panel(project, panel):
            if not self.loginCheck(project=project):
                abort(401, 'forbidden')
            if self.loginCheck(project=project, admin=True):
                try:
                    return self.panel_templates[panel].render(
                        version=AIDE_VERSION,
                        project=project
                    )
                except Exception:
                    abort(404, 'not found')
            else:
                abort(401, 'forbidden')


        @self.app.route('/<project>')
        @self.app.route('/<project>/')
        def send_project_overview(project):

            # get project data (and check if project exists)
            try:
                is_admin = self.loginCheck(project=project, admin=True)
                project_data = self.middleware.getProjectInfo(project,
                                    ['name', 'description', 'interface_enabled', 'demomode'],
                                    is_admin)
                if project_data is None:
                    return self.__redirect()
            except Exception:
                return self.__redirect()

            if not self.loginCheck(project=project, extend_session=True):
                return self.__redirect(True, project)

            # render overview template
            try:
                username = html.escape(request.get_cookie('username'))
            except Exception:
                username = ''

            return self.projLandPage_template.render(
                version=AIDE_VERSION,
                projectShortname=project,
                projectTitle=project_data['name'],
                projectDescription=project_data['description'],
                username=username)


        @self.app.route('/<project>/setup')
        def send_project_setup_page(project):

            #TODO
            if not self.loginCheck(canCreateProjects=True):
                return self.__redirect(loginPage=True, redirect='/' + project + '/setup')

            # get project data (and check if project exists)
            project_data = self.middleware.getProjectInfo(project,
                                        ['name', 'description', 'interface_enabled', 'demomode'],
                                        True)
            if project_data is None:
                return self.__redirect()

            if not self.loginCheck(project=project, extend_session=True):
                return redirect('/')

            if not self.loginCheck(project=project, admin=True, extend_session=True):
                return redirect('/' + project + '/interface')

            # render configuration template
            try:
                username = html.escape(request.get_cookie('username'))
            except Exception:
                username = ''

            return self.projSetup_template.render(
                    version=AIDE_VERSION,
                    projectShortname=project,
                    projectTitle=project_data['name'],
                    username=username)


        @self.app.route('/<project>/configuration/<panel>')
        def send_project_config_panel(project, panel=None):
            #TODO
            if not self.loginCheck():
                if panel is None:
                    panel = 'overview'
                return self.__redirect(loginPage=True, redirect=f'/{project}/configuration/{panel}')

            if not self.loginCheck(project=project, extend_session=True):
                return redirect('/')

            if not self.loginCheck(project=project, admin=True, extend_session=True):
                return redirect('/' + project + '/interface')

            # get project data (and check if project exists)
            project_data = self.middleware.getProjectInfo(project, ['name'], True)
            if project_data is None or 'name' not in project_data:
                return self.__redirect()

            # render configuration template
            try:
                username = html.escape(request.get_cookie('username'))
            except Exception:
                username = ''

            if panel is None:
                panel = ''

            return self.projConf_template.render(
                    version=AIDE_VERSION,
                    panel=panel,
                    projectShortname=project,
                    projectTitle=project_data['name'],
                    username=username)


        @self.app.route('/<project>/configuration')
        def send_project_config_page(project):
            # compatibility for deprecated configuration panel access
            return send_project_config_panel(project)


        @self.app.get('/<project>/getPlatformInfo')
        @self.app.post('/<project>/getPlatformInfo')
        def get_platform_info(project):
            if not self.loginCheck(project, admin=True):
                abort(401, 'forbidden')
            try:
                # parse subset of configuration parameters (if provided)
                params = None if request.json is None else request.json.get('parameters', None)

                proj_data = self.middleware.getPlatformInfo(project, params)
                return { 'settings': proj_data }
            except Exception:
                abort(400, 'bad request')


        @self.app.get('/<project>/getProjectImmutables')
        @self.app.post('/<project>/getProjectImmutables')
        def get_project_immutables(project):
            if not self.loginCheck(project, admin=True):
                abort(401, 'forbidden')
            return {'immutables': self.middleware.getProjectImmutables(project)}


        @self.app.get('/<project>/getConfig')
        @self.app.post('/<project>/getConfig')
        def get_project_configuration(project):
            if not self.loginCheck(project=project):
                abort(401, 'forbidden')
            try:
                # parse subset of configuration parameters (if provided)
                try:
                    data = request.json
                    params = data['parameters']
                except Exception:
                    params = None

                is_admin = self.loginCheck(project=project, admin=True)
                proj_data = self.middleware.getProjectInfo(project, params, is_admin)
                return { 'settings': proj_data }
            except Exception:
                abort(400, 'bad request')


        @self.app.post('/<project>/saveProjectConfiguration')
        def save_project_configuration(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                settings = request.json
                is_valid = self.middleware.updateProjectSettings(project, settings)
                if is_valid:
                    return {'success': is_valid}
                else:
                    abort(400, 'bad request')
            except Exception:
                abort(400, 'bad request')


        @self.app.post('/<project>/saveClassDefinitions')
        def save_class_definitions(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                params = request.json
                classdef = params['classes']
                remove_missing = params.get('remove_missing', False)
                if isinstance(classdef, str):
                    # re-parse JSON (might happen in case of single quotes)
                    classdef = json.loads(classdef)
                warnings = self.middleware.updateClassDefinitions(project, classdef, remove_missing)
                return {'status': 0, 'warnings': warnings}
            except Exception as exc:
                abort(400, str(exc))


        @self.app.get('/<project>/getModelClassMapping')
        def get_model_to_project_class_mapping(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                # parse AI model state ID if provided
                ai_model_id = request.params.get('modelID', None)
                response = self.middleware.getModelToProjectClassMapping(project, ai_model_id)
                return {
                    'status': 0,
                    'response': response
                }

            except Exception as exc:
                abort(400, str(exc))


        @self.app.post('/<project>/saveModelClassMapping')
        def save_model_to_project_class_mapping(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                params = request.json
                mapping = params['mapping']
                status = self.middleware.saveModelToProjectClassMapping(project, mapping)
                return {
                    'status': status
                }

            except Exception as exc:
                abort(400, str(exc))


        @self.app.post('/<project>/renewSecretToken')
        def renew_secret_token(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')
            try:
                new_token = self.middleware.renewSecretToken(project)
                return {'secret_token': new_token}
            except Exception:
                abort(400, 'bad request')


        @self.app.get('/<project>/getUsers')
        def get_project_users(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')

            users = self.middleware.getProjectUsers(project)
            return {'users':users}


        @self.app.get('/<project>/getPermissions')
        def get_project_permissions(project):
            permissions = {
                'can_view': False,
                'can_label': False,
                'is_admin': False
            }

            is_admin = self.loginCheck(project=project, admin=True)

            # project-specific permissions
            config = self.middleware.getProjectInfo(project, None, is_admin)
            if config['demomode']:
                permissions['can_view'] = True
                permissions['can_label'] = config['interface_enabled'] and not config['archived']
            is_public = config['ispublic']
            if not is_public and not self.loginCheck(project=project):
                # pretend project does not exist (TODO: suboptimal solution; does not properly hide
                # project from view)
                abort(404, 'not found')

            # user-specific permissions
            user_privileges = self.loginCheck(project=project, return_all=True)
            if user_privileges is None or user_privileges is False:
                # user not logged in; only demo mode projects allowed
                permissions['can_view'] = config['demomode']
                permissions['can_label'] = config['demomode']
                permissions['is_admin'] = False

            elif user_privileges['logged_in']:
                permissions['can_view'] = (config['demomode'] or is_public or \
                    user_privileges['project']['enrolled'])
                permissions['can_label'] = config['interface_enabled'] and \
                    not config['archived'] and \
                        (config['demomode'] or user_privileges['project']['enrolled'])
                permissions['is_admin'] = user_privileges['project']['isAdmin']

            return {'permissions': permissions}


        @self.app.post('/<project>/setPermissions')
        def set_permissions(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                user_list = request.json['users']
                privileges = request.json['privileges']

                return self.middleware.setPermissions(project, user_list, privileges)

            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        # Project creation
        with open(os.path.abspath(
            'modules/ProjectAdministration/static/templates/newProject.html'
            ), 'r', encoding='utf-8') as f_template:
            self.new_project_template = SimpleTemplate(f_template.read())

        @self.app.route('/newProject')
        def new_project_page():
            if not self.loginCheck():
                return redirect('/')
            if not self.loginCheck(canCreateProjects=True):
                abort(401, 'forbidden')

            username = html.escape(request.get_cookie('username'))
            return self.new_project_template.render(
                version=AIDE_VERSION,
                username=username,
                data_server_uri=self.config.get_property('Server',
                                                         'dataServer_uri',
                                                         fallback='/')
            )


        @self.app.post('/createProject')
        def create_project():
            if not self.loginCheck(canCreateProjects=True):
                abort(401, 'forbidden')

            success = False
            try:
                username = html.escape(request.get_cookie('username'))

                # check provided properties
                proj_settings = request.json
                success = self.middleware.createProject(username, proj_settings)

            except Exception as exc:
                abort(400, str(exc))

            if success:
                return {'success':True}
            abort(500, 'An unknown error occurred.')



        @self.app.get('/verifyProjectName')
        def check_project_name_valid():
            if not self.loginCheck(canCreateProjects=True):
                abort(401, 'forbidden')

            try:
                proj_name = html.escape(request.query['name'])
                if len(proj_name) > 0:
                    available = self.middleware.getProjectNameAvailable(proj_name)
                else:
                    available = False
                return { 'available': available }

            except Exception:
                abort(400, 'bad request')


        @self.app.get('/verifyProjectShort')
        def check_project_shortname_valid():
            if not self.loginCheck(canCreateProjects=True):
                abort(401, 'forbidden')

            try:
                proj_name = html.escape(request.query['shorthand'])
                if len(proj_name) > 0:
                    available = self.middleware.getProjectShortNameAvailable(proj_name)
                else:
                    available = False
                return { 'available': available }

            except Exception:
                abort(400, 'bad request')


        @self.app.get('/suggestShortname')
        def suggest_shortname():
            if not self.loginCheck(canCreateProjects=True):
                abort(401, 'forbidden')
            try:
                proj_name = html.escape(request.query['name'])
                if len(proj_name) > 0:
                    shortname = self.middleware.suggest_shortname(proj_name)
                else:
                    shortname = None
                return {
                    'shortname': shortname
                }
            except Exception:
                abort(400, 'bad request')


        @self.app.get('/<project>/isArchived')
        def is_archived(project):
            if not self.loginCheck(project=project):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))
                result = self.middleware.getProjectArchived(project, username)
                return result

            except Exception:
                abort(400, 'bad request')


        @self.app.post('/<project>/setArchived')
        def set_project_archived(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))
                archived = request.json['archived']
                result = self.middleware.setProjectArchived(project, username, archived)
                return result

            except Exception:
                abort(400, 'bad request')


        @self.app.post('/<project>/deleteProject')
        def delete_project(project):
            if not self.loginCheck(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                username = html.escape(request.get_cookie('username'))

                # verify user-provided project name
                proj_name_user = request.json['projName']
                if proj_name_user != project:
                    return {
                        'status': 2,
                        'message': 'User-provided project name does not match actual project name.'
                    }
                delete_files = request.json['deleteFiles']

                result = self.middleware.deleteProject(project, username, delete_files)
                return result

            except Exception:
                abort(400, 'bad request')
