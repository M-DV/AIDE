'''
    2024 Benjamin Kellenberger
'''

from bottle import Bottle

from modules.Database.app import Database
from modules.UserHandling.app import UserHandler
from modules.TaskCoordinator.app import TaskCoordinator
from util.configDef import Config



# pylint: disable=too-few-public-methods,too-many-arguments
class Module:
    '''
        "Abstract" base class for AIDE modules.
    '''
    def __init__(self,
                 config: Config,
                 app: Bottle,
                 db_connector: Database,
                 user_handler: UserHandler,
                 task_coordinator: TaskCoordinator,
                 verbose_start: bool=False,
                 passive_mode: bool=False) -> None:
        self.config = config
        self.app = app
        self.db_connector = db_connector
        self.user_handler = user_handler
        self.task_coordinator = task_coordinator
        self.verbose_start = verbose_start
        self.passive_mode = passive_mode


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
        return self.user_handler.check_authenticated(project,
                                                     admin,
                                                     superuser,
                                                     can_create_projects,
                                                     extend_session,
                                                     return_all)
