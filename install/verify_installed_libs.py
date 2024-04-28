'''
    Script that attempts to import installed libraries/packages required for AIDE to run properly.

    2024 Benjamin Kellenberger
'''

import argparse
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
    'rasterio',
    'torch',
    'detectron2'
)



def verify_libraries(raise_on_first_error: bool=False) -> None:
    '''
        Attempts to load list of required packages one by one. Prints all libraries to the command
        line that could not be imported properly.
    '''
    for lib in LIBS:
        try:
            importlib.import_module(lib)
        except ModuleNotFoundError as exc:
            if raise_on_first_error:
                raise exc
            print(f'{lib}: {exc}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Verify import of dependencies')
    parser.add_argument('--raise-on-error', type=int,
                        default=0,
                        help='Set to 1 to raise on first import error (default: 0)')
    args = parser.parse_args()
    verify_libraries(bool(args.raise_on_error))
