'''
    Helper script to upgrade an existing project from AIDE v1 to a v2 (multi-project)
    installation.

    Use as follows:
        1. Move the images from your v1 project to a sub-folder of v2's "file directory"
           with the name of your v1 project's database schema (check parameter "staticfiles_dir"
           under "[FileServer]" of the v2's configuration .ini file).
           For example:
                If your v1's images are stored under "/datadrive/images",
                your v1's database schema is named "my_great_project",
                and the "staticfiles_dir" of v2 is set to "/datadrive/new",
                you have to move all images from "/datadrive/images" to
                "/datadrive/new/my_great_project".
           Alternatively, the script may ask you if it should create a symbolic link from the new
           target place to the original folder. This is a temporary solution only. Also, you should
           avoid using recursive links (e.g., "/datadrive/images/my_great_project" pointing to
           "/datadrive/images").
        1. Make sure the "AIDE_CONFIG_PATH" environment variable points to the
           configuration .ini file of the NEW (v2) installation.
        2. Run this script as follows:
            python projectCreation/upgrade_v1_project.py --settings_filepath=/path/to/settings.ini
           
           replace "/path/to/settings.ini" with the file path to the configuration .ini file
           of your original (v1) installation.

    NOTES:
        - This script does NOT transfer a v1 project to another database, it just upgrades an
          existing v1 project to work with the v2 installation that points to the SAME database.
        - Once a v1 project has been successfully upgraded with this script, the original
          configuration .ini file can be discarded. There is no need to run this script more than
          one time for a specific v1 project.
        - THERE IS NO GUARANTEE THAT A v1 PROJECT, CONVERTED TO v2 WITH THIS SCRIPT, WILL STILL
          RUN UNDER A v1 INSTALLATION. IT IS STRONGLY DISCOURAGED TO CONTINUE TO USE THE v1 SOFT-
          WARE ON A PROJECT THAT HAS BEEN MIGRATED.

    
    2019-24 Benjamin Kellenberger
'''

import os

# verify environment variables
if not 'AIDE_CONFIG_PATH' in os.environ:
        raise Exception('ERROR: System environment variable "AIDE_CONFIG_PATH" must be set and ' + \
                        'must point to the configuration .ini file of the v2 installation.')
if not 'AIDE_MODULES' in os.environ:
    os.environ['AIDE_MODULES'] = 'FileServer'     # for compatibility with Celery worker import

# verify execution directory
if not os.path.isdir(os.path.join(os.getcwd(), 'modules')):
    raise Exception('ERROR: Upgrade script needs to be launched from the root directory ' + \
                    'of the AIDE v2 installation.')

import sys
import argparse
import json
import secrets
from psycopg2 import sql
from setup.setupDB import setupDB
from setup.migrate_aide import MODIFICATIONS_sql
from modules import UserHandling
from util import helpers



