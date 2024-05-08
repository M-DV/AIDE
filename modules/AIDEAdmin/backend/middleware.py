'''
    2020-24 Benjamin Kellenberger
'''

import os
import datetime
import requests
from psycopg2 import sql
# from celery import current_app

from constants.version import AIDE_VERSION, MIN_FILESERVER_VERSION, compare_versions
from util import celeryWorkerCommons
from util.logDecorator import LogDecorator
from util.helpers import is_localhost



class AdminMiddleware:
    '''
        Middleware for administrative functionalities of AIDE.
    '''
    def __init__(self, config, db_connector) -> None:
        self.config = config
        self.db_connector = db_connector


    def get_service_details(self,
                            verbose: bool=False,
                            raise_error: bool=False) -> dict:
        '''
            Queries the indicated AIController and FileServer modules for availability and their
            version. Returns metadata about the setup of AIDE accordingly. Raises an Exception if
            not running on the main host. If "verbose" is True, a warning statement is printed to
            the command line if the version of AIDE on the attached AIController and/or FileServer
            is not the same as on the host, or if the servers cannot be contacted. If "raise_error"
            is True, an Exception is being thrown at the first error occurrence.
        '''
        if verbose:
            print('Contacting AIController...'.ljust(LogDecorator.get_ljust_offset()), end='')

        # check if running on the main host
        modules = os.environ['AIDE_MODULES'].strip().split(',')
        modules = set(module.strip() for module in modules)
        if not 'LabelUI' in modules:
            # not running on main host
            raise Exception('Not a main host; cannot query service details.')

        aic_uri = self.config.get_property('Server',
                                           'aiController_uri',
                                           dtype=str,
                                           fallback=None)
        fs_uri = self.config.get_property('Server',
                                          'dataServer_uri',
                                          dtype=str,
                                          fallback=None)

        if not is_localhost(aic_uri):
            # AIController runs on a different machine; poll for version of AIDE
            try:
                aic_response = requests.get(os.path.join(aic_uri, 'version'),
                                            timeout=60)
                aic_version = aic_response.text
                if verbose and aic_version != AIDE_VERSION:
                    LogDecorator.print_status('warn')
                    print('WARNING: AIDE version of connected AIController differs from main host.')
                    print(f'\tAIController URI: {aic_uri}')
                    print(f'\tAIController AIDE version:    {aic_version}')
                    print(f'\tAIDE version on this machine: {AIDE_VERSION}')

                elif verbose:
                    LogDecorator.print_status('ok')
            except Exception as exc:
                message = f'ERROR: could not connect to AIController (message: "{str(exc)}").'
                if verbose:
                    LogDecorator.print_status('fail')
                    print(message)
                if raise_error:
                    raise Exception(message) from exc
                aic_version = None
        else:
            aic_version = AIDE_VERSION
            if verbose:
                LogDecorator.print_status('ok')

        if verbose:
            print('Contacting FileServer...'.ljust(LogDecorator.get_ljust_offset()), end='')
        if not is_localhost(fs_uri):
            # same for the file server
            try:
                fs_response = requests.get(os.path.join(fs_uri, 'version'),
                                           timeout=60)
                fs_version = fs_response.text

                # check if version if recent enough
                if compare_versions(fs_version, MIN_FILESERVER_VERSION) < 0:
                    # FileServer version is too old
                    LogDecorator.print_status('fail')
                    print('ERROR: AIDE version of connected FileServer is too old.')
                    print(f'\tMinimum required version:    {MIN_FILESERVER_VERSION}')
                    print(f'\tCurrent FileServer version:  {fs_version}')

                if verbose and fs_version != AIDE_VERSION:
                    LogDecorator.print_status('warn')
                    print('WARNING: AIDE version of connected FileServer differs from main host.')
                    print(f'\tFileServer URI: {fs_uri}')
                    print(f'\tFileServer AIDE version:      {fs_version}')
                    print(f'\tAIDE version on this machine: {AIDE_VERSION}')
                elif verbose:
                    LogDecorator.print_status('ok')
            except Exception as exc:
                message = f'ERROR: could not connect to FileServer (message: "{str(exc)}").'
                if verbose:
                    LogDecorator.print_status('fail')
                    print(message)
                if raise_error:
                    raise Exception(message) from exc
                fs_version = None
        else:
            fs_version = AIDE_VERSION
            if verbose:
                LogDecorator.print_status('ok')

        # query database
        if verbose:
            print('Contacting Database...'.ljust(LogDecorator.get_ljust_offset()), end='')
        db_version = None
        db_info = None
        try:
            db_version = self.db_connector.execute('SHOW server_version;',
                                                   None,
                                                   1)[0]['server_version']
            db_version = db_version.split(' ')[0].strip()
            db_info = self.db_connector.execute('SELECT version() AS version;',
                                                None,
                                                1)[0]['version']
            if verbose:
                LogDecorator.print_status('ok')
        except Exception as exc:
            message = f'ERROR: database version ("{str(db_version)}") could not be parsed properly.'
            if verbose:
                LogDecorator.print_status('warn')
                print(message)
            if raise_error:
                raise Exception(message) from exc

        return {
                'aide_version': AIDE_VERSION,
                'AIController': {
                    'uri': aic_uri,
                    'aide_version': aic_version
                },
                'FileServer': {
                    'uri': fs_uri,
                    'aide_version': fs_version
                },
                'Database': {
                    'version': db_version,
                    'details': db_info
                }
            }


    def get_celery_worker_details(self) -> dict:
        '''
            Queries all Celery workers for their details (name, URL, capabilities, AIDE version,
            etc.)
        '''
        return celeryWorkerCommons.get_celery_worker_details()


    def get_project_details(self) -> dict:
        '''
            Returns projects and statistics about them (number of images, disk usage, etc.).
        '''

        # get all projects
        projects = {}
        response = self.db_connector.execute('''
                SELECT shortname, name, owner, annotationtype, predictiontype,
                    ispublic, demomode, ai_model_enabled, interface_enabled, archived,
                    COUNT(username) AS num_users
                FROM aide_admin.project AS p
                JOIN aide_admin.authentication AS auth
                ON p.shortname = auth.project
                GROUP BY shortname
            ''', None, 'all')

        for res in response:
            proj_def = {}
            for key in res.keys():
                if key == 'interface_enabled':
                    proj_def[key] = res['interface_enabled'] and not res['archived']
                if key != 'shortname':
                    proj_def[key] = res[key]
            projects[res['shortname']] = proj_def

        # get statistics (number of annotations, predictions, prediction models, etc.)
        for p_key, project in projects.items():
            stats = self.db_connector.execute(sql.SQL('''
                    SELECT COUNT(*) AS count
                    FROM {id_img}
                    UNION ALL
                    SELECT COUNT(*)
                    FROM {id_anno}
                    UNION ALL
                    SELECT COUNT(*)
                    FROM {id_pred}
                    UNION ALL
                    SELECT SUM(viewcount)
                    FROM {id_iu}
                    UNION ALL
                    SELECT COUNT(*)
                    FROM {id_cnnstate}
                ''').format(
                    id_img=sql.Identifier(p_key, 'image'),
                    id_anno=sql.Identifier(p_key, 'annotation'),
                    id_pred=sql.Identifier(p_key, 'prediction'),
                    id_iu=sql.Identifier(p_key, 'image_user'),
                    id_cnnstate=sql.Identifier(p_key, 'cnnstate')
                ), None, 'all')
            project['num_img'] = stats[0]['count']
            project['num_anno'] = stats[1]['count']
            project['num_pred'] = stats[2]['count']
            project['total_viewcount'] = stats[3]['count']
            project['num_cnnstates'] = stats[4]['count']

            # time statistics (last viewed)
            stats = self.db_connector.execute(sql.SQL('''
                SELECT MIN(first_checked) AS first_checked,
                    MAX(last_checked) AS last_checked
                FROM {id_iu};
            ''').format(
                id_iu=sql.Identifier(p_key, 'image_user')
            ), None, 1)
            try:
                project['first_checked'] = stats[0]['first_checked'].timestamp()
            except Exception:
                project['first_checked'] = None
            try:
                project['last_checked'] = stats[0]['last_checked'].timestamp()
            except Exception:
                project['last_checked'] = None

        return projects


    def get_user_details(self) -> dict:
        '''
            Returns details about the user (name, number of enrolled projects, last activity, etc.).
        '''
        users = {}
        user_data = self.db_connector.execute('''
                SELECT name, email, isSuperUser, canCreateProjects,
                    last_login, project, isAdmin, admitted_until, blocked_until
                FROM aide_admin.user AS u
                LEFT OUTER JOIN aide_admin.authentication AS auth
                ON u.name = auth.username
            ''', None, 'all')
        for ud in user_data:
            if not ud['name'] in users:
                users[ud['name']] = {
                    'email': ud['email'],
                    'canCreateProjects': ud['cancreateprojects'],
                    'isSuperUser': ud['issuperuser'],
                    'last_login': (None if ud['last_login'] is None \
                                   else ud['last_login'].timestamp()),
                    'enrolled_projects': {}
                }
                if ud['project'] is not None:
                    admitted_until = ud['admitted_until']
                    if isinstance(admitted_until, datetime.datetime):
                        admitted_until = admitted_until.timestamp()
                    blocked_until = ud['admitted_until']
                    if isinstance(blocked_until, datetime.datetime):
                        blocked_until = blocked_until.timestamp()
                    users[ud['name']]['enrolled_projects'][ud['project']] = {
                        'admitted_until': admitted_until,
                        'blocked_until': blocked_until
                    }
        return users


    def set_can_create_projects(self,
                                username: str,
                                allow_create_projects: bool) -> dict:
        '''
            Sets or unsets the flag on whether a user can create new projects or not.
        '''
        # check if user exists
        user_exists = self.db_connector.execute('''
            SELECT * FROM aide_admin.user
            WHERE name = %s;
        ''', (username,), 1)
        if len(user_exists) == 0:
            return {
                'success': False,
                'message': f'User with name "{username}" does not exist.'
            }

        result = self.db_connector.execute('''
            UPDATE aide_admin.user
            SET cancreateprojects = %s
            WHERE name = %s;
            SELECT cancreateprojects
            FROM aide_admin.user
            WHERE name = %s;
        ''', (allow_create_projects, username, username), 1)
        result = result[0]['cancreateprojects']
        return {
            'success': (result == allow_create_projects)
        }
        