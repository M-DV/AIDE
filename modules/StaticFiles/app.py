'''
    Serves all modules' static files from a single URL. Also contains a number of static files that
    are general to AIDE as a whole.

    2019-24 Benjamin Kellenberger
'''

import os
import json
from bottle import static_file, SimpleTemplate, HTTPResponse

from constants.version import AIDE_VERSION
from ..module import Module



class StaticFileServer(Module):
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
