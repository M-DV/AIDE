'''
    Bottle routings for labeling statistics of project, including per-user analyses and progress.

    2019-24 Benjamin Kellenberger
'''

import html
from bottle import request, static_file, abort

from util.helpers import parse_boolean
from .backend.middleware import ProjectStatisticsMiddleware
from ..module import Module



class ProjectStatistics(Module):
    '''
        Entry point for statistics about a project (user progress, performance, etc.).
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

        self.static_dir = 'modules/ProjectStatistics/static'
        self.middleware = ProjectStatisticsMiddleware(config, db_connector)

        self._init_bottle()


    def _init_bottle(self):

        @self.app.route('/statistics/<filename:re:.*>') #TODO: /statistics/static/ is ignored by Bottle...
        def send_static(filename):
            return static_file(filename, root=self.static_dir)


        @self.app.get('/<project>/getProjectStatistics')
        def get_project_statistics(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            
            stats = self.middleware.getProjectStatistics(project)
            return { 'statistics': stats }


        @self.app.get('/<project>/getLabelclassStatistics')
        def get_labelclass_statistics(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            
            stats = self.middleware.getLabelclassStatistics(project)
            return { 'statistics': stats }


        @self.app.post('/<project>/getPerformanceStatistics')
        def get_user_statistics(project):
            # pylint: disable=no-member

            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                params = request.json
                entities_eval = params['entities_eval']
                entity_target = params['entity_target']
                entityType = params['entity_type']
                threshold = params.get('threshold', None)
                goldenQuestionsOnly = params.get('goldenQuestionsOnly', False)

                stats = self.middleware.getPerformanceStatistics(project, entities_eval, entity_target, entityType, threshold, goldenQuestionsOnly)

                return {
                    'status': 0,
                    'result': stats
                }

            except Exception as e:
                return {
                    'status': 1,
                    'message': str(e)
                }


        
        @self.app.post('/<project>/getUserAnnotationSpeeds')
        def get_user_annotation_speeds(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            
            userList = request.json['users']
            if 'goldenQuestionsOnly' in request.json:
                goldenQuestionsOnly = request.json['goldenQuestionsOnly']
            else:
                goldenQuestionsOnly = False
            
            stats = self.middleware.getUserAnnotationSpeeds(project, userList, goldenQuestionsOnly)
            
            return { 'result': stats }


        @self.app.get('/<project>/getUserFinished')
        def get_user_finished(project):
            if not self.login_check(project=project):
                abort(401, 'forbidden')
            
            try:
                username = html.escape(request.get_cookie('username'))
                done = self.middleware.getUserFinished(project, username)
            except Exception:
                done = False
            return {'finished': done}


        @self.app.get('/<project>/getTimeActivity')
        def get_time_activity(project):
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')
            
            try:
                try:
                    type = request.query['type']
                except Exception:
                    type = 'image'
                try:
                    numDaysMax = request.query['num_days']
                except Exception:
                    numDaysMax = 31
                try:
                    perUser = parse_boolean(request.query['per_user'])
                except Exception:
                    perUser = False
                stats = self.middleware.getTimeActivity(project, type, numDaysMax, perUser)
                return {'result': stats}
            except Exception as e:
                abort(401, str(e))