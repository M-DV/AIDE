'''
    Middleware for administrative functionalities
    of AIDE.

    2020-24 Benjamin Kellenberger
'''

import os
import datetime
import requests
from psycopg2 import sql
from celery import current_app
from constants.version import AIDE_VERSION, MIN_FILESERVER_VERSION, compare_versions
from util import celeryWorkerCommons
from util.logDecorator import LogDecorator
from util.helpers import is_localhost


class AdminMiddleware:

    def __init__(self, config, dbConnector):
        self.config = config
        self.dbConnector = dbConnector


    def getServiceDetails(self, verbose=False, raise_error=False):
        '''
            Queries the indicated AIController and FileServer
            modules for availability and their version. Returns
            metadata about the setup of AIDE accordingly.
            Raises an Exception if not running on the main host.
            If "verbose" is True, a warning statement is printed
            to the command line if the version of AIDE on the attached
            AIController and/or FileServer is not the same as on the
            host, or if the servers cannot be contacted.
            If "raise_error" is True, an Exception is being thrown at
            the first error occurrence.
        '''
        if verbose:
            print('Contacting AIController...'.ljust(LogDecorator.get_ljust_offset()), end='')

        # check if running on the main host
        modules = os.environ['AIDE_MODULES'].strip().split(',')
        modules = set([m.strip() for m in modules])
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
                aic_response = requests.get(os.path.join(aic_uri, 'version'))
                aic_version = aic_response.text
                if verbose and aic_version != AIDE_VERSION:
                    LogDecorator.print_status('warn')
                    print('WARNING: AIDE version of connected AIController differs from main host.')
                    print(f'\tAIController URI: {aic_uri}')
                    print(f'\tAIController AIDE version:    {aic_version}')
                    print(f'\tAIDE version on this machine: {AIDE_VERSION}')
                
                elif verbose:
                    LogDecorator.print_status('ok')
            except Exception as e:
                message = f'ERROR: could not connect to AIController (message: "{str(e)}").'
                if verbose:
                    LogDecorator.print_status('fail')
                    print(message)
                if raise_error:
                    raise Exception(message)
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
                fs_response = requests.get(os.path.join(fs_uri, 'version'))
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
                    print(f'\tFileServer AIDE version:       {fs_version}')
                    print(f'\tAIDE version on this machine: {AIDE_VERSION}')
                elif verbose:
                    LogDecorator.print_status('ok')
            except Exception as e:
                message = f'ERROR: could not connect to FileServer (message: "{str(e)}").'
                if verbose:
                    LogDecorator.print_status('fail')
                    print(message)
                if raise_error:
                    raise Exception(message)
                fs_version = None
        else:
            fs_version = AIDE_VERSION
            if verbose:
                LogDecorator.print_status('ok')

        # query database
        if verbose:
            print('Contacting Database...'.ljust(LogDecorator.get_ljust_offset()), end='')
        dbVersion = None
        dbInfo = None
        try:
            dbVersion = self.dbConnector.execute('SHOW server_version;', None, 1)[0]['server_version']
            dbVersion = dbVersion.split(' ')[0].strip()
            dbInfo = self.dbConnector.execute('SELECT version() AS version;', None, 1)[0]['version']
            if verbose:
                LogDecorator.print_status('ok')
        except Exception as e:
            message = f'ERROR: database version ("{str(dbVersion)}") could not be parsed properly.'
            if verbose:
                LogDecorator.print_status('warn')
                print(message)
            if raise_error:
                raise Exception(message)

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
                    'version': dbVersion,
                    'details': dbInfo
                }
            }

    
    def getCeleryWorkerDetails(self):
        '''
            Queries all Celery workers for their details (name,
            URL, capabilities, AIDE version, etc.)
        '''
        return celeryWorkerCommons.getCeleryWorkerDetails()



    def getProjectDetails(self):
        '''
            Returns projects and statistics about them
            (number of images, disk usage, etc.).
        '''

        # get all projects
        projects = {}
        response = self.dbConnector.execute('''
                SELECT shortname, name, owner, annotationtype, predictiontype,
                    ispublic, demomode, ai_model_enabled, interface_enabled, archived,
                    COUNT(username) AS num_users
                FROM aide_admin.project AS p
                JOIN aide_admin.authentication AS auth
                ON p.shortname = auth.project
                GROUP BY shortname
            ''', None, 'all')

        for r in response:
            projDef = {}
            for key in r.keys():
                if key == 'interface_enabled':
                    projDef[key] = r['interface_enabled'] and not r['archived']
                if key != 'shortname':
                    projDef[key] = r[key]
            projects[r['shortname']] = projDef
        
        # get statistics (number of annotations, predictions, prediction models, etc.)
        for project in projects.keys():
            stats = self.dbConnector.execute(sql.SQL('''
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
                    id_img=sql.Identifier(project, 'image'),
                    id_anno=sql.Identifier(project, 'annotation'),
                    id_pred=sql.Identifier(project, 'prediction'),
                    id_iu=sql.Identifier(project, 'image_user'),
                    id_cnnstate=sql.Identifier(project, 'cnnstate')
                ), None, 'all')
            projects[project]['num_img'] = stats[0]['count']
            projects[project]['num_anno'] = stats[1]['count']
            projects[project]['num_pred'] = stats[2]['count']
            projects[project]['total_viewcount'] = stats[3]['count']
            projects[project]['num_cnnstates'] = stats[4]['count']

            # time statistics (last viewed)
            stats = self.dbConnector.execute(sql.SQL('''
                SELECT MIN(first_checked) AS first_checked,
                    MAX(last_checked) AS last_checked
                FROM {id_iu};
            ''').format(
                id_iu=sql.Identifier(project, 'image_user')
            ), None, 1)
            try:
                projects[project]['first_checked'] = stats[0]['first_checked'].timestamp()
            except Exception:
                projects[project]['first_checked'] = None
            try:
                projects[project]['last_checked'] = stats[0]['last_checked'].timestamp()
            except Exception:
                projects[project]['last_checked'] = None

        return projects


    def getUserDetails(self):
        '''
            Returns details about the user (name, number of
            enrolled projects, last activity, etc.).
        '''
        users = {}
        userData = self.dbConnector.execute('''
                SELECT name, email, isSuperUser, canCreateProjects,
                    last_login, project, isAdmin, admitted_until, blocked_until
                FROM aide_admin.user AS u
                LEFT OUTER JOIN aide_admin.authentication AS auth
                ON u.name = auth.username
            ''', None, 'all')
        for ud in userData:
            if not ud['name'] in users:
                users[ud['name']] = {
                    'email': ud['email'],
                    'canCreateProjects': ud['cancreateprojects'],
                    'isSuperUser': ud['issuperuser'],
                    'last_login': (None if ud['last_login'] is None else ud['last_login'].timestamp()),
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


    def setCanCreateProjects(self, username, allowCreateProjects):
        '''
            Sets or unsets the flag on whether a user
            can create new projects or not.
        '''
        # check if user exists
        userExists = self.dbConnector.execute('''
            SELECT * FROM aide_admin.user
            WHERE name = %s;
        ''', (username,), 1)
        if not len(userExists):
            return {
                'success': False,
                'message': f'User with name "{username}" does not exist.'
            }
        
        result = self.dbConnector.execute('''
            UPDATE aide_admin.user
            SET cancreateprojects = %s
            WHERE name = %s;
            SELECT cancreateprojects
            FROM aide_admin.user
            WHERE name = %s;
        ''', (allowCreateProjects, username, username), 1)
        result = result[0]['cancreateprojects']
        return {
            'success': (result == allowCreateProjects)
        }
        