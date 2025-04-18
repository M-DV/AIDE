'''
    Creates and assembles the Bottle app with the individual AIDE modules. Can also be used as a dry
    run and to perform pre-flight checks (verbose start; database migration, etc.).

    2021-24 Benjamin Kellenberger
'''

import os
import sys
import platform
import argparse
import bottle
from bottle import Bottle

from util import helpers
from util.logDecorator import LogDecorator
from util.configDef import Config
from util import drivers
from setup.setup_database import add_update_superuser
from setup.migrate_aide import migrate_aide
from modules import REGISTERED_MODULES, Database
from constants.version import AIDE_VERSION


def _verify_unique(instances, module_class):
    '''
        Compares the newly requested module, address and port against already launched modules on
        this instance. Raises an Exception if another module from the same type has already been
        launched on this instance
    '''
    for key in instances.keys():
        instance = instances[key]
        if module_class.__class__.__name__ == instance.__class__.__name__:
            raise Exception(
                f'Module {module_class.__class__.__name__} already launched on this server.')



def assemble_server(verbose_start=True,
                    check_v1_config=True,
                    migrate_database=True,
                    force_migrate=False,
                    passive_mode=False):
    '''
        Initializes all AIDE modules and furnishes them with helpers where needed. Does not start a
        server by itself.
    '''
    # force verbosity if any of the pre-flight checks is enabled
    verbose_start = any((verbose_start, check_v1_config, migrate_database))

    instance_args = os.environ['AIDE_MODULES'].split(',')

    if verbose_start:
        config_path = os.environ['AIDE_CONFIG_PATH']
        module_checks = [['', f'=> {mod}'][int(mod in instance_args)] \
                         for mod in ['LabelUI','AIController','FileServer']]
        print(f'''\033[0;34m\033[1m
             ████████                   version {AIDE_VERSION}
         ███████████████                {platform.platform()}
        ██████████████████              Python {platform.python_version()}
    ████████████████████████
 ██████████████████████████████         [config]
████████   ███  █     ███     ████      => {config_path}
███████  █  ██  █  ███  █  ████████
███████     ██  █  ███  █    ██████     [modules]
██████  ███  █  █  ███  █  ████████     {module_checks[0]}
 █████  ███  █  █     ███     ████      {module_checks[1]}
  ███████████████████████████████       {module_checks[2]}
    ███████████████████████████\033[0m
''')

    status_offset = LogDecorator.get_ljust_offset()

    # load configuration
    config = Config(None, verbose_start)
    bottle.BaseRequest.MEMFILE_MAX = 1024**3    #TODO: make hyperparameter in config?

    # connect to database
    db_connector = Database(config, verbose_start)

    # Abord any unfinished project task on startup
    db_connector.execute('''
        DO $$ 
        DECLARE 
            project TEXT;
        BEGIN
            FOR project IN 
                SELECT table_schema
                FROM information_schema.tables
                WHERE table_name = 'workflowhistory'
            LOOP
                EXECUTE format('UPDATE %I.workflowhistory SET timeFinished = NOW(), succeeded = FALSE WHERE timeFinished IS NULL', project);
            END LOOP;
        END $$;
    ''', None, None)

    if check_v1_config:
        # check if config file points to unmigrated v1 project
        print('Checking database...'.ljust(status_offset), end='')
        has_admin_table = db_connector.execute('''
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'aide_admin'
                    AND table_name = 'project'
                );
            ''', None, 1)
        if not has_admin_table[0]['exists']:
            # not (yet) migrated, raise Exception with instructions to ensure compatibility
            LogDecorator.print_status('fail')
            print(f'''
        The current installation of AIDE:
            database host: {config.get_property('Database', 'host')}
            database name: {config.get_property('Database', 'name')}
            schema:        {config.get_property('Database', 'schema', str, '(not specified)')}

        points to an installation of the legacy AIDE v1.
        If you wish to continue using AIDE v3, you have to upgrade the project accordingly.
        For instructions to do so, see here:
            https://github.com/bkellenb/AIDE/blob/v3.0/doc/upgrade_from_v1.md
            ''')
            sys.exit(1)

        else:
            LogDecorator.print_status('ok')

        # check if projects have been migrated
        print('Checking projects...'.ljust(status_offset), end='')
        db_schema = config.get_property('Database', 'schema', str, None)
        if db_schema is not None:
            is_migrated = db_connector.execute('''
                    SELECT COUNT(*) AS cnt
                    FROM aide_admin.project
                    WHERE shortname = %s;
                ''', (db_schema,), 1)
            if is_migrated is not None and is_migrated[0]['cnt'] == 0:
                LogDecorator.print_status('warn')
                print(f'''
        WARNING: the selected configuration .ini file
        ("{os.environ['AIDE_CONFIG_PATH']}")
        points to a project that has not yet been migrated to AIDE v2.
        Details:
            database host: {config.get_property('Database', 'host')}
            database name: {config.get_property('Database', 'name')}
            schema:        {db_schema}

        If you wish to continue using AIDE v2 for this project, you have to upgrade it
        to v2 accordingly.
        For instructions to do so, see here:
            https://github.com/bkellenb/AIDE/blob/multiProject/doc/upgrade_from_v1.md
            ''')
            else:
                LogDecorator.print_status('ok')
        else:
            LogDecorator.print_status('ok')


    if migrate_database or force_migrate:
        # bring AIDE up-to-date
        print('Updating database...'.ljust(status_offset), end='')
        warnings, errors = migrate_aide(force_migrate)
        if len(warnings) > 0 or len(errors) > 0:
            if len(errors) > 0:
                LogDecorator.print_status('fail')
            else:
                LogDecorator.print_status('warn')

            print('Warnings and/or errors occurred while updating AIDE to the latest version ' + \
                f'({AIDE_VERSION}):')
            print('\nWarnings:')
            for warning in warnings:
                print(f'\t"{warning}"')

            print('\nErrors:')
            for error in errors:
                print(f'\t"{error}"')

            if len(errors) > 0:
                sys.exit(2)

        else:
            LogDecorator.print_status('ok')

    # add/modify superuser credentials if needed
    try:
        result = add_update_superuser(config, db_connector)
        if result is not None:
            if result['new_account']:
                print('New super user credentials in configuration file added to database:')
                print('\tName:   ' + result['details']['name'])
                print('\tE-mail: ' + result['details']['email'])
                print('\tPassword: ****')
            elif len(result['changes']) > 0:
                su_name = result['details']['name']
                print(f'Super user account details changed for account name "{su_name}". ' + \
                        'New credentials:')
                print('\tName:   ' + result['details']['name'])
                print('\tE-mail: ' + result['details']['email'] + \
                    (' (changed)' if result['changes'].get('adminEmail', False) else ''))
                print('\tPassword: ****' + \
                    (' (changed)' if result['changes'].get('adminPassword', False) else ''))
    except Exception as exc:
        # no superuser credentials provided; ignore
        print(exc)    #TODO

    # load drivers
    drivers.init_drivers(verbose_start)

    # prepare bottle
    app = Bottle()

    # monkey-patch JSON encoder
    app.plugins[0].json_dumps = helpers.json_dumps

    # initialize "singletons"
    db_connector = REGISTERED_MODULES['Database'](config, verbose_start)
    user_handler = REGISTERED_MODULES['UserHandler'](config,
                                                     app,
                                                     db_connector)
    task_coordinator = REGISTERED_MODULES['TaskCoordinator'](config,
                                                             app,
                                                             db_connector,
                                                             user_handler)

    # add helper modules to definition
    instance_args.extend(['DataAdministrator', 'StaticFileServer'])
    if 'LabelUI' in instance_args:
        instance_args.extend(['AIDEAdmin',
                              'Reception',
                              'ProjectConfigurator',
                              'ProjectStatistics',
                              'ImageQuerier',           #TODO: allow running on FileServer
                              'Mapserver'])             #TODO: ditto
    if 'AIController' in instance_args:
        instance_args.append('ModelMarketplace')

    # parse requested instances
    instances = {}
    for inst_arg in instance_args:

        module_name = inst_arg.strip()
        if module_name in ('Database', 'UserHandler', 'TaskCoordinator', 'AIWorker') or \
            module_name in instances:
            continue

        module_class = REGISTERED_MODULES[module_name]

        # verify
        _verify_unique(instances, module_class)

        # create instance
        instance = module_class(config,
                                app,
                                db_connector,
                                user_handler,
                                task_coordinator,
                                verbose_start,
                                passive_mode)
        instances[module_name] = instance

        # add authentication functionality
        if hasattr(instance, 'add_login_check_fun'):
            instance.add_login_check_fun(user_handler.check_authenticated)

        # register Celery tasks where needed
        if module_name == 'FileServer':
            from modules.DataAdministration.backend import celery_interface

        elif module_name == 'AIController':
            from modules.AIController.backend import celery_interface

        elif module_name == 'AIWorker':
            from modules.AIWorker.backend import celery_interface

    if verbose_start:
        print('\n')
    return app



