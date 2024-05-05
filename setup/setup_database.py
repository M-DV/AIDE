'''
    Script to establish a database schema according to the specifications provided in the
    configuration file. Unlike in previous versions of AIDE, this does not set up any
    project-specific schemata anymore. This task is achieved through the GUI. See
    modules.ProjectAdministration.backend.middleware.py for details.

    2019-24 Benjamin Kellenberger
'''

import os

if not 'AIDE_MODULES' in os.environ:
    os.environ['AIDE_MODULES'] = 'FileServer'     # for compatibility with Celery worker import

# pylint: disable=wrong-import-position
import argparse
import bcrypt

from constants.version import AIDE_VERSION
from util.configDef import Config
from util import helpers
from modules import Database
from modules.UserHandling.backend.middleware import UserMiddleware
from setup.migrate_aide import migrate_aide



def add_update_superuser(config: Config, db_connector: Database) -> dict:
    '''
        Reads the super user credentials from the config file and checks if anything has changed
        w.r.t. the entries in the database. Makes modifications if this is the case and reports back
        the changes.
    '''
    is_new_account = False
    changes = {}

    # values in config file
    admin_name = config.get_property('Project', 'adminName')
    if admin_name is None or len(admin_name) == 0:
        return None
    admin_email = config.get_property('Project', 'adminEmail')
    admin_pass = config.get_property('Project', 'adminPassword')
    if admin_pass is None or len(admin_pass) == 0:
        raise ValueError('No password defined for admin account in configuration file.')

    # get current values
    current_meta = db_connector.execute('''
            SELECT email, hash
            FROM aide_admin.user
            WHERE name = %s;
        ''', (admin_name,), 1)
    if current_meta is None or len(current_meta) == 0:
        # no account found under this name; create new
        is_new_account = True

    # check if changes
    if current_meta is not None and len(current_meta) > 0:
        current_meta = current_meta[0]
        if current_meta['email'] != admin_email:
            changes['adminEmail'] = True
        if not bcrypt.checkpw(admin_pass.encode('utf8'), bytes(current_meta['hash'])):
            changes['adminPassword'] = True

    if is_new_account or len(changes) > 0:
        hash_val = helpers.create_hash(admin_pass.encode('utf8'), UserMiddleware.SALT_NUM_ROUNDS)
        sql = '''
                INSERT INTO aide_admin.user (name, email, hash, issuperuser)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                SET email=EXCLUDED.email, hash=EXCLUDED.hash;
            '''
        values = (admin_name, admin_email, hash_val, True,)
        db_connector.execute(sql, values, None)

    return {
        'details': {
            'name': admin_name,
            'email': admin_email
        },
        'new_account': is_new_account,
        'changes': changes
    }



def setup_db() -> None:
    '''
        Reads the database initialization SQL script and sets up the database to AIDE
        specifications.
    '''
    config = Config()
    db_connector = Database(config)

    # read SQL skeleton
    with open(os.path.join(os.getcwd(), 'setup/db_create.sql'),
              'r',
              encoding='utf-8') as f_sql:
        sql = f_sql.read()

    # fill in placeholders
    sql = sql.replace('&user', config.get_property('Database', 'user'))

    # run SQL
    db_connector.execute(sql, None, None)

    # add admin user
    add_update_superuser(config, db_connector)

    # finalize: migrate database in any case (this also adds the AIDE version if needed)
    migrate_aide()

    # fresh database; add AIDE version
    db_connector.execute('''
        INSERT INTO aide_admin.version (version)
        VALUES (%s)
        ON CONFLICT (version) DO NOTHING;
    ''', (AIDE_VERSION,), None)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Set up AIDE database schema.')
    parser.add_argument('--settings_filepath',
                        type=str,
                        default='config/settings.ini',
                        const=1,
                        nargs='?',
                        help='Manual specification of the directory of the settings.ini file; ' + \
                             'only considered if environment variable unset ' + \
                              '(default: "config/settings.ini").')
    args = parser.parse_args()

    if 'AIDE_CONFIG_PATH' not in os.environ:
        os.environ['AIDE_CONFIG_PATH'] = args.settings_filepath

    setup_db()
