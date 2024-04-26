'''
    AIDE version identifier.
    Format:
        "<major>.<minor>.<nightly build date><suffix>"

    where the build date is formatted as "YYMMDD".
    An optional suffix like "b" might be provided in
    case of multiple builds per day.

    2020-24 Benjamin Kellenberger
'''

import datetime



AIDE_VERSION = '3.0.240426'

# minimum required version for FileServer, due to recent changes
MIN_FILESERVER_VERSION = '3.0.230109c'

# model marketplace format version exported by the current AIDE implementation
MODEL_MARKETPLACE_VERSION = 1.0



def get_version_components(version: str=AIDE_VERSION) -> dict:
    '''
        Returns dict of major, minor, nightly, suffix components of AIDE version string.
    '''
    try:
        tokens = version.split('.')
        suffix = tokens[-1][-1]
        if suffix.isnumeric():
            suffix = None
            nightly = tokens[-1]
        else:
            nightly = tokens[-1][:-1]

        return {
            'major': int(tokens[0]),
            'minor': int(tokens[1]),
            'nightly': datetime.datetime.strptime(nightly, '%y%m%d'),
            'suffix': suffix
        }
    except Exception:
        return None



def compare_versions(version_a: str,
                     version_b: str) -> int:
    '''
        Receives two version str and tries to parse them.
        Returns:
            -1 if "version_a" is older than "version_b"
             0 if they are identical
             1 if "version_a" is newer than "version_b"
            None if either or both of the str could not be parsed
    '''
    try:
        if version_a.lower() == version_b.lower():
            return 0

        t_a = get_version_components(version_a)
        t_b = get_version_components(version_b)

        if t_a['major'] > t_b['major']:
            return 1
        if t_a['major'] < t_b['major']:
            return -1
        if t_a['minor'] > t_b['minor']:
            return 1
        if t_a['minor'] < t_b['minor']:
            return -1
        if t_a['nightly'] > t_b['nightly']:
            return 1
        if t_a['nightly'] < t_b['nightly']:
            return -1
        if t_a['suffix'] is not None and t_b['suffix'] is not None:
            return (1 if t_a['suffix'] > t_b['suffix'] else -1)
        if t_a['suffix'] is not None:
            return 1
        return -1
    except Exception:
        return None
