'''
    2019-24 Benjamin Kellenberger
'''

import os
from typing import Optional, Any
import warnings
import builtins
from configparser import ConfigParser

from util.logDecorator import LogDecorator



class Config():
    '''
        Wrapper class for the AIDE configuration (settings.ini) file.
    '''
    def __init__(self,
                 override_config_path: str=None,
                 verbose_start: bool=False):
        if verbose_start:
            print('Reading configuration...'.ljust(LogDecorator.get_ljust_offset()), end='')
        if isinstance(override_config_path, str) and len(override_config_path):
            config_path = override_config_path
        elif 'AIDE_CONFIG_PATH' in os.environ:
            config_path = os.environ['AIDE_CONFIG_PATH']
        else:
            if verbose_start:
                LogDecorator.print_status('fail')
            raise ValueError('Neither system environment variable "AIDE_CONFIG_PATH" ' + \
                             'nor override path are set.')

        self.config = None
        try:
            self.config = ConfigParser()
            self.config.read(config_path)

            self.function_map = {
                str: self.config.get,
                bool: self.config.getboolean,
                int: self.config.getint,
                float: self.config.getfloat,
            }

        except Exception as exc:
            if verbose_start:
                LogDecorator.print_status('fail')
            raise Exception(f'Could not read configuration file (message: "{str(exc)}").')

        if verbose_start:
            LogDecorator.print_status('ok')


    def get_property(self,
                     module: str,
                     property_name: str,
                     dtype: Optional[type]=str,
                     fallback: Optional[Any]=None) -> any:
        '''
            Returns the property value under given "module" and "property_name", or else "fallback"
            (defaults to None) if it could not be found. Will attempt to perform typecasting if
            "data_type" is provided (default: str) and also returns None if typecasting fails.

            Inputs:

                - module:           str, name of the main module to draw property from (e.g.,
                                    "FileServer")
                - property_name:    str, name of the property to query
                - dtype:            type, optional typecasting argument (default: str)
                - fallback:         Any, optional return argument if property value could not be
                                    found or typecast.

            Returns:

                Any                 config value (or else None if error)
        '''
        try:
            return self.function_map.get(dtype, self.config.get)(module,
                                                                 property_name,
                                                                 fallback=fallback)
        except Exception as _:
            return fallback


     # pylint: disable=invalid-name,redefined-builtin
    def getProperty(self, module, propertyName, type=str, fallback=None):
        '''
            Legacy method for compatibility.
        '''
        warnings.warn('Function "getProperty" is deprecated and will be removed ' + \
                       'in a future release of AIDE.\n' + \
                       'Please use "get_property" instead.',
                       DeprecationWarning,
                       stacklevel=2)
        return self.get_property(module,
                                 propertyName,
                                 type,
                                 fallback)



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Get configuration entry programmatically.')
    parser.add_argument('--settings_filepath',
                        type=str,
                        help='Override directory of the settings.ini file. ' + \
                             'By default, environment variable "AIDE_CONFIG_PATH" will be read.')
    parser.add_argument('--section',
                        type=str,
                        help='Configuration file section.')
    parser.add_argument('--parameter',
                        type=str,
                        help='Parameter within the section.')
    parser.add_argument('--type',
                        type=str,
                        help='Parameter type. One of {"str" (default), "bool", "int", "float", ' + \
                             'None (everything else)}')
    parser.add_argument('--fallback',
                        type=str,
                        help='Fallback value, if parameter does not exist (optional)')
    args = parser.parse_args()

    if 'settings_filepath' in args and args.settings_filepath is not None:
        os.environ['AIDE_CONFIG_PATH'] = str(args.settings_filepath)

    if args.section is None or args.parameter is None:
        print('Usage: python configDef.py --section=<.ini file section> ' + \
              '--parameter=<section parameter name> [--fallback=<default value>]')

    else:
        try:
            DTYPE = getattr(builtins, args.type.lower())
        except AttributeError:
            DTYPE=None

        print(Config().get_property(args.section,
                                    args.parameter,
                                    dtype=DTYPE,
                                    fallback=args.fallback))
