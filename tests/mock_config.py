'''
    Simple script that initializes an environment according to a mock configuration for unit tests.

    2024 Benjamin Kellenberge
'''

import os
import importlib
import shutil

# mock initialization
os.environ['AIDE_CONFIG_PATH'] = 'tests/mock_settings.ini'
os.environ['AIDE_MODULES'] = 'LabelUI,AIController,AIWorker,FileServer'

# initialize FileServer directories
cfg_mod = importlib.import_module('util.configDef')
config = getattr(cfg_mod, 'Config')()

STATIC_FILES_DIR = config.get_property('FileServer',
                                      'staticfiles_dir',
                                      dtype=str,
                                      fallback='/tmp/aide/files')

TEMP_FILES_DIR = config.get_property('FileServer',
                                    'tempfiles_dir',
                                    dtype=str,
                                    fallback='/tmp/aide/tempfiles')

os.makedirs(config.get_property('FileServer', 'staticfiles_dir'), exist_ok=True)
os.makedirs(config.get_property('FileServer', 'tempfiles_dir'), exist_ok=True)



def destroy() -> None:
    '''
        Cleaning up procedure
    '''
    for tempdir in (STATIC_FILES_DIR, TEMP_FILES_DIR):
        if os.path.exists(tempdir):
            shutil.rmtree(tempdir)
