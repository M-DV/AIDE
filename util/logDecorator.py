'''
    Class for pretty-printing startup messages and statuses to the command line.

    2021-24 Benjamin Kellenberger
'''

import os


class LogDecorator:
    '''
        Console formatter for adjusted strings. Used for e.g. module startup status display.
    '''
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    @staticmethod
    def get_ljust_offset():
        '''
            Returns the number of characters in a line on the terminal minus six for status messages
            (e.g., "[ OK ]", "[FAIL]"). Defaults to 74 if undeterminable (assumes an 80-character
            console).
        '''
        try:
            return os.get_terminal_size().columns - 6
        except Exception:
            return 74

    @staticmethod
    def print_status(status: str,
                     color: str=None) -> None:
        '''
            Prints a status text to the console (end of line), with optional color if provided.
        '''
        if status.lower() == 'ok':
            print(f'{LogDecorator.OKGREEN}[ OK ]{LogDecorator.ENDC}')
        elif status.lower() == 'warn':
            print(f'{LogDecorator.WARNING}[WARN]{LogDecorator.ENDC}')
        elif status.lower() == 'fail':
            print(f'{LogDecorator.FAIL}[FAIL]{LogDecorator.ENDC}')
        else:
            if color is not None:
                print(f'{getattr(LogDecorator, color)}[{status}]{LogDecorator.ENDC}')
            else:
                print(f'[{status}]')