if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='Upgrade and register an AIDE v1 project to an existing v2 installation.')
    parser.add_argument('--settings_filepath', type=str,
                        help='Path of the configuration .ini file for the v1 project ' + \
                             'to be upgraded to v2.')
    args = parser.parse_args()

    from util.configDef import Config
    from modules import Database

    # v2 config file
    config = Config()
    dbConn = Database(config)
    if not dbConn.canConnect():
        raise Exception('Error connecting to database.')

    # v1 config file
    v1_config = Config(args.settings_filepath)

    # db schema of v1 project
    dbSchema = v1_config.get_property('Database', 'schema')
    projectName = v1_config.get_property('Project', 'projectName')

    # verify we're running a database on v2 standards
    isV2 = dbConn.execute('''
        SELECT 1
        FROM   information_schema.tables 
        WHERE  table_schema = 'aide_admin'
        AND    table_name = 'project';
    ''', None, 'all')
    if isV2 is None or not len(isV2):
        # upgrade to v2
        dbName = config.get_property('Database', 'name')
        print(f'WARNING: Target database "{dbName}" has not (yet) been upgraded to the ' + \
              'AIDE v2 schema; we will attempt to do this now...')
        setupDB()

    # verify that project is unique
    uniqueQuery = dbConn.execute('''
        SELECT shortname, name
        FROM aide_admin.project;
    ''', None, 'all')
    if uniqueQuery is not None and len(uniqueQuery):
        for u in uniqueQuery:
            if u['shortname'] == dbSchema:
                print(f'Project with short name "{dbSchema}" seems to have already been ' + \
                      'migrated to AIDE v2. Aborting...')
                sys.exit(0)
            if u['name'] == projectName:
                projectName_old = projectName
                projectName = f'{projectName_old} ({dbSchema})'
                print(f'WARNING: project name "{projectName_old}" already exists in database. ' + \
                      f'Renaming to "{projectName}"...')

    # migrate user names before applying changes to database

    # add admin user (if not already present)
    adminName = v1_config.get_property('Project',
                                      'adminName',
                                      dtype=str,
                                      fallback=None)
    if adminName is not None:
        adminEmail = v1_config.get_property('Project', 'adminEmail')
        adminPass = v1_config.get_property('Project', 'adminPassword')
        uHandler = UserHandling.backend.middleware.UserMiddleware(config, dbConn)
        adminPass = uHandler._create_hash(adminPass.encode('utf8'))
        dbConn.execute('''
                INSERT INTO aide_admin.user (name, email, hash, issuperuser)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO NOTHING;
            ''',
            (adminName, adminEmail, adminPass, True),
            None
        )

    # add users
    dbConn.execute(sql.SQL('''
            DO
            $do$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM   information_schema.tables 
                    WHERE  table_schema = %s
                    AND    table_name = 'user'
                ) THEN
                    INSERT INTO aide_admin.user (name, email, hash, isSuperUser, canCreateProjects,
                        session_token, last_login)
                    SELECT name, email, hash, FALSE, FALSE, session_token, last_login
                    FROM {id_user}
                    ON CONFLICT (name) DO NOTHING;
                END IF;
            END $do$;
        ''').format(id_user=sql.Identifier(dbSchema, 'user')),
        (dbSchema,))

    # update tables: make modifications one at a time
    for mod in MODIFICATIONS_sql:
        dbConn.execute(mod.format(schema=dbSchema), None, None)

    # migrate project to v2

    # The multi-project AIDE setup requires images to be in a subfolder named after
    # the project shorthand. Here we tell the user about moving the files, or else
    # propose a temporary fix (softlink).
    softlinkName = config.get_property('FileServer', 'staticfiles_dir')
    v1StaticFilesDir = v1_config.get_property('FileServer', 'staticfiles_dir')
    if not os.path.isdir(softlinkName):
        # not running on file server; show message
        print('You do not appear to be running AIDE on a "FileServer" instance.')
        print('INFO: In the process of AIDE supporting multiple projects, each')
        print('project\'s files must be put in a sub-folder named after the project\'s')
        print(f'shorthand (i.e.: {softlinkName}/{dbSchema}/...).')
        print('Make sure to move the files to the new path on the FileServer instance.')

    else:
        softlinkName = os.path.join(softlinkName, dbSchema)
        if os.path.islink(softlinkName):
            print(f'INFO: Detected link to project file directory ({softlinkName})')
            print('You might want to move the files to a dedicated folder at some point...')
        else:
            print('INFO: In the process of AIDE supporting multiple projects, each')
            print('project\'s files must be put in a sub-folder named after the project\'s')
            print(f'shorthand (i.e.: {softlinkName}/<images>).')
            print('Ideally, you would want to move the images to that folder, but as a')
            print('temporary fix, you can also use a softlink:')
            print(f'{softlinkName} -> {v1StaticFilesDir}')
            print('Would you like to create this softlink now?')
            confirmation = None
            while confirmation is None:
                try:
                    confirmation = input('[Y/n]: ')
                    if 'Y' in confirmation:
                        confirmation = True
                    elif 'n' in confirmation.lower():
                        confirmation = False
                        print('You selected not to create a softlink. AIDE will not find the ' + \
                              'image files before they have been moved to the new folder ' + \
                              f'("{softlinkName}"). Please create this folder and move the ' + \
                              f'contents of "{v1StaticFilesDir}" to it manually.')
                    else: raise Exception('Invalid value')
                except Exception:
                    confirmation = None
            if confirmation:
                os.symlink(
                    v1StaticFilesDir,
                    softlinkName
                )

    # assemble dict of dynamic project UI and AI settings

    # styles: try to get provided ones and fallback to defaults, if needed
    try:
        # check if custom default styles are provided
        with open('config/default_ui_settings.json',
                  'r',
                  encoding='utf-8') as f_ui:
            defaultStyles = json.load(f_ui)
    except Exception:
        # resort to built-in styles
        with open('modules/ProjectAdministration/static/json/default_ui_settings.json',
                  'r',
                  encoding='utf-8') as f_styles:
            defaultStyles = json.load(f_styles)
    try:
        with open(v1_config.get_property('LabelUI', 'styles_file'),
                  'r',
                  encoding='utf-8') as f:
            styles = json.load(f)
            styles = styles['styles']

            # compare with defaults
            styles = helpers.check_args(styles, defaultStyles)
    except Exception:
        # fallback to defaults
        styles = defaultStyles
    try:
        welcome_message_file = v1_config.get_property('Project',
                                'welcome_message_file',
                                dtype=str,
                                fallback='modules/LabelUI/static/templates/welcome_message.html')
        with open(welcome_message_file,
                  'r',
                  encoding='utf-8') as f:
            welcomeMessage = f.readlines()
    except Exception:
        welcomeMessage = ''
    uiSettings = {
        'enableEmptyClass': v1_config.get_property('Project',
                                                   'enableEmptyClass',
                                                   fallback='no'),
        'showPredictions': v1_config.get_property('LabelUI',
                                                  'showPredictions',
                                                  fallback='yes'),
        'showPredictions_minConf': v1_config.get_property('LabelUI',
                                                          'showPredictions_minConf',
                                                          dtype=float,
                                                          fallback=0.5),
        'carryOverPredictions': v1_config.get_property('LabelUI',
                                                       'carryOverPredictions',
                                                       fallback='no'),
        'carryOverRule': v1_config.get_property('LabelUI',
                                                'carryOverRule',
                                                fallback='maxConfidence'),
        'carryOverPredictions_minConf': v1_config.get_property('LabelUI',
                                                               'carryOverPredictions_minConf',
                                                               dtype=float,
                                                               fallback=0.75),
        'defaultBoxSize_w': v1_config.get_property('LabelUI',
                                                   'defaultBoxSize_w',
                                                   dtype=int,
                                                   fallback=10),
        'defaultBoxSize_h': v1_config.get_property('LabelUI',
                                                   'defaultBoxSize_h',
                                                   dtype=int,
                                                   fallback=10),
        'minBoxSize_w': v1_config.get_property('Project',
                                               'box_minWidth',
                                               dtype=int,
                                               fallback=1),
        'minBoxSize_h': v1_config.get_property('Project',
                                               'box_minHeight',
                                               dtype=int,
                                               fallback=1),
        'numImagesPerBatch': v1_config.get_property('LabelUI',
                                                    'numImagesPerBatch',
                                                    dtype=int,
                                                    fallback=1),
        'minImageWidth': v1_config.get_property('LabelUI',
                                                'minImageWidth',
                                                dtype=int,
                                                fallback=300),
        'numImageColumns_max': v1_config.get_property('LabelUI',
                                                      'numImageColumns_max',
                                                      dtype=int,
                                                      fallback=1),
        'defaultImage_w': v1_config.get_property('LabelUI',
                                                 'defaultImage_w',
                                                 dtype=int,
                                                 fallback=800),
        'defaultImage_h': v1_config.get_property('LabelUI',
                                                 'defaultImage_h',
                                                 dtype=int,
                                                 fallback=600),
        'styles': styles,
        'welcomeMessage': welcomeMessage
    }

    # models
    modelPath = v1_config.get_property('AIController', 'model_lib_path', fallback=None)
    if modelPath is not None and len(modelPath):
        dbConn.execute(sql.SQL('''
            UPDATE {} SET model_library = %s
            WHERE model_library IS NULL;''').format(sql.Identifier(dbSchema, 'cnnstate')),
        (modelPath,), None)
    else:
        modelPath = None
    alCriterionPath = v1_config.get_property('AIController', 'al_criterion_lib_path', fallback=None)
    if alCriterionPath is None or len(alCriterionPath) == 0:
        alCriterionPath = None

    modelSettingsPath = v1_config.get_property('AIController', 'model_options_path', fallback=None)
    if modelSettingsPath is not None and len(modelSettingsPath):
        try:
            with open(modelSettingsPath, 'r', encoding='utf-8') as f:
                modelSettings = json.load(f).dumps()
        except Exception:
            print('WARNING: could not parse settings defined in model settings path ' + \
                  f'("{modelSettingsPath}")')
            modelSettings = None
    else:
        modelSettings = None
    alCriterionSettingsPath = v1_config.get_property('AIController',
                                                    'al_criterion_options_path',
                                                    fallback=None)
    if alCriterionSettingsPath is not None and len(alCriterionSettingsPath):
        try:
            with open(alCriterionSettingsPath, 'r', encoding='utf-8') as f:
                alCriterionSettings = json.load(f).dumps()
        except Exception:
            print('WARNING: could not parse settings defined in AL criterion settings path ' + \
                  f'("{alCriterionSettingsPath}")')
            alCriterionSettings = None
    else:
        alCriterionSettings = None


    #TODO: eventually replace legacy fields with default workflow
    # # workflows: move values from legacy fields and create new workflow, if project already registered
    # colnames = dbConn.execute('''
    #     SELECT column_name
    #     FROM information_schema.columns
    #     WHERE table_schema = 'aide_admin'
    #     AND table_name   = 'project';
    # ''', None, 'all')
    # colnames = set([c['column_name'] for c in colnames])
    # if 'minnumannoperimage' in colnames:
    #     # legacy fields present; read and replace with new default workflow
    #     autoTrainSpec = dbConn.execute('''
    #         SELECT minnumannoperimage, maxnumimages_train, maxnumimages_inference
    #         FROM aide_admin.project
    #         WHERE shortname = %s;
    #     ''', (dbSchema,), 1)
    #     if len(autoTrainSpec):
    #         autoTrainSpec = autoTrainSpec[0]
    #         #TODO

    # register project
    secretToken = secrets.token_urlsafe(32)
    dbConn.execute('''
        INSERT INTO aide_admin.project (shortname, name, description,
            owner,
            secret_token,
            interface_enabled,
            demoMode,
            annotationType, predictionType, ui_settings,
            numImages_autoTrain,
            minNumAnnoPerImage,
            maxNumImages_train,
            maxNumImages_inference,
            ai_model_enabled,
            ai_model_library, ai_model_settings,
            ai_alCriterion_library, ai_alCriterion_settings
            )
        VALUES (
            %s, %s, %s,
            %s,
            %s,
            %s,
            %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (shortname) DO NOTHING;
    ''',
        (
            dbSchema,
            projectName,
            v1_config.get_property('Project', 'projectDescription'),
            v1_config.get_property('Project', 'adminName'),
            secretToken,
            True,
            v1_config.get_property('Project', 'demoMode'),
            v1_config.get_property('Project', 'annotationType'),
            v1_config.get_property('Project', 'predictionType'),
            json.dumps(uiSettings),
            v1_config.get_property('AIController', 'numImages_autoTrain'),
            v1_config.get_property('AIController', 'minNumAnnoPerImage'),
            v1_config.get_property('AIController', 'maxNumImages_train'),
            v1_config.get_property('AIController', 'maxNumImages_inference'),
            (modelPath is not None),
            modelPath, modelSettings,
            alCriterionPath, alCriterionSettings
        )
    )

    # add user authentication for project
    dbConn.execute(sql.SQL('''
        DO
        $do$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM   information_schema.tables 
                WHERE  table_schema = %s
                AND    table_name = 'user'
            ) THEN
                INSERT INTO aide_admin.authentication (username, project, isAdmin)
                SELECT name, %s, isAdmin FROM {id_user}
                WHERE name IN (SELECT name FROM aide_admin.user)
                ON CONFLICT (username, project) DO NOTHING;
            END IF;
        END $do$;
    ''').format(id_user=sql.Identifier(dbSchema, 'user')),
    (dbSchema, dbSchema))

    print(f'Project "{projectName}" has been converted to AIDE v2 standards. ' + \
          'Please do not use a v1 installation on this project anymore.')
