'''
    Miscellaneous helper functions.

    2019-24 Benjamin Kellenberger
'''

from typing import Union, Tuple, Any, Iterable
from types import ModuleType
import os
import sys
import importlib
import unicodedata
import random
import re
import decimal
import uuid
import json
from datetime import datetime
import socket
from urllib.parse import urlsplit
import html
import base64
import bcrypt
import numpy as np
import pytz
import netifaces
import requests
from PIL import Image, ImageColor
import torch
from torch.nn import functional as F

from util.configDef import Config
from util import drivers



FILENAMES_PROHIBITED_CHARS = (
    '&lt;',
    '<',
    '>',
    '&gt;',
    '..',
    '/',
    '\\',
    '|',
    '?',
    '*',
    ':'    # for macOS
)


DEFAULT_BAND_CONFIG = (
    'Red',
    'Green',
    'Blue'
)

DEFAULT_RENDER_CONFIG = {
    "bands": {
        "indices": {
            "red": 0,
            "green": 1,
            "blue": 2
        }
    },
    "grayscale": False,
    "white_on_black": False,
    "contrast": {
        "percentile": {
            "min": 0.0,
            "max": 100.0
        }
    },
    "brightness": 0
}

DEFAULT_MAPSERVER_SETTINGS = {
    'enabled': False,
    'layers': {
        'image-outlines': {
            'name': 'Image outlines',
            'services': {
                'wfs': {
                    'enabled': False,
                    'acl': {
                        'non_admin': False
                    }
                }
            }
        },
        'images': {
            'name': 'Images',
            'services': {
                'wms': {
                    'enabled': False,
                    'acl': {
                        'non_admin': False
                    },
                    'options': {
                        'render_config': DEFAULT_RENDER_CONFIG
                    }
                },
                'wcs': {
                    'enabled': False,
                    'acl': {
                        'non_admin': False
                    }
                }
            }
        }
    }
}


def to_number(value: Union[int,float,str]) -> Union[int,float]:
    '''
        Auto-converts objects to either int or float; returns Nonen if unparseable.
    '''
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except Exception:
            return None
    return None



def array_split(arr: list, size: int) -> list:
    '''
        Receives a list and divides it into sublists of given size.
    '''
    arrs = []
    while len(arr) > size:
        pice = arr[:size]
        arrs.append(pice)
        arr = arr[size:]
    arrs.append(arr)
    return arrs



def current_time() -> datetime:
    '''
        Returns the current time with UTC timestamp.
    '''
    return datetime.now(tz=pytz.utc)



def is_binary(file_path: str) -> bool:
    '''
        Returns True if the file is a binary file, False if it is a text file. Raises an Exception
        if the file could not be found. Source:
        https://stackoverflow.com/questions/898669/how-can-i-detect-if-a-file-is-binary-non-text-in-python
    '''
    textchars = bytearray({7,8,9,10,12,13,27} | set(range(0x20, 0x100)) - {0x7f})
    with open(file_path, 'rb') as f:
        return bool(f.read(1024).translate(None, textchars))



def slugify(value: str, allow_unicode: bool=False) -> str:
    '''
        Taken from https://github.com/django/django/blob/master/django/utils/text.py Convert to
        ASCII if 'allow_unicode' is False. Convert spaces or repeated dashes to single dashes.
        Remove characters that aren't alphanumerics, underscores, or hyphens. Convert to lowercase.
        Also strip leading and trailing whitespace, dashes, and underscores.
    '''
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')



def get_class_executable(path: str) -> ModuleType:
    '''
        Loads a Python class path (e.g. package.subpackage.classFile.className) and returns the
        class executable (under 'className').
    '''
    # split classPath into path and executable name
    idx = path.rfind('.')
    class_path, executable_name = path[0:idx], path[idx+1:]
    exec_file = importlib.import_module(class_path)
    return getattr(exec_file, executable_name)



