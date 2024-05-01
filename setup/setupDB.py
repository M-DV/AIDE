'''
    Script to establish a database schema according to the specifications
    provided in the configuration file. Unlike in previous versions of
    AIDE, this does not set up any project-specific schemata anymore.
    This task is achieved through the GUI.
    See modules.ProjectAdministration.backend.middleware.py for details.

    2019-24 Benjamin Kellenberger
'''

import os

if not 'AIDE_MODULES' in os.environ:
    os.environ['AIDE_MODULES'] = 'FileServer'     # for compatibility with Celery worker import

import argparse
import bcrypt
from constants.version import AIDE_VERSION
from util.configDef import Config
from modules import Database
from modules.UserHandling.backend.middleware import UserMiddleware
from setup.migrate_aide import migrate_aide



def add_update_superuser(config, dbConn):
    '''
        Reads the super user credentials from the config file and checks if
        anything has changed w.r.t. the entries in the database. Makes
        modifications if this is the case and reports back the changes.
    '''
    isNewAccount = False
    changes = {}

    # values in config file
    adminName = config.get_property('Project', 'adminName')
    if adminName is None or len(adminName) == 0:
        return None
    adminEmail = config.get_property('Project', 'adminEmail')
    adminPass = config.get_property('Project', 'adminPassword')
    if adminPass is None or len(adminPass) == 0:
        raise Exception('No password defined for admin account in configuration file.')

    # get current values
    currentMeta = dbConn.execute('''
        SELECT email, hash
        FROM aide_admin.user
        WHERE name = %s;
    ''', (adminName,), 1)
    if currentMeta is None or len(currentMeta) == 0:
        # no account found under this name; create new
        isNewAccount = True

    # check if changes
    if currentMeta is not None and len(currentMeta) > 0:
        currentMeta = currentMeta[0]
        if currentMeta['email'] != adminEmail:
            changes['adminEmail'] = True
        if not bcrypt.checkpw(adminPass.encode('utf8'), bytes(currentMeta['hash'])):
            changes['adminPassword'] = True

    if isNewAccount or len(changes) > 0:
        hash_val = UserMiddleware._create_hash(adminPass.encode('utf8'))
        sql = '''
            INSERT INTO aide_admin.user (name, email, hash, issuperuser)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
            SET email=EXCLUDED.email, hash=EXCLUDED.hash;
        '''
        values = (adminName, adminEmail, hash_val, True,)
        dbConn.execute(sql, values, None)

    return {
        'details': {
            'name': adminName,
            'email': adminEmail
        },
        'new_account': isNewAccount,
        'changes': changes
    }



def setupDB() -> None:
    config = Config()
    db_connector = Database(config)

    # read SQL skeleton
    with open(os.path.join(os.getcwd(), 'setup/db_create.sql'), 'r', encoding='utf-8') as f_sql:
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

    # setup
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

    setupDB()
