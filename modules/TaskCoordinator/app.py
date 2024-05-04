'''
    Module responsible for Celery task status polling of various other modules that make use of the
    message queue system.

    2020-24 Benjamin Kellenberger
'''

from bottle import request, abort
from .backend.middleware import TaskCoordinatorMiddleware


class TaskCoordinator:

    def __init__(self, config, app, db_connector):
        self.config = config
        self.app = app
        self.middleware = TaskCoordinatorMiddleware(self.config, db_connector)

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

        ''' Status polling '''
        @self.app.post('/<project>/pollStatus')
        def poll_status_project(project):
            '''
                Receives a task ID and polls the middleware
                for an ongoing data administration task.
                Returns a dict with (meta-) data, including
                the Celery status type, result (if completed),
                error message (if failed), etc.
            '''
            if not self.login_check(project=project, admin=True):
                abort(401, 'forbidden')

            try:
                task_id = request.json.get('taskID', None)
                status = self.middleware.poll_task_status(project, task_id)
                return {'response': status}

            except Exception as exc:
                abort(400, str(exc))


        #TODO:
        # @self.app.post('/allTaskStatuses')
        # def poll_status_tasks():
        #     '''
        #         Returns the status of all running tasks.
        #         Only accessible to super users.
        #     '''
        #     if not self.loginCheck(superuser=True):
        #         abort(401, 'forbidden')
    
        #     try:
        #         status = self.middleware.poll_task_status(None, None)
        #         return {'response': status}
        #     except Exception as e:
        #         abort(400, str(e))



    def submit_task(self, project, username, process, queue):
        return self.middleware.submit_task(project, username, process, queue)


    def poll_task_status(self, project, task_id):
        return self.middleware.poll_task_status(project, task_id)


    def poll_task_type(self, project, task_name, running_only=True):
        return self.middleware.poll_task_type(project, task_name, running_only)