def get_library_available(lib_name: str, check_import: bool=False) -> bool:
    '''
        Checks whether a Python library is available and returns a bool accordingly. Library names
        can be dot-separated as common in Python imports. If "checkImport" is True, the library is
        attempt- ed to be actually imported; if this fails, False is returned.
    '''
    try:
        if sys.version_info[1] <= 3:
            if importlib.util.find_spec(lib_name) is None:
                return False
        else:
            if importlib.util.find_spec(lib_name) is None:
                return False

        if check_import:
            importlib.import_module(lib_name)

        return True
    except Exception:
        return False



def check_args(options: dict, default_options: dict) -> dict:
    '''
        Compares a dictionary of objects ('options') with a set of 'defaultOptions'
        options and copies entries from the default set to the provided options
        if they are not in there.
    '''
    def __check(options_check: dict, default: dict) -> dict:
        if not isinstance(default, dict):
            return options_check
        for key in default.keys():
            if not key in options_check:
                options_check[key] = default[key]
            if not key == 'transform':
                options_check[key] = __check(options_check[key], default[key])
        return options_check
    if options is None or not isinstance(options, dict):
        return default_options
    return __check(options, default_options)



def parse_boolean(boolean: Union[bool,int,str]) -> bool:
    '''
        Performs parsing of various specifications of a boolean:
        True, 'True', 'true', 't', 'yes', '1', etc.
    '''
    if isinstance(boolean, bool):
        return boolean
    if isinstance(boolean, int):
        return bool(boolean)
    if isinstance(boolean, str):
        boolean = boolean.lower()
        if boolean.startswith('t') or boolean == '1' or boolean.startswith('y'):
            return True
        return False
    return False



def parse_parameters(data: dict,
                     params: list,
                     absent_ok: bool=True,
                     escape: bool=True,
                     none_ok: bool=True) -> Tuple[list,list]:
    '''
        Accepts a dict (data) and list (params) and assembles
        an output list of the entries in data under keys of params, in order of
        the latter.
        If params is a list of lists, the first entry of the nested list is the
        key, and the second the data type to which the value will be cast.
        Raises an Exception if typecasting fails.
        If absent_ok is True, missing keys will be skipped.
        If escape is True, sensitive characters will be escaped from strings.
        If none_ok is True, values may be None instead of the given data type.

        Also returns a list of the keys that were eventually added.
    '''
    output_vals = []
    output_keys = []
    for param in params:
        if isinstance(param, str):
            next_key = param
            data_type = str
        else:
            next_key = param[0]
            data_type = param[1]

        if not next_key in data and absent_ok:
            continue

        value = data[next_key]
        if escape and isinstance(value, str):
            value = html.escape(value)
        if not none_ok and value is not None:
            value = data_type(value)
        output_vals.append(value)
        output_keys.append(next_key)
    return output_vals, output_keys



class CustomJSONEncoder(json.JSONEncoder):
    '''
        Encoder for JSON serialization that auto-converts common, non-encodeable data types like
        UUID, Decimal, etc.
    '''
    def default(self,
                o: Union[uuid.UUID,decimal.Decimal,Any]) -> Union[str,float,Any]:
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, decimal.Decimal):
            return float(o)
        return json.JSONEncoder.default(self, o)



def json_dumps(*args: list, **kwargs: dict) -> str:
    '''
        Custom JSON dump to string function that can auto-convert objects to strings.
    '''
    return json.dumps(*args, ensure_ascii=False, cls=CustomJSONEncoder, **kwargs).encode('utf8')



def create_hash(password: bytes, salt_num_rounds: int=12) -> bytes:
    '''
        Receives a password as bytes and number of salt rounds and creates a salted password hash.

        Args:
            - "password":           bytes, encoded password string
            - "salt_num_rounds":    int, number of salt rounds (default: 12)

        Returns:
            bytes, hashed and salted password
    '''
    return bcrypt.hashpw(password, bcrypt.gensalt(salt_num_rounds))