if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='Launch AIDE server (single-threaded) or perform pre-flight checks.')
    parser.add_argument('--launch', type=int, default=0,
        help='If set to 1, a single-threaded server (typically Python WSGI ref.) will be launched.')
    parser.add_argument('--check_v1', type=int, default=1,
        help='Set to 1 to check database for unmigrated AIDE v1 setup.')
    parser.add_argument('--migrate_db', type=int, default=1,
        help='Set to 1 to upgrade database with latest changes for AIDE setup.')
    parser.add_argument('--force_migrate', type=int, default=0,
        help='If set to 1, database upgrade will be enforced even if AIDE versions already match.')
    parser.add_argument('--verbose', type=int, default=1,
        help='Set to 1 to print launch information to console.')
    args = parser.parse_args()

    try:
        aide_app = assemble_server(args.verbose,
                                   args.check_v1,
                                   args.migrate_db,
                                   args.force_migrate,
                                   not bool(args.launch))
    except Exception as global_exc:
        print(global_exc)
        sys.exit(1)

    if bool(args.launch):
        if args.verbose:
            print('Launching server...')
        server_config = Config(False)
        host = server_config.get_property('Server', 'host')
        port = server_config.get_property('Server', 'port')
        aide_app.run(host=host, port=port)
    # else:
    #     sys.exit(0)
