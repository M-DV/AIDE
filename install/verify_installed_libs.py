'''
    Script that attempts to import installed libraries/packages required for AIDE to run properly.

    2024 Benjamin Kellenberger
'''

import importlib



# required package libraries
LIBS: tuple= (
    'bottle',
    'gunicorn',
    'psycopg2',
    'tqdm',
    'bcrypt',
    'netifaces',
    'PIL',
    'numpy',
    'requests',
    'celery',
    'cv2',
    'torch',
    'detectron2'
)



def verify_libraries() -> None:
    '''
        Attempts to load list of required packages one by one. Prints all libraries to the command
        line that could not be imported properly.
    '''
    for lib in LIBS:
        try:
            importlib.import_module(lib)
        except Exception:
            print(lib)



if __name__ == '__main__':
    verify_libraries()
