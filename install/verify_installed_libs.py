'''
    Script that attempts to import installed libraries/packages required for AIDE to run properly.

    2024 Benjamin Kellenberger
'''

from typing import Optional, List
import argparse
import importlib



# required package libraries
LIBS_REQUIRED: tuple= (
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
    'torch'
)

# optional package libraries (for certain models)
LIBS_OPTIONAL: tuple = (
    'detectron2',
    'yolov5'
)



def verify_libraries(verify_optional_libs: bool=True,
                     raise_on_first_error: bool=False,
                     libs_ignore: Optional[List[str]]=None) -> None:
    '''
        Attempts to load list of required packages one by one. Prints all libraries to the command
        line that could not be imported properly.
    '''
    if libs_ignore is None:
        libs_ignore = []
    libs = LIBS_REQUIRED
    if verify_optional_libs:
        libs += LIBS_OPTIONAL
    for lib in libs:
        if lib in libs_ignore:
            continue
        try:
            importlib.import_module(lib)
        except ModuleNotFoundError as exc:
            if raise_on_first_error:
                raise exc
            print(f'{lib}: {exc}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Verify import of dependencies')
    parser.add_argument('--verify-optional', type=int,
                        default=1,
                        help='Set to 0 to only verify requried libraries (default: 1).')
    parser.add_argument('--raise-on-error', type=int,
                        default=0,
                        help='Set to 1 to raise on first import error (default: 0).')
    parser.add_argument('--libs-ignore', type=str, nargs='?', required=False,
                        help='Libraries to skip checking (e.g., for unit tests).')
    args = parser.parse_args()
    verify_libraries(bool(args.verify_optional),
                     bool(args.raise_on_error),
                     args.libs_ignore)
