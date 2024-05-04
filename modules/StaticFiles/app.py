'''
    Serves all modules' static files from a single URL. Also contains a number of static files that
    are general to AIDE as a whole.

    2019-24 Benjamin Kellenberger
'''

import os
import json
from bottle import static_file, abort, SimpleTemplate, HTTPResponse
from constants.version import AIDE_VERSION


class StaticFileServer:
    '''
        Entry point for frontend for serving static files (scripts, images, etc.) regarding all the
        modules.
    '''

    MODULE_ROUTINGS = {
        'general': 'modules/StaticFiles/static',
        'interface': 'modules/LabelUI/static',
        'reception': 'modules/Reception/static',
        'dataAdmin': 'modules/DataAdministration/static',
        'projectAdmin': 'modules/ProjectAdministration/static',
        'statistics': 'modules/ProjectStatistics/static',
        'taskCoordinator': 'modules/TaskCoordinator/static',
        'aiController': 'modules/AIController/static'
    }

    def __init__(self, config, app, dbConnector, verbose_start=False):
        self.config = config
        self.app = app

        self.login_check_fun = None

        with open(os.path.abspath('modules/StaticFiles/static/templates/about.html'),
                  'r',
                  encoding='utf-8') as f_about:
            self.about_page = SimpleTemplate(f_about.read())

        with open(os.path.abspath('modules/StaticFiles/static/templates/privacy.html'),
                  'r',
                  encoding='utf-8') as f_privacy:
            self.privacy_page = SimpleTemplate(f_privacy.read())

        with open('modules/StaticFiles/static/img/backdrops/backdrops.json',
                  'r',
                  encoding='utf-8') as f_backdrops:
            self.backdrops = json.load(f_backdrops)

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


    def _init_bottle(self) -> None:

        @self.app.route('/version')
        def aide_version() -> str:
            return AIDE_VERSION


        @self.app.route('/favicon.ico')
        def favicon() -> HTTPResponse:
            return static_file('favicon.ico', root='modules/StaticFiles/static/img')


        @self.app.route('/about')
        @self.app.route('/<project>/about')
        def about(**_: dict) -> str:
            return self.about_page.render(version=AIDE_VERSION)


        @self.app.route('/privacy')
        @self.app.route('/<project>/privacy')
        def privacy(**_: dict) -> str:
            return self.privacy_page.render(version=AIDE_VERSION)


        @self.app.get('/getBackdrops')
        def get_backdrops() -> dict:
            return {'info': self.backdrops}


        @self.app.route('/static/<module>/<filename:re:.*>')
        def send_static(module: str, filename: str) -> HTTPResponse:
            return static_file(filename, self.MODULE_ROUTINGS[module])

        #TODO: can be removed
        @self.app.route('/<project>/static/<module>/<filename:re:.*>')
        def send_static_proj(project: str,
                             module: str,
                             filename: str) -> HTTPResponse:
            return send_static(module, filename)
