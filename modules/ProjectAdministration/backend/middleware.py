'''
    Middleware layer between the project configuration front-end and the database.

    2019-24 Benjamin Kellenberger
'''

from typing import Union, Iterable, List
import os
import re
import secrets
import json
from uuid import UUID, uuid4
from datetime import datetime
import requests
from psycopg2 import sql
from bottle import request

from modules.DataAdministration.backend import celery_interface as fileServer_interface
from modules.TaskCoordinator.backend.middleware import TaskCoordinatorMiddleware
from util import helpers, common
from .db_fields import Fields_annotation, Fields_prediction



class ProjectConfigMiddleware:
    '''
        Middleware for setting up and configuring labeling projects.
    '''

    # prohibited project shortnames
    PROHIBITED_SHORTNAMES = [
        'con',  # for MS Windows
        'prn',
        'aux',
        'nul',
        'com1',
        'com2',
        'com3',
        'com4',
        'com5',
        'com6',
        'com7',
        'com8',
        'com9',
        'lpt1',
        'lpt2',
        'lpt3',
        'lpt4',
        'lpt5',
        'lpt6',
        'lpt7',
        'lpt8',
        'lpt9'
    ]

    # prohibited project names (both as a whole and for shortnames)
    PROHIBITED_NAMES = [
        '',
        'project',
        'getavailableaimodels',
        'getbackdrops',
        'verifyprojectname',
        'verifyprojectshort',
        'suggestshortname',
        'newproject',
        'createproject',
        'statistics',
        'static',
        'getcreateaccountunrestricted'
        'getprojects',
        'about',
        'favicon.ico',
        'logincheck',
        'logout',
        'login',
        'dologin',
        'createaccount',
        'loginscreen',
        'accountexists',
        'getauthentication',
        'getusernames',
        'docreateaccount',
        'admin',
        'getservicedetails',
        'getceleryworkerdetails',
        'getprojectdetails',
        'getuserdetails',
        'setpassword',
        'exec',
        'v',
        'getbandconfiguration',
        'parseCRS',
        'mapserver'
    ]

    # prohibited name prefixes
    PROHIBITED_NAME_PREFIXES = [
        '/',
        '?',
        '&'
    ]

    # patterns that are prohibited anywhere for shortnames (replaced with underscores)
    SHORTNAME_PATTERNS_REPLACE = [
        '|',
        '?',
        '*',
        ':'    # for macOS
    ]

    # patterns that are prohibited anywhere for both short and long names (no replacement)
    PROHIBITED_STRICT = [
        '&lt;',
        '<',
        '>',
        '&gt;',
        '..',
        '/',
        '\\'
    ]

    # absolute RGB component sum distance required between colors. In principle,
    # this is only important for segmentation (due to anti-aliasing effects of
    # the HTML canvas, but we apply it everywhere anyway)
    MINIMAL_COLOR_OFFSET = 9

    # default spatial reference system for image extent geometry columns (WGS84)
    DEFAULT_SRID = 4326

    def __init__(self, config, dbConnector):
        self.config = config
        self.db_connector = dbConnector

        self.project_shortname_check = re.compile('^[A-Za-z0-9_-]*')
        self.project_shortname_postgres_check = re.compile(r'(^(pg_|[0-9]).*|.*(\$|\s)+.*)')

        # load default UI settings
        try:
            # check if custom default styles are provided
            with open('config/default_ui_settings.json', 'r', encoding='utf-8') as f_settings:
                self.default_ui_settings = json.load(f_settings)
        except Exception:
            # resort to built-in styles
            with open('modules/ProjectAdministration/static/json/default_ui_settings.json',
                        'r', encoding='utf-8') as f_ui_settings:
                self.default_ui_settings = json.load(f_ui_settings)


    @staticmethod
    def _recursive_update(dict_obj: dict, target: dict) -> None:
        '''
            Recursively iterates over all keys and sub-keys of "dictObject" and its sub-dicts and
            copies over values from dict "target", if they are available.
        '''
        for key in dict_obj.keys():
            if key in target:
                if isinstance(dict_obj[key], dict):
                    ProjectConfigMiddleware._recursive_update(dict_obj[key], target[key])
                else:
                    dict_obj[key] = target[key]


    def get_platform_info(self,
                          project: str,
                          parameters: Union[Iterable[str],str]=None) -> dict:
        '''
            AIDE setup-specific platform metadata.
        '''
        # parse parameters (if provided) and compare with mutable entries
        all_params = set([
            'server_uri',
            'server_dir',
            'watch_folder_interval',
            'inference_batch_size_limit',
            'max_num_concurrent_tasks'
        ])
        if parameters is not None and parameters != '*':
            if isinstance(parameters, str):
                parameters = [parameters.lower()]
            else:
                parameters = [p.lower() for p in parameters]
            set(parameters).intersection_update(all_params)
        else:
            parameters = all_params
        parameters = list(parameters)

        # check if FileServer needs to be contacted
        server_uri = self.config.get_property('Server', 'dataServer_uri')
        server_dir = self.config.get_property('FileServer', 'staticfiles_dir')
        if 'server_dir' in parameters and not helpers.is_localhost(server_uri):
            # FileServer is remote instance; get info via URL query
            try:
                # pylint: disable=no-member
                cookies = request.cookies.dict
                for key in cookies:
                    cookies[key] = cookies[key][0]
                fs_data = requests.get(os.path.join(server_uri, 'getFileServerInfo'),
                                       cookies=cookies,
                                       timeout=180)
                fs_data = json.loads(fs_data.text)
                server_dir = fs_data['staticfiles_dir']
            except Exception as e:
                print('WARNING: an error occurred trying to query FileServer for static files ' + \
                      f'directory (message: "{str(e)}").')
                print(f'Using value provided in this instance\'s config instead ("{server_dir}").')

        response = {}
        for param in parameters:
            if param.lower() == 'server_uri':
                response[param] = os.path.join(server_uri, project, 'files')
            elif param.lower() == 'server_dir':
                response[param] = os.path.join(server_dir, project)
            elif param.lower() == 'watch_folder_interval':
                interval = self.config.get_property('FileServer',
                                                    'watch_folder_interval',
                                                    dtype=float,
                                                    fallback=60)
                response[param] = interval
            elif param.lower() == 'inference_batch_size_limit':
                inference_batch_size_limit = self.config.get_property('AIWorker',
                                                                      'inference_batch_size_limit',
                                                                      dtype=int,
                                                                      fallback=-1)
                response[param] = inference_batch_size_limit
            elif param.lower() == 'max_num_concurrent_tasks':
                max_num_concurrent_tasks = self.config.get_property('AIWorker',
                                                                    'max_num_concurrent_tasks',
                                                                    dtype=int,
                                                                    fallback=2)
                response[param] = max_num_concurrent_tasks

        return response


    def get_project_immutables(self, project: str) -> dict:
        '''
            Compatibility wrapper for main app.
        '''
        anno_type, pred_type = common.get_project_immutables(project, self.db_connector)
        if anno_type is None or pred_type is None:
            return None
        return {
            'annotationType': anno_type,
            'predictionType': pred_type
        }


    def get_project_info(self,
                         project: str,
                         parameters: Union[Iterable[str],str]=None,
                         is_admin: bool=False) -> dict:
        '''
            Returns configuration metadata for a given project.

            Args:
                - "project":    str, project shortname
                - "parameters": either an Iterable of str containing project parameters to query
                                (e.g., "name", "description", "render_config"), or else "*" to query
                                all
                - "is_admin":   bool, allows querying restricted parameters only accessible to
                                admins if True (default: False)

            Returns:
                - dict, containing parameter keys and corresponding values
        '''

        # parse parameters (if provided) and compare with mutable entries
        public_params = set([
            'name',
            'description',
            'ispublic',
            'demomode',
            'interface_enabled',
            'archived',
            'band_config',
            'render_config'
        ])
        admin_params = set([
            'annotationtype',
            'predictiontype',
            'secret_token',
            'ui_settings',
            'segmentation_ignore_unlabeled',
            'ai_model_enabled',
            'ai_model_library',
            'ai_model_settings',
            'ai_alcriterion_library',
            'ai_alcriterion_settings',
            'numimages_autotrain',
            'minnumannoperimage',
            'maxnumimages_train',
            'inference_chunk_size',
            'max_num_concurrent_tasks',
            'watch_folder_enabled',
            'watch_folder_remove_missing_enabled',
            'mapserver_settings'
        ])
        all_params = set.union(public_params, admin_params)
        if parameters is not None and parameters != '*':
            if isinstance(parameters, str):
                parameters = [parameters.lower()]
            else:
                parameters = [p.lower() for p in parameters]
            parameters = set(parameters)
            if is_admin:
                parameters.intersection_update(all_params)
            else:
                parameters.intersection_update(public_params)
        elif is_admin:
            parameters = all_params
        else:
            parameters = public_params
        if 'interface_enabled' in parameters:
            parameters.add('archived')
        parameters = list(parameters)
        sql_parameters = ','.join(parameters)

        query_str = sql.SQL('''
        SELECT {} FROM aide_admin.project
        WHERE shortname = %s;
        ''').format(
            sql.SQL(sql_parameters)
        )
        result = self.db_connector.execute(query_str, (project,), 1)
        result = result[0]

        # assemble response
        response = {}
        for param in parameters:
            value = result[param]
            if param == 'ui_settings':
                value = json.loads(value)

                # auto-complete with defaults where missing
                value = helpers.check_args(value, self.default_ui_settings)
            elif param == 'interface_enabled':
                value = value and not result['archived']
            elif param in ('band_config', 'render_config'):
                try:
                    value = json.loads(value)
                except Exception:
                    value = None
            response[param] = value

        return response


    def renew_secret_token(self, project: str) -> str:
        '''
            Creates a new secret token, invalidating the old one.
        '''
        try:
            token_new = secrets.token_urlsafe(32)
            result = self.db_connector.execute('''UPDATE aide_admin.project
                SET secret_token = %s
                WHERE shortname = %s;
                SELECT secret_token FROM aide_admin.project
                WHERE shortname = %s;
            ''', (token_new, project, project,), 1)
            return result[0]['secret_token']
        except Exception:
            # this normally should not happen, since we checked for the validity of the project
            return None


    def set_permissions(self,
                         project: str,
                         user_list: str,
                         privileges: dict) -> dict:
        '''
            Sets project permissions for a given list of user names. Permissions may be set through
            a dict of "privileges" with values and include the following privilege keywords and
            value types:

                - "isAdmin": bool
                - "blocked_until": datetime or anything else for no limit
                - "admitted_until": datetime or anything else for no limit
                - "remove": bool        # removes users from project
        '''
        user_list = [(u,) for u in user_list]

        for priv_key in privileges.keys():
            query_type = 'update'
            if priv_key.lower() == 'isadmin':
                query_val = bool(privileges[priv_key])
            elif priv_key.lower() in ('admitted_until', 'blocked_until'):
                try:
                    query_val = datetime.fromtimestamp(privileges[priv_key])
                except Exception:
                    query_val = None
            elif priv_key.lower() == 'remove':
                query_val = None
                query_type = 'remove'
            else:
                raise ValueError(f'"{priv_key}" is not a recognized privilege type.')

            if query_type == 'update':
                query_str = f'''
                    UPDATE aide_admin.authentication
                    SET {priv_key} = %s
                    WHERE username IN %s
                    AND project = %s
                    RETURNING username;
                '''
                result = self.db_connector.execute(query_str,
                                                   (query_val, tuple(user_list), project),
                                                   'all')
            else:
                query_str = '''
                    DELETE FROM aide_admin.authentication
                    WHERE username IN %s
                    AND project = %s
                    RETURNING username;
                '''
                result = self.db_connector.execute(query_str,
                                                   (tuple(user_list), project),
                                                   'all')

            if result is None or len(result) == 0:
                #TODO: provide more sophisticated error response
                return {
                    'status': 2,
                    'message': f'An error occurred while trying to set permission type "{priv_key}"'
                }

        return {
            'status': 0
        }


    def get_project_users(self, project: str) -> List[dict]:
        '''
            Returns a list of users that are enrolled in the project, as well as their roles within
            the project.
        '''

        query_str = sql.SQL('SELECT * FROM aide_admin.authentication WHERE project = %s;')
        result = self.db_connector.execute(query_str, (project,), 'all')
        response = []
        for res in result:
            user = {}
            for key, val in res.items():
                user[key] = val.timestamp() if isinstance(val, datetime) else val
            response.append(user)
        return response


    def create_project(self,
                       username: str,
                       properties: dict) -> bool:
        '''
            Receives the most basic, mostly non-changeable settings for a new project ("properties")
            with the following entries:
            
            - shortname
            - owner (the current username)
            - name
            - description
            - annotationType
            - predictionType

            More advanced settings (UI config, AI model, etc.) will be configured after the initial
            project creation stage.

            Verifies whether these settings are available for a new project. If they are, it creates
            a new database schema for the project, adds an entry for it to the admin schema table
            and makes the current user admin. Returns True in this case. Otherwise raises an
            exception.
        '''

        name, shortname = properties['name'], properties['shortname']

        # verify availability of the project name and shortname
        if not self.get_project_name_available(name):
            raise ValueError(f'Project name "{name}" unavailable.')
        if not self.get_project_shortname_available(shortname):
            raise ValueError(f'Project shortname "{shortname}" unavailable.')

        # load base SQL
        with open('modules/ProjectAdministration/static/sql/create_schema.sql',
                  'r',
                  encoding='utf-8') as f_sql:
            query_str = sql.SQL(f_sql.read())

        # determine annotation and prediction types and add fields accordingly
        fields_annotation = list(getattr(Fields_annotation, properties['annotationType']).value)
        fields_prediction = list(getattr(Fields_prediction, properties['predictionType']).value)

        # custom band configuration
        band_config = properties.get('band_config', None)
        if not isinstance(band_config, (list, tuple)):
            band_config = helpers.DEFAULT_BAND_CONFIG
        band_config = json.dumps(band_config)

        # custom render configuration
        render_config = properties.get('render_config', None)
        if isinstance(render_config, dict):
            # verify entries
            render_config = helpers.check_args(render_config, helpers.DEFAULT_RENDER_CONFIG)
        else:
            # set to default
            render_config = helpers.DEFAULT_RENDER_CONFIG
        render_config = json.dumps(render_config)

        # create project schema
        self.db_connector.execute(query_str.format(
                id_schema=sql.Identifier(shortname),
                id_auth=sql.Identifier(self.config.get_property('Database', 'user')),
                id_image=sql.Identifier(shortname, 'image'),
                id_iu=sql.Identifier(shortname, 'image_user'),
                id_bookmark=sql.Identifier(shortname, 'bookmark'),
                id_labelclassGroup=sql.Identifier(shortname, 'labelclassgroup'),
                id_labelclass=sql.Identifier(shortname, 'labelclass'),
                id_annotation=sql.Identifier(shortname, 'annotation'),
                id_cnnstate=sql.Identifier(shortname, 'cnnstate'),
                id_modellc=sql.Identifier(shortname, 'model_labelclass'),
                id_prediction=sql.Identifier(shortname, 'prediction'),
                id_workflow=sql.Identifier(shortname, 'workflow'),
                id_workflowHistory=sql.Identifier(shortname, 'workflowhistory'),
                id_filehierarchy=sql.Identifier(shortname, 'filehierarchy'),
                id_taskHistory=sql.Identifier(shortname, 'taskhistory'),
                id_tag=sql.Identifier(shortname, 'tag'),
                id_tagImage=sql.Identifier(shortname, 'tag_image'),
                annotation_fields=sql.SQL(', ').join(
                    [sql.SQL(field) for field in fields_annotation]),
                prediction_fields=sql.SQL(', ').join(
                    [sql.SQL(field) for field in fields_prediction])
            ),
            (shortname, shortname, properties.get('srid', None),),
            None
        )

        # check if schema got created
        valid = self.db_connector.execute('''
            SELECT COUNT(*) AS present
            FROM "information_schema".schemata
            WHERE schema_name = %s;
        ''', (shortname,), 1)
        if valid is None or len(valid) == 0 or valid[0]['present'] < 1:
            raise Exception(f'Project with shortname "{shortname}" could not be created.' + \
                '\nCheck for database permission errors.')

        # register project
        self.db_connector.execute('''
            INSERT INTO aide_admin.project (shortname, name, description,
                owner,
                secret_token,
                interface_enabled,
                annotationType, predictionType,
                isPublic, demoMode,
                ai_alcriterion_library,
                numImages_autotrain,
                minNumAnnoPerImage,
                maxNumImages_train,
                ui_settings,
                band_config,
                render_config)
            VALUES (
                %s, %s, %s,
                %s,
                %s,
                %s,
                %s, %s,
                %s, %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            );
            ''',
            (
                shortname,
                name,
                (properties['description'] if 'description' in properties else ''),
                username,
                secrets.token_urlsafe(32),
                False,
                properties['annotationType'],
                properties['predictionType'],
                False, False,
                #TODO: default AL criterion to facilitate auto-training
                'ai.al.builtins.maxconfidence.MaxConfidence',
                #TODO: default values for automated AI model training
                128, 0, 128,
                json.dumps(self.default_ui_settings),
                band_config,
                render_config
            ),
            None)

        # register user in project
        self.db_connector.execute('''
                INSERT INTO aide_admin.authentication (username, project, isAdmin)
                VALUES (%s, %s, true);
            ''',
            (username, shortname,),
            None)

        # notify FileServer instance(s) to set up project folders
        process = fileServer_interface.aide_internal_notify.si({
            'task': 'create_project_folders',
            'projectName': shortname
        })
        process.apply_async(queue='aide_broadcast',
                            ignore_result=True)

        return True


    def update_project_settings(self,
                                project: str,
                                project_settings: dict) -> bool:
        '''
            Receives a project shortname and dict of settings to update, performs integrity checks
            and type conversions, and updates settings in the database accordingly. Returns True if
            update has succeeded.

            Args:
                - "project":            str, project shortname
                - "project_settings":   dict, settings to update. Settings are typecast individually
                                        (e.g., "ui_settings" usually come from frontend as a JSON
                                        string and get parsed into a dict for checking).
    
            Returns:
                bool, True if update succeeded (else will raise an exception)
        '''

        # check UI settings first
        if 'ui_settings' in project_settings:
            if isinstance(project_settings['ui_settings'], str):
                project_settings['ui_settings'] = json.loads(project_settings['ui_settings'])
            field_names = [
                ('welcomeMessage', str),
                ('numImagesPerBatch', int),
                ('minImageWidth', int),
                ('numImageColumns_max', int),
                ('defaultImage_w', int),
                ('defaultImage_h', int),
                ('styles', dict),
                ('enableEmptyClass', bool),
                ('showPredictions', bool),
                ('showPredictions_minConf', float),
                ('carryOverPredictions', bool),
                ('carryOverRule', str),
                ('carryOverPredictions_minConf', float),
                ('defaultBoxSize_w', int),
                ('defaultBoxSize_h', int),
                ('minBoxSize_w', int),
                ('minBoxSize_h', int),
                ('showImageNames', bool),
                ('showImageURIs', bool)
            ]
            ui_settings_new, ui_s_keys_new = helpers.parse_parameters(
                                                                project_settings['ui_settings'],
                                                                field_names,
                                                                absent_ok=True,
                                                                escape=True)

            # adopt current settings and replace values accordingly
            ui_settings = self.db_connector.execute('''SELECT ui_settings
                    FROM aide_admin.project
                    WHERE shortname = %s;            
                ''', (project,), 1)
            ui_settings = json.loads(ui_settings[0]['ui_settings'])
            for k_idx, key_new in enumerate(ui_s_keys_new):
                if key_new not in ui_settings:
                    #TODO: may be a bit careless, as any new keywords could be added...
                    ui_settings[key_new] = ui_settings_new[k_idx]
                elif isinstance(ui_settings[key_new], dict):
                    ProjectConfigMiddleware._recursive_update(ui_settings[key_new],
                                                              ui_settings_new[k_idx])
                else:
                    ui_settings[key_new] = ui_settings_new[k_idx]

            # auto-complete with defaults where missing
            ui_settings = helpers.check_args(ui_settings, self.default_ui_settings)

            project_settings['ui_settings'] = json.dumps(ui_settings)


        # parse remaining parameters
        field_names = [
            ('description', str),
            ('isPublic', bool),
            ('secret_token', str),
            ('demoMode', bool),
            ('ui_settings', str),
            ('interface_enabled', bool),
            ('watch_folder_enabled', bool),
            ('watch_folder_remove_missing_enabled', bool),
            ('mapserver_settings', str)
        ]

        if 'mapserver_settings' in project_settings:
            project_settings['mapserver_settings'] = \
                json.dumps(project_settings['mapserver_settings'])

        vals, params = helpers.parse_parameters(project_settings,
                                                field_names,
                                                absent_ok=True,
                                                escape=False)
        vals.append(project)

        # commit to DB
        query_str = sql.SQL('''UPDATE aide_admin.project
            SET {}
            WHERE shortname = %s;
            '''
        ).format(
            sql.SQL(',').join([sql.SQL(f'{item} = %s') for item in params])
        )

        self.db_connector.execute(query_str,
                                  tuple(vals),
                                  None)

        return True


    def update_class_definitions(self,
                                 project: str,
                                 classdef: Iterable[dict],
                                 remove_missing: bool=False) -> List[str]:
        '''
            Updates the project's class definitions. if "remove_missing" is set to True, label
            classes that are present in the database, but not in "classdef," will be removed. Label
            class groups will only be removed if they do not reference any label class present in
            "classdef." This functionality is disallowed in the case of segmentation masks.
        '''

        warnings = []

        # check if project contains segmentation masks
        meta_type = self.db_connector.execute('''
                    SELECT annotationType, predictionType FROM aide_admin.project
                    WHERE shortname = %s;
                ''',
                (project,),
                1)[0]
        is_segmentation = any('segmentationmasks' in m.lower() for m in meta_type.values())
        if is_segmentation:
            # segmentation: we disallow deletion and serial idx > 255
            if remove_missing:
                warnings.append('Pixel-wise segmentation projects disallow removing label classes.')
            remove_missing = False
            lc_query = self.db_connector.execute(sql.SQL('''
                SELECT id, idx, color FROM {};
            ''').format(sql.Identifier(project, 'labelclass')), None, 'all')
            colors = dict([c['color'].lower(), c['id']] for c in lc_query)
            colors.update({         # we disallow fully black or white colors for segmentation, too
                '#000000': -1,
                '#ffffff': -1
            })

            max_idx = 0 if len(lc_query) == 0 else max(l['idx'] for l in lc_query)
        else:
            colors = {}
            max_idx = 0

        # get current classes from database
        db_classes = {}
        db_groups = {}
        query_str = sql.SQL('''
            SELECT * FROM {id_lc} AS lc
            FULL OUTER JOIN (
                SELECT id AS lcgid, name AS lcgname, parent, color
                FROM {id_lcg}
            ) AS lcg
            ON lc.labelclassgroup = lcg.lcgid
        ''').format(
            id_lc=sql.Identifier(project, 'labelclass'),
            id_lcg=sql.Identifier(project, 'labelclassgroup')
        )
        result = self.db_connector.execute(query_str, None, 'all')
        for r in result:
            if r['id'] is not None:
                db_classes[r['id']] = r
            if r['lcgid'] is not None:
                if not r['lcgid'] in db_groups:
                    db_groups[r['lcgid']] = {**r, **{'num_children':0}}
                elif not 'lcgid' in db_groups[r['lcgid']]:
                    db_groups[r['lcgid']] = {**db_groups[r['lcgid']], **r}
            if r['labelclassgroup'] is not None:
                if not r['labelclassgroup'] in db_groups:
                    db_groups[r['labelclassgroup']] = {'num_children':1}
                else:
                    db_groups[r['labelclassgroup']]['num_children'] += 1

        # parse provided class definitions list
        unique_keystrokes = set()
        classes_new = []
        classes_update = []
        classgroups_update = []
        def _parse_item(item, parent=None):
            # get or create ID for item
            try:
                item_id = UUID(item['id'])
            except Exception:
                item_id = uuid4()
                while item_id in classes_update or item_id in classgroups_update:
                    item_id = uuid4()

            color = item.get('color', None)

            # resolve potentially duplicate/too similar color values
            if isinstance(color, str) and (color not in colors or colors[color] != item_id):
                color = helpers.offset_color(color.lower(),
                                            colors.keys(),
                                            self.MINIMAL_COLOR_OFFSET)
            elif not isinstance(color, str):
                color = helpers.random_hex_color(colors.keys(), self.MINIMAL_COLOR_OFFSET)

            color = color.lower()

            entry = {
                'id': item_id,
                'name': item['name'],
                'color': color,
                'keystroke': None,
                'labelclassgroup': parent
            }
            colors[color] = item_id
            if 'children' in item:
                # label class group
                classgroups_update.append(entry)
                for child in item['children']:
                    _parse_item(child, item_id)
            else:
                # label class
                if 'keystroke' in item and not item['keystroke'] in unique_keystrokes:
                    entry['keystroke'] = item['keystroke']
                    unique_keystrokes.add(item['keystroke'])
                if entry.get('id', None) in db_classes:
                    classes_update.append(entry)
                else:
                    classes_new.append(entry)

        for item in classdef:
            _parse_item(item, None)

        # apply changes
        if remove_missing:
            query_args = []
            if len(classes_update) > 0:
                # remove all missing label classes
                lc_spec = sql.SQL('WHERE id NOT IN %s')
                query_args.append(tuple([(l['id'],) for l in classes_update]))
            else:
                # remove all label classes
                lc_spec = sql.SQL('')
            if len(classgroups_update) > 0:
                # remove all missing labelclass groups
                lcg_spec = sql.SQL('WHERE id NOT IN %s')
                query_args.append(tuple([(l['id'],) for l in classgroups_update]))
            else:
                # remove all labelclass groups
                lcg_spec = sql.SQL('')
            query_str = sql.SQL('''
                DELETE FROM {id_lc}
                {lcSpec};
                DELETE FROM {id_lcg}
                {lcgSpec};
            ''').format(
                id_lc=sql.Identifier(project, 'labelclass'),
                id_lcg=sql.Identifier(project, 'labelclassgroup'),
                lcSpec=lc_spec,
                lcgSpec=lcg_spec
            )
            self.db_connector.execute(query_str, tuple(query_args), None)

        # add/update in order (groups, set their parents, label classes)
        groups_new = [(g['id'], g['name'], g['color'],) for g in classgroups_update]
        query_str = sql.SQL('''
            INSERT INTO {id_lcg} (id, name, color)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                color = EXCLUDED.color;
        ''').format(        #TODO: on conflict(name)
            id_lcg=sql.Identifier(project, 'labelclassgroup')
        )
        self.db_connector.insert(query_str, groups_new)

        # set parents
        groups_parents = [(g['id'], g['labelclassgroup'],) for g in classgroups_update \
                            if ('labelclassgroup' in g and g['labelclassgroup'] is not None)]
        query_str = sql.SQL('''
            UPDATE {id_lcg} AS lcg
            SET parent = q.parent
            FROM (VALUES %s) AS q(id, parent)
            WHERE lcg.id = q.id;
        ''').format(
            id_lcg=sql.Identifier(project, 'labelclassgroup')
        )
        self.db_connector.insert(query_str, groups_parents)

        # update existing label classes
        if is_segmentation and max_idx >= 255 and len(classes_new) > 0:
            # segmentation and maximum labelclass idx serial reached: cannot add new classes
            # pylint: disable=consider-using-f-string
            warnings.append('Maximum class index ordinal 255 reached. ' + \
                'The following new classes had to be discarded: {}.'.format(
                    ','.join(['"{}"'.format(c['name']) for c in classes_new])
                ))
            classes_new = []
        else:
            # do updates and insertions in one go
            classes_update.extend(classes_new)

        lcdata = [(l['id'], l['name'], l['color'], l['keystroke'], l['labelclassgroup'],) \
                    for l in classes_update]
        query_str = sql.SQL('''
            INSERT INTO {id_lc} (id, name, color, keystroke, labelclassgroup)
            VALUES %s
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
            color = EXCLUDED.color,
            keystroke = EXCLUDED.keystroke,
            labelclassgroup = EXCLUDED.labelclassgroup;
        ''').format(    #TODO: on conflict(name)
            id_lc=sql.Identifier(project, 'labelclass')
        )
        self.db_connector.insert(query_str, lcdata)

        return warnings


    def get_model_to_proj_class_mapping(self,
                                        project: str,
                                        model_id: Union[UUID,
                                                        str,
                                                        Iterable[Union[UUID,str]]]=None) -> dict:
        '''
            Returns a dict of tuples of tuples (AI model label class name, project label class ID),
            organized by AI model library. These label class mappings are used to translate from AI
            model state class predictions from the Model Marketplace to label class IDs present in
            the current project. If "aiModelID" is provided (str or Iterable of str), only
            definitions for the provided AI model libraries are returned.
        '''
        model_ids = []
        lib_str = sql.SQL('')

        if isinstance(model_id, (UUID, str)):
            model_id = [model_id]
        for mid in model_id:
            try:
                model_ids.append(UUID(mid))
            except (TypeError, AttributeError, ValueError):
                continue
        model_ids = tuple(model_ids)
        if len(model_ids) > 0:
            lib_str = sql.SQL('WHERE marketplace_origin_id IN (%s)')
        else:
            model_ids = None

        response = {}
        result = self.db_connector.execute(sql.SQL(
            'SELECT * FROM {id_modellc} {libStr};'
        ).format(
            id_modellc=sql.Identifier(project, 'model_labelclass'),
            libStr=lib_str
        ), model_id, 'all')
        if result is not None and len(result):
            for res in result:
                model_origin_id = str(res['marketplace_origin_id'])
                if model_origin_id not in response:
                    response[model_origin_id] = []
                lc_proj = (str(res['labelclass_id_project']) \
                            if res['labelclass_id_project'] is not None else None)
                response[model_origin_id].append((res['labelclass_id_model'],
                                                  res['labelclass_name_model'],
                                                  lc_proj))
        return response


    def save_model_to_proj_class_mapping(self, project: str, mapping: dict) -> int:
        '''
            Receives a dict of tuples of tuples, organized by AI model library, and saves the
            information in the database. NOTE: all previous rows in the database for the given AI
            model library entries are deleted prior to insertion of the new values.
        '''
        # assemble arguments
        ai_model_ids = set()
        values = []
        labelclasses_new = {}       # label classes in model to add new to project
        for key, next_map in mapping.items():
            ai_model_id = UUID(key)
            ai_model_ids.add(ai_model_id)
            for row in next_map:
                # tuple order in map: (source class ID, source class name, target class ID)
                source_id = row[0]
                source_name = row[1]
                target_id = None
                if isinstance(row[2], str):
                    if row[2].lower() == '$$add_new$$':
                        # special flag to add new labelclass to project
                        labelclasses_new[source_name] = (ai_model_id,
                                                         source_id,
                                                         source_name,
                                                         target_id)
                        continue    # we'll deal with newly added classes later
                    try:
                        target_id = UUID(row[2])
                    except Exception:
                        target_id = None
                values.append((ai_model_id,
                               source_id,
                               source_name,
                               target_id))

        # add any newly added label classes to project
        if len(labelclasses_new) > 0:
            lc_added = self.db_connector.insert(sql.SQL('''
                    INSERT INTO {id_lc} (name, color)
                    VALUES %s
                    ON CONFLICT (name) DO NOTHING
                    RETURNING id, name;
                ''').format(id_lc=sql.Identifier(project, 'labelclass')),
                [(l[2],helpers.random_hex_color(),) for l in labelclasses_new.values()],
                'all')       #TODO: make random colors exclusive from each other
            for row in lc_added:
                values.append((labelclasses_new[row[1]][0],
                               labelclasses_new[row[1]][1],
                               labelclasses_new[row[1]][2],
                               row[0]))

        # perform insertion
        self.db_connector.insert(sql.SQL('''
            DELETE FROM {id_modellc} WHERE
            marketplace_origin_id IN %s;
        ''').format(
            id_modellc=sql.Identifier(project, 'model_labelclass')
        ),
        (tuple(ai_model_ids),))
        self.db_connector.insert(sql.SQL('''
            INSERT INTO {id_modellc} (marketplace_origin_id, labelclass_id_model, labelclass_name_model,
            labelclass_id_project)
            VALUES %s;
        ''').format(
            id_modellc=sql.Identifier(project, 'model_labelclass')
        ),
        tuple(values))
        return 0



    def get_project_name_available(self, project_name: str) -> bool:
        '''
            Returns True if the provided project (long) name is available.
        '''
        if not isinstance(project_name, str):
            return False
        project_name_stripped = project_name.strip().lower()
        if len(project_name_stripped) == 0:
            return False

        # check if name matches prohibited AIDE keywords (we do not replace long names)
        if project_name_stripped in self.PROHIBITED_STRICT or \
            any(p in project_name_stripped for p in self.PROHIBITED_STRICT):
            return False
        if project_name_stripped in self.PROHIBITED_NAMES:
            return False
        if any(project_name_stripped.startswith(p) for p in self.PROHIBITED_NAME_PREFIXES):
            return False

        # check if name is already taken
        result = self.db_connector.execute('''SELECT 1 AS result
            FROM aide_admin.project
            WHERE name = %s;
            ''',
            (project_name,),
            1)

        if result is None or len(result) == 0:
            return True
        return result[0]['result'] != 1


    def get_project_shortname_available(self, project_name: str) -> bool:
        '''
            Returns True if the provided project shortname is available. In essence, "available"
            means that a database schema with the given name can be created (this includes Postgres
            schema name conventions). Returns False otherwise.
        '''
        if not isinstance(project_name, str):
            return False
        project_name_stripped = project_name.strip().lower()
        if len(project_name_stripped) == 0:
            return False

        # check if name conforms to allowed characters
        if re.fullmatch(self.project_shortname_check, project_name_stripped) is None:
            return False

        # check if name matches prohibited AIDE keywords; replace where possible
        if project_name_stripped in self.PROHIBITED_STRICT or \
            any(p in project_name_stripped for p in self.PROHIBITED_STRICT):
            return False
        if project_name_stripped in self.PROHIBITED_NAMES or \
            project_name_stripped in self.PROHIBITED_SHORTNAMES:
            return False
        if any(project_name_stripped.startswith(pat) for pat in self.PROHIBITED_NAME_PREFIXES):
            return False
        for pat in self.SHORTNAME_PATTERNS_REPLACE:
            project_name = project_name.replace(pat, '_')

        # check if provided name is valid as per Postgres conventions
        matches = re.findall(self.project_shortname_postgres_check, project_name)
        if len(matches) > 0:
            return False

        # check if project shorthand already exists in database
        result = self.db_connector.execute('''SELECT 1 AS result
            FROM information_schema.schemata
            WHERE schema_name ilike %s
            UNION ALL
            SELECT 1 FROM aide_admin.project
            WHERE shortname ilike %s;
            ''',
            (project_name,project_name,),
            2)

        if result is None or len(result) == 0:
            return True

        if len(result) == 2:
            return result[0]['result'] != 1 and result[1]['result'] != 1
        if len(result) == 1:
            return result[0]['result'] != 1
        return True


    def suggest_shortname(self, long_name: str) -> str:
        '''
            Creates and returns a shortname-compatible variant of the provided "long_name" that is
            available (i.e., not yet used by another project).
        '''
        if len(long_name) == 0:
            return None

        # get all current project names
        proj_names = self.db_connector.execute('''
            SELECT shortname FROM aide_admin.project;
        ''', None, 'all')
        proj_names = {pname['shortname'] for pname in proj_names}

        def _append_number(shortname):
            if shortname not in set.union(proj_names, \
                set(self.PROHIBITED_SHORTNAMES),
                set(self.PROHIBITED_NAMES)):
                return shortname
            probe_name = shortname
            number = 1
            is_taken = True
            while is_taken:
                probe_name = f'{shortname}-{number}'
                is_taken = probe_name in proj_names
                number += 1
            return probe_name

        short_name = long_name.lower()
        for prefix in self.PROHIBITED_NAME_PREFIXES:
            if short_name.startswith(prefix):
                short_name = short_name[1:]
        for pattern in [
            *self.SHORTNAME_PATTERNS_REPLACE,
            *self.PROHIBITED_STRICT,
            ' ']:
            short_name = short_name.replace(pattern, '-')

        # append dash and number if necessary
        short_name = _append_number(short_name)
        return short_name


    def get_project_archived(self,
                             project: str,
                             username: str) -> dict:
        '''
            Returns the "archived" flag of a project. Throws an error if user is not registered in
            project, or if the project is not in demo mode.
        '''

        # check if user is authenticated
        is_authenticated = self.db_connector.execute('''
            SELECT username, isSuperUser FROM (
                SELECT username
                FROM aide_admin.authentication
                WHERE project = %s
            ) AS auth
            RIGHT OUTER JOIN (
                SELECT name, isSuperUser
                FROM aide_admin.user
                WHERE name = %s
            ) AS usr
            ON auth.username = usr.name
        ''', (project, username), 1)

        if is_authenticated is None or len(is_authenticated) == 0 or \
            (is_authenticated[0]['username'] is None and not is_authenticated[0]['issuperuser']):
            # project does not exist or user is neither member nor super user
            return {
                'status': 2,
                'message': 'User cannot view project details.'
            }

        is_archived = self.db_connector.execute('''
            SELECT archived FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project,), 1)

        if is_archived is None or len(is_archived) == 0:
            return {
                'status': 3,
                'message': 'Project does not exist.'
            }

        return {
            'status': 0,
            'archived': is_archived[0]['archived']
        }


    def set_project_archived(self,
                             project: str,
                             username: str,
                             archived: bool) -> dict:
        '''
            Archives or unarchives a project by setting the "archived" flag in the database to the
            value in "archived". An archived project is simply hidden from the list and
            unchangeable, but stays intact as-is and can be unarchived if needed. No data is
            deleted.

            Only project owners and super users can archive projects (i.e., even being a project
            administrator is not enough).
        '''

        # check if user is authenticated
        is_authenticated = self.db_connector.execute('''
            SELECT CASE WHEN owner = %s THEN TRUE ELSE FALSE END AS result
            FROM aide_admin.project
            WHERE shortname = %s
            UNION ALL
            SELECT isSuperUser AS result
            FROM aide_admin.user
            WHERE name = %s;
        ''', (username, project, username), 2)

        if not is_authenticated[0]['result'] \
            and not is_authenticated[1]['result']:
            # user is neither project owner nor super user; reject
            return {
                'status': 2,
                'message': 'User is not authenticated to archive or unarchive project.'
            }

        # archive project
        self.db_connector.execute('''
            UPDATE aide_admin.project
            SET archived = %s
            WHERE shortname = %s;
        ''', (archived, project), None)

        return {
            'status': 0
        }


    def delete_project(self,
                       project: str,
                       username: str,
                       delete_files: bool=False) -> dict:
        '''
            Removes a project from the database, including all metadata. Also dispatches a Celery
            task to the FileServer to delete images (and other project-specific data on disk) if
            "deleteFiles" is True.

            WARNING: this seriously deletes a project in its entirety; any data will be lost
            forever.

            Only project owners and super users can delete projects (i.e., even being a project
            administrator is not enough).
        '''

        # check if user is authenticated
        is_authenticated = self.db_connector.execute('''
            SELECT CASE WHEN owner = %s THEN TRUE ELSE FALSE END AS result
            FROM aide_admin.project
            WHERE shortname = %s
            UNION ALL
            SELECT isSuperUser AS result
            FROM aide_admin.user
            WHERE name = %s;
        ''', (username, project, username), 2)

        if not is_authenticated[0]['result'] \
            and not is_authenticated[1]['result']:
            # user is neither project owner nor super user; reject
            return {
                'status': 2,
                'message': 'User is not authenticated to delete project.'
            }

        # check if project exists; if not it may already be deleted
        project_exists = self.db_connector.execute('''
            SELECT shortname
            FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project,), 1)
        if project_exists is None or len(project_exists) == 0:
            # project does not exist; return        #TODO: still allow deleting files on disk?
            return {
                'status': 3,
                'message': 'Project does not exist.'
            }

        # stop ongoing tasks
        #TODO: make more elegant
        tc = TaskCoordinatorMiddleware(self.config, self.db_connector)
        tc.revoke_all_tasks(project, username, include_ai_tasks=True)


        # remove rows from database
        self.db_connector.execute('''
            DELETE FROM aide_admin.authentication
            WHERE project = %s;
            DELETE FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project, project,), None)

        # dispatch Celery task to remove DB schema and files (if requested)
        process = fileServer_interface.deleteProject.si(project, delete_files)
        process.apply_async(queue='FileServer')       #TODO: task ID; progress monitoring

        #TODO: return Celery task ID?
        return {
                'status': 0
            }