def is_file_server(config: Config) -> bool:
    '''
        Returns True if the current instance is a valid file server. For this, the following two
        properties must hold:
            - the "staticfiles_dir" property under "[FileServer]" in the configuration.ini file must
              be a valid directory on this machine; 
            - environment variable "AIDE_MODULES" must be set to contain the string "FileServer"
              (check is performed without case)
    '''
    fs_dir = config.get_property('FileServer',
                                 'staticfiles_dir',
                                 dtype=str,
                                 fallback=None)
    if fs_dir is None:
        return False
    return ('fileserver' in os.environ.get('AIDE_MODULES', '').lower() and \
        (os.path.isdir(fs_dir) or \
            (os.path.islink(fs_dir) and os.path.exists(os.readlink(fs_dir)))
        )
    )



def is_localhost(base_uri: str) -> bool:
    '''
        Receives a URI and checks whether it points to this host ("localhost", "/", same socket
        name, etc.). Returns True if it is the same machine, and False otherwise.
    '''
    # pylint: disable=c-extension-no-member

    # check for explicit localhost or hostname appearance in URL
    localhosts = ['localhost', socket.gethostname()]
    interfaces = netifaces.interfaces()
    for i in interfaces:
        iface = netifaces.ifaddresses(i).get(netifaces.AF_INET)
        if iface is not None:
            for j in iface:
                localhosts.append(j['addr'])

    base_uri_fragments = urlsplit(base_uri)
    base_uri_stripped = base_uri_fragments.netloc
    for host in localhosts:
        if base_uri_stripped.startswith(host):
            return True

    # also check for local addresses that do not even specify the hostname (e.g. '/files' or just
    # 'files')
    if not base_uri.startswith('http'):
        return True

    # all checks failed; file server is running on another machine
    return False



def is_ai_task(task_name: str) -> bool:
    '''
        Returns True if the taskName (str) is part of the AI task chain, or False if not (e.g.,
        another type of task).
    '''
    task_n = str(task_name).lower()
    return task_n.startswith('aiworker') or \
        task_n in ('aicontroller.get_training_images', 'aicontroller.get_inference_images')



def list_directory(base_dir: str,
                   recursive: bool=False,
                   images_only: bool=True) -> set:
    '''
        Similar to glob's recursive file listing, but implemented so that circular softlinks are
        avoided. Removes the base_dir part (with trailing separator) from the files returned.
    '''
    if not images_only and len(drivers.VALID_IMAGE_EXTENSIONS) == 0:
        drivers.init_drivers(False)         # should not be required
    files_disk = set()
    if not base_dir.endswith(os.sep):
        base_dir += os.sep
    def _scan_recursively(imgs, base_dir, file_dir, recursive):
        if not os.path.isdir(file_dir):     # also understands symbolic links
            imgs.add(file_dir)
            return imgs
        files = os.listdir(file_dir)
        for file in files:
            path = os.path.join(file_dir, file)
            ext = os.path.splitext(file)[1].lower()
            if os.path.isfile(path) and (not images_only or ext in drivers.VALID_IMAGE_EXTENSIONS):
                imgs.add(path)
            elif os.path.islink(path):
                if os.readlink(path) in base_dir:
                    # circular link; avoid
                    continue
                if recursive:
                    imgs = _scan_recursively(imgs, base_dir, path, True)
            elif os.path.isdir(path) and recursive:
                imgs = _scan_recursively(imgs, base_dir, path, True)
        return imgs

    files_scanned = _scan_recursively(set(), base_dir, base_dir, recursive)
    for file in files_scanned:
        files_disk.add(file.replace(base_dir, ''))
    return files_disk



