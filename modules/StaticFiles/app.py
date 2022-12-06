'''
    Serves all modules' static files from a single URL.
    Also contains a number of static files that are general
    to AIDE as a whole.

    2019-21 Benjamin Kellenberger
'''

import os
import json
import requests
from bottle import static_file, abort, SimpleTemplate
from constants.version import AIDE_VERSION
from util.helpers import is_localhost


class StaticFileServer:

    MODULE_ROUTINGS = {
        'general': 'modules/StaticFiles/static',
        'interface': 'modules/LabelUI/static',
        'reception': 'modules/Reception/static',
        'dataAdmin': 'modules/DataAdministration/static',
        'projectAdmin': 'modules/ProjectAdministration/static',
        'statistics': 'modules/ProjectStatistics/static',
        'aiController': 'modules/AIController/static'
    }

    def __init__(self, config, app, dbConnector, verbose_start=False):
        self.config = config
        self.app = app

        self.login_check = None
        self._initBottle()


    def loginCheck(self, project=None, admin=False, superuser=False, canCreateProjects=False, extend_session=False):
        return self.login_check(project, admin, superuser, canCreateProjects, extend_session)


    def addLoginCheckFun(self, loginCheckFun):
        self.login_check = loginCheckFun

    
    def _initBottle(self):

        @self.app.route('/version')
        def aide_version():
            return AIDE_VERSION
            

        @self.app.route('/favicon.ico')
        def favicon():
            return static_file('favicon.ico', root='modules/StaticFiles/static/img')

        with open(os.path.abspath(os.path.join('modules/StaticFiles/static/templates/about.html')), 'r', encoding='utf-8') as f:
            self.aboutPage = SimpleTemplate(f.read())

        with open(os.path.abspath(os.path.join('modules/StaticFiles/static/templates/privacy.html')), 'r', encoding='utf-8') as f:
            self.privacyPage = SimpleTemplate(f.read())

        @self.app.route('/about')
        @self.app.route('/<project>/about')
        def about(project=None):
            return self.aboutPage.render(version=AIDE_VERSION)

        
        @self.app.route('/privacy')
        @self.app.route('/<project>/privacy')
        def privacy(project=None):
            return self.privacyPage.render(version=AIDE_VERSION)


        @self.app.get('/getBackdrops')
        def get_backdrops():
            try:
                return {'info': json.load(open('modules/StaticFiles/static/img/backdrops/backdrops.json', 'r'))}
            except Exception:
                abort(500)


        @self.app.route('/static/<module>/<filename:re:.*>')
        def send_static(module, filename):
            return static_file(filename, self.MODULE_ROUTINGS[module])

        #TODO: can be removed
        @self.app.route('/<project>/static/<module>/<filename:re:.*>')
        def send_static_proj(project, module, filename):
            return send_static(module, filename)