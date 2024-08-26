'''
    Main Bottle and routings for the LabelUI web frontend.

    2019-24 Benjamin Kellenberger
'''

import os
import html
from uuid import UUID
import bottle
from bottle import request, response, abort, SimpleTemplate

from constants.version import AIDE_VERSION
from util.logDecorator import LogDecorator
from util.helpers import parse_boolean
from ..module import Module
from .backend.middleware import DBMiddleware



class LabelUI(Module):
    '''
        Label UI frontend main entry point.
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

        if self.verbose_start:
            print('LabelUI'.ljust(LogDecorator.get_ljust_offset()), end='')

        try:
            self.middleware = DBMiddleware(config, db_connector)

            self._init_bottle()
        except Exception as exc:
            if self.verbose_start:
                LogDecorator.print_status('fail')
            raise Exception(f'Could not launch LabelUI (message: "{str(exc)}").') from exc

        if self.verbose_start:
            LogDecorator.print_status('ok')


    def __redirect_login_page(self, redirect: str=None) -> response:
        location = '/login'
        if redirect is not None:
            location += '?redirect=' + redirect
        response_obj = bottle.response
        response_obj.status = 303
        response_obj.set_header('Location', location)
        return response_obj


    def __redirect_project_page(self, project: str) -> response:
        response_obj = bottle.response
        response_obj.status = 303
        #TODO: add project once loopback is resolved and project page initiated
        response_obj.set_header('Location', '/')
        return response_obj


    # pylint: disable=too-many-locals,too-many-statements
    def _init_bottle(self):

        with open(os.path.abspath(os.path.join('modules/LabelUI/static/templates/interface.html')),
                  'r',
                  encoding='utf-8') as f_template:
            self.interface_template = SimpleTemplate(f_template.read())

        @self.app.route('/<project>/interface')
        def interface(project: str) -> response:
            # check if user logged in
            if not self.login_check(project=project):
                return self.__redirect_login_page(f'{project}/interface')

            # get project data (and check if project exists)
            project_data = self.middleware.get_project_info(project)
            if project_data is None:
                return self.__redirect_login_page('/')

            # check if user authenticated for project
            if not self.login_check(project=project, extend_session=True):
                return self.__redirect_login_page(f'{project}/interface')

            # redirect to project page if interface not enabled
            if not project_data['interface_enabled']:
                return self.__redirect_project_page(project)

            # render interface template
            username = html.escape(request.get_cookie('username', ''))
            return self.interface_template.render(username=username,
                                                  version=AIDE_VERSION,
                                                  projectShortname=project,
                                                  projectTitle=project_data['projectName'],
                                                  projectDescr=project_data['projectDescription'])


        @self.app.get('/<project>/getProjectInfo')
        def get_project_info(project: str) -> response:
            # minimum info (name, description) that can be viewed without logging in
            return {'info': self.middleware.get_project_info(project)}


        @self.app.get('/<project>/getProjectSettings')
        def get_project_settings(project: str) -> response:
            if not self.login_check(project=project):
                abort(401, 'not logged in')
            settings = {
                'settings': self.middleware.get_project_settings(project)
            }
            return settings


        @self.app.get('/<project>/getClassDefinitions')
        def get_class_definitions(project: str) -> response:
            if not self.login_check(project=project):
                abort(401, 'not logged in')

            # pylint: disable=no-member
            show_hidden = parse_boolean(request.params.get('show_hidden', False))
            class_defs = {
                'classes': self.middleware.get_class_definitions(project, show_hidden)
            }
            return class_defs


        @self.app.post('/<project>/getImages')
        def get_images(project: str) -> response:
            if not self.login_check(project=project):
                abort(401, 'not logged in')
            hide_golden_question_info = not self.login_check(project=project, admin=True)

            username = html.escape(request.get_cookie('username', ''))
            data_ids = request.json['imageIDs']
            json = self.middleware.get_batch_fixed(project,
                                                   username,
                                                   data_ids,
                                                   hide_golden_question_info)
            return json


        @self.app.get('/<project>/getLatestImages')
        def get_latest_images(project: str) -> response:
            if not self.login_check(project=project):
                abort(401, 'not logged in')
            hide_golden_questions = not self.login_check(project=project, admin=True)

            username = html.escape(request.get_cookie('username', ''))
            try:
                limit = int(request.query['limit'])
            except Exception:
                limit = None
            try:
                order = int(request.query['order'])
            except Exception:
                order = 'unlabeled'
            try:
                subset = int(request.query['subset'])
            except Exception:
                subset = 'default'
            batch = self.middleware.get_batch_auto(project=project,
                                                   username=username,
                                                   order=order,
                                                   subset=subset,
                                                   limit=limit,
                                                   hide_golden_question_info=hide_golden_questions)

            return batch


        @self.app.post('/<project>/getImages_timestamp')
        def get_images_timestamp(project: str) -> response:
            # pylint: disable=no-member

            if not self.login_check(project=project):
                abort(401, 'unauthorized')

            # check if user requests to see other user names; only permitted if admin
            # also, by default we limit labels to the current user, even for admins, to provide a
            # consistent experience.
            username = html.escape(request.get_cookie('username'))
            try:
                users = request.json['users']
                if len(users) == 0:
                    users = [username]
            except Exception:
                users = [username]

            if not self.login_check(project=project, admin=True):
                # user no admin: can only query their own labels
                users = [username]
                hide_golden_question_info = True

            elif not self.login_check(project=project):
                # not logged in, resp. not authorized for project
                abort(401, 'unauthorized')

            else:
                hide_golden_question_info = False

            timestamp_min = request.json.get('minTimestamp', None)
            timestamp_max = request.json.get('maxTimestamp', None)
            skip_empty = request.json.get('skipEmpty', False)
            limit = request.json.get('limit', None)
            golden_questions_only = request.json.get('goldenQuestionsOnly', False)
            last_img_uuid = request.json.get('lastImageUUID', None)

            # query and return
            batch = self.middleware.get_batch_time_range(project,
                                                       timestamp_min,
                                                       timestamp_max,
                                                       users,
                                                       skip_empty,
                                                       limit,
                                                       golden_questions_only,
                                                       hide_golden_question_info,
                                                       last_img_uuid)
            return batch


        @self.app.post('/<project>/getTimeRange')
        def get_time_range(project: str) -> dict:
            if not self.login_check(project=project):
                abort(401, 'unauthorized')

            username = html.escape(request.get_cookie('username'))

            # check if user requests to see other user names; only permitted if admin
            # pylint: disable=no-member
            users = request.json.get('users', [username])

            if not self.login_check(project=project, admin=True):
                # user no admin: can only query their own labels
                users = [username]

            skip_empty = request.json.get('skipEmpty', False)
            golden_questions_only = request.json.get('goldenQuestionsOnly', False)

            # query and return
            time_range = self.middleware.get_time_range(project,
                                                       users,
                                                       skip_empty,
                                                       golden_questions_only)
            return time_range


        @self.app.get('/<project>/getImageCardinalDirection')
        def get_images_cardinal_direction(project: str) -> response:
            # pylint: disable=no-member

            if not self.login_check(project=project):
                abort(401, 'unauthorized')

            # check if user requests to see other user names; only permitted if admin
            # also, by default we limit labels to the current user, even for admins, to provide a
            # consistent experience.
            username = html.escape(request.get_cookie('username'))

            if not self.login_check(project=project, admin=True):
                # user no admin: can only query their own labels
                hide_golden_question_info = True

            elif not self.login_check(project=project):
                # not logged in, resp. not authorized for project
                abort(401, 'unauthorized')

            else:
                hide_golden_question_info = False

            current_image_id = request.query.get('ci', None)
            cardinal_direction = request.query.get('cd', None)

            # query and return
            batch = self.middleware.get_image_cardinal_direction(project,
                                                                 username,
                                                                 current_image_id,
                                                                 cardinal_direction,
                                                                 hide_golden_question_info)
            return batch


        @self.app.get('/<project>/getSampleData')
        @self.app.post('/<project>/getSampleData')
        def get_sample_data(project: str) -> dict:
            if not self.login_check(project=project):
                abort(401, 'not logged in')
            sample_data = self.middleware.get_sample_data(project)
            return sample_data


        @self.app.post('/<project>/submitAnnotations')
        def submit_annotations(project: str) -> dict:
            if not self.login_check(project=project):
                abort(401, 'not logged in')
            try:
                username = html.escape(request.get_cookie('username'))
                if username is None:
                    # 100% failsafety for projects in demo mode
                    raise ValueError('no username provided')
                submission = request.json
                status = self.middleware.submit_annotations(project,
                                                           username,
                                                           submission)
                return { 'status': status }
            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        @self.app.get('/<project>/getGoldenQuestions')
        def get_golden_questions(project: str) -> dict:
            if not self.login_check(project=project, admin=True):
                abort(403, 'forbidden')
            try:
                return self.middleware.get_golden_questions(project)
            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }


        @self.app.post('/<project>/setGoldenQuestions')
        def set_golden_questions(project: str) -> dict:
            if not self.login_check(project=project, admin=True):
                abort(403, 'forbidden')
            # parse and check validity of submissions
            submissions = request.json
            try:
                submissions = submissions['goldenQuestions']
                if not isinstance(submissions, dict):
                    abort(400, 'malformed submissions')
                submissions_ = []
                for key in submissions.keys():
                    submissions_.append(tuple((UUID(key), bool(submissions[key]),)))
            except Exception:
                abort(400, 'malformed submissions')

            return self.middleware.set_golden_questions(project, tuple(submissions_))


        @self.app.get('/<project>/getBookmarks')
        def get_bookmarks(project: str) -> dict:
            if not self.login_check(project=project):
                abort(403, 'forbidden')
            try:
                username = html.escape(request.get_cookie('username'))
                if username is None:
                    abort(403, 'forbidden')
                return self.middleware.get_bookmarks(project, username)
            except Exception as e:
                return {
                    'status': 1,
                    'message': str(e)
                }


        @self.app.post('/<project>/setBookmark')
        def set_bookmark(project: str) -> dict:
            if not self.login_check(project=project):
                abort(403, 'forbidden')
            try:
                username = html.escape(request.get_cookie('username', ''))
                if len(username.strip()) == 0:
                    # 100% failsafety for projects in demo mode
                    raise ValueError('no username provided')

                bookmarks = request.json['bookmarks']
                return self.middleware.set_bookmarks(project,
                                                     username,
                                                     bookmarks)
            except Exception as exc:
                return {
                    'status': 1,
                    'message': str(exc)
                }