def file_list_to_hierarchy(file_list: Iterable) -> dict:
    '''
        Receives an Iterable of file names and converts it into a nested dict of dicts,
        corresponding to the folder hierarchy.
    '''
    assert isinstance(file_list, Iterable), 'Provided input is not an iterable list of files.'

    def _embed_file(tree, tokens, is_dir):
        if not isinstance(tree, dict):
            return
        if isinstance(tokens, str):
            if is_dir:
                tree[tokens] = {}
            else:
                tree[tokens] = None
        elif len(tokens) == 1:
            if is_dir:
                tree[tokens[0]] = {}
            else:
                tree[tokens[0]] = None
        else:
            if tokens[0] not in tree:
                tree[tokens[0]] = {}
            _embed_file(tree[tokens[0]], tokens[1:], is_dir)

    hierarchy = {}
    for file in file_list:
        tokens = file.split(os.sep)
        _embed_file(hierarchy, tokens, os.path.isdir(file))
    return hierarchy



def file_hierarchy_to_list(hierarchy: dict) -> list:
    '''
        Receives a dict of dicts of files and returns a flattened list of files accordingly.
    '''
    assert isinstance(hierarchy, dict), 'Provided input is not a hierarchy of files.'

    file_list = []
    def _flatten_tree(tree, dir_base):
        if isinstance(tree, dict):
            for key in tree.keys():
                _flatten_tree(tree[key], os.path.join(dir_base, key))
        else:
            file_list.append(dir_base)
    _flatten_tree(hierarchy, '')
    return file_list



def rgb_to_hex(rgb: Iterable[int]) -> str:
    '''
        Receives a tuple/list with three int values and returns an
        HTML/CSS-compliant hex color string in format:
            "#RRGGBB"
    '''
    # pylint: disable=consider-using-f-string

    def clamp(x: int) -> int:
        return max(0, min(x, 255))

    return '#{0:02x}{1:02x}{2:02x}'.format(clamp(rgb[0]), clamp(rgb[1]), clamp(rgb[2]))



def hex_to_rgb(hex_str: str) -> Tuple[int]:
    '''
        Receives a HTML/CSS-compliant hex color string of one of the following formats (hash symbol
        optional):
            "#RRGGBB"
            "#RGB"
        and returns a tuple of (Red, Green, Blue) values in the range of [0, 255].
    '''
    if hex_str is None:
        return None
    assert isinstance(hex_str, str), f'ERROR: "{str(hex_str)}" is not a valid string.'
    if not hex_str.startswith('#'):
        hex_str = '#' + hex_str
    assert len(hex_str)>1, 'ERROR: the provided string is empty.'

    return ImageColor.getrgb(hex_str)



def offset_color(color: str,
                 excluded: set=None,
                 distance: int=0) -> Union[np.ndarray,str]:
    '''
        Receives a "color" (hex string) and a set of "excluded" color hex strings. Adjusts the color
        value up or down until its sum of absolute differences of RGB uint8 color values is larger
        than "distance" to the closest color in "excluded". Returns the modified color value as hex
        string accordingly.

        Used to adjust colors for segmentation projects (required due to anti-aliasing effects of
        HTML canvas).

        #TODO: offsetting colors slightly could bring them too close to the next one again...
    '''
    if excluded is None or len(excluded) == 0:
        return color

    color_rgb = np.array(hex_to_rgb(color))
    excluded_rgb = set()
    for ex in excluded:
        excluded_rgb.add(hex_to_rgb(ex))
    excluded_rgb = np.array(list(excluded_rgb))

    dists = np.sum(np.abs(excluded_rgb - color_rgb), 1)
    if np.all(dists > distance):
        # color is already sufficiently spaced apart
        return color

    # need to offset; get closest
    closest = np.argmin(dists)
    component_diffs = excluded_rgb[closest,:] - color_rgb

    # adjust in direction of difference
    diff_pos = np.where(component_diffs != 0)[0]
    if len(diff_pos) == 0:
        diff_pos = np.array([0,1,2])

    color_rgb[diff_pos] += (np.sign(component_diffs[diff_pos]) * \
                                component_diffs[diff_pos] * \
                                    max(1, distance/len(diff_pos))).astype(color_rgb.dtype)
    return rgb_to_hex(color_rgb.astype(np.uint8).tolist())



