'''
    Unit tests for installed AI models.

    2024 Benjamin Kellenberger
'''

import os

from tests import mock_config
from constants.version import AIDE_VERSION
from util.configDef import Config
from modules.Database.app import Database
from modules.AIDEAdmin.app import AdminMiddleware
from modules.AIController.backend.functional import AIControllerWorker
from modules.AIWorker.app import AIWorker
from modules.AIWorker.backend.fileserver import FileServer



# def get_installed_models():
#     pass



if __name__ == '__main__':

    # initialize directories according to config
    config = Config()

    os.makedirs(config.get_property('FileServer', 'staticfiles_dir'), exist_ok=True)
    os.makedirs(config.get_property('FileServer', 'tempfiles_dir'), exist_ok=True)

    # initialize required modules
    db_connector = Database(config)
    aiw = AIWorker(config, db_connector, True)
    aicw = AIControllerWorker(config, None)

    # check if AIDE file server is reachable
    admin = AdminMiddleware(config, db_connector)
    conn_details = admin.get_service_details(True, False)
    fs_version = conn_details['FileServer']['aide_version']
    # if not isinstance(fs_version, str):
    #     # no file server running
    #     raise Exception('''ERROR: AIDE file server is not running, but required for running models.
    #                        Make sure to launch it prior to running this script.''')
    # if fs_version != AIDE_VERSION:
    #     print(f'''WARNING: the AIDE version of File Server instance ({fs_version})
    #               differs from this one ({AIDE_VERSION}).''')

    print('modules loaded')


    # all done; clean up
    mock_config.destroy()