def random_hex_color(excluded: set=None, distance: int=0) -> str:
    '''
        Creates a random HTML/CSS-compliant hex color string that is not already
        in the optional set/dict/list/tuple of "excluded" colors.

        If "distance" is an int or float, colors must be spaced apart by more
        than this value in terms of absolute summed numerical RGB differences.
    '''

    # create unique random color
    random_color = f'#{random.randint(10, 0xFFFFF0):06x}'

    #offset if needed
    if distance > 0 and excluded is not None and len(excluded) > 0:
        random_color = offset_color(random_color, excluded, distance)
    return random_color



def image_to_base64(image: Image) -> Tuple[str,int,int]:
    '''
        Receives a PIL image and converts it into a base64 string. Returns that string plus the
        width and height of the image.
    '''
    data_array = np.array(image).astype(np.uint8)
    b64str = base64.b64encode(data_array.ravel()).decode('utf-8')
    return b64str, image.width, image.height



def base64_to_image(base64str: str,
                    width: int,
                    height: int,
                    to_pil: bool=True,
                    attempt_rescale_if_needed: bool=False,
                    interpolation: str='nearest') -> Image:
    '''
        Receives a base64-encoded string as stored in AIDE's database (e.g. for segmentation masks)
        and returns a PIL image with its contents if "to_pil" is True (default), or an ndarray
        otherwise.

        Args:
            - "base64str":                  str, base64-encoded string of image
            - "width":                      int, image width in pixels
            - "height":                     int, image height in pixels
            - "to_pil":                     bool, returns PIL.Image if True (default), else
                                            Numpy.ndarray
            - "attempt_rescale_if_needed":  bool, tries to identify the actual size based on
                                            width/height aspect ratio if True, else raises an
                                            exception (default)
            - "interpolation":              str, interpolation mode if size mismatch could be solved
                                            to scale image back up to target size
    '''
    #TODO: adjust for LabelUI restrictions (determine aspect ratio > segmask size > resize with
    #nearest)
    raster = np.frombuffer(base64.b64decode(base64str), dtype=np.uint8)
    size = (int(height),int(width),)
    if size[0] * size[1] != len(raster):
        if attempt_rescale_if_needed:
            width_actual = np.sqrt(float(width)/float(height) * float(len(raster)))
            if np.mod(len(raster) / np.ceil(width_actual), 1) == 0:
                size = (int(len(raster)/np.ceil(width_actual)), int(np.ceil(width_actual)))
            elif np.mod(len(raster) / np.floor(width_actual), 1) == 0:
                size = (int(len(raster)/np.floor(width_actual)), int(np.floor(width_actual)))
            else:
                # neither rounding method worked
                raise ArithmeticError(
                    f'Could not properly infer dimensions for base64 buffer of size {len(raster)}.')
        else:
            raise AttributeError(f'Invalid dimensions ({width} x {height} != {len(raster)})')
    raster = np.reshape(raster, size)
    if raster.shape[0] != height or raster.shape[1] != width:
        # rescale back up
        raster = F.upsample(torch.from_numpy(raster).unsqueeze(0).unsqueeze(0),
                            (height, width),
                            mode=interpolation).squeeze().numpy()
    if not to_pil:
        return raster
    image = Image.fromarray(raster)
    return image



def download_file(url: str, local_filename: str=None) -> str:
    '''
        Source:
        https://stackoverflow.com/questions/16694907/download-large-file-in-python-with-requests
    '''
    if local_filename is None:
        local_filename = url.split('/')[-1]
    with requests.get(url, stream=True, timeout=180) as req:
        req.raise_for_status()
        with open(local_filename, 'wb') as f_req:
            for chunk in req.iter_content(chunk_size=8192):
                f_req.write(chunk)
    return local_filename
