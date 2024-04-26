'''
    Helper scripts for installation, e.g. for obtaining compatible package versions.

    2024 Benjamin Kellenberger
'''

import os
import sys
import re
import argparse
import yaml



PT_INSTALL_STR_CONDA: str = \
    'conda install pytorch=={ptver} torchvision=={tvver} {custr} -c pytorch -c nvidia'
PT_INSTALL_STR_PIP: str = \
    'pip install torch=={ptver} torchvision=={tvver} ' + \
        '--index-url https://download.pytorch.org/whl/{cuidx}'


def compare_versions(ver_a: str,
                     ver_b: str,
                     common_denominator_only: bool=False) -> int:
    '''
        Receives two version strings (format major.minor(.minor) and compares them, returning 1 (if
        ver_a > ver_b), -1 (if ver_b > ver_a), and 0 if identical.

        Arguments:
            - "ver_a": str, first version string
            - "ver_b": str, second version string
            - "common_denominator_only": bool, stop comparison at smallest common minor if True
              (default False)
        
        Returns:
            - int, indicating relationship between "ver_a" and "ver_b"
    '''
    # split versions into components
    ver_a, ver_b = str(ver_a), str(ver_b)
    comp_a = [int(token) for token in ver_a.split('.')]
    comp_b = [int(token) for token in ver_b.split('.')]

    if common_denominator_only:
        comp_a += (len(comp_b) - len(comp_a)) * [0]
        comp_b += (len(comp_a) - len(comp_b)) * [0]

    for idx, val_a in enumerate(comp_a):
        if idx >= len(comp_b):
            return 0
        if val_a > comp_b[idx]:
            return 1
        if val_a < comp_b[idx]:
            return -1
    return 0



def installed_cuda_version() -> str:
    '''
        Attempts to query installed CUDA version. Returns version string (e.g., "12.3") if installed
        or None if unidentified/-able.
    '''
    has_smi = os.popen('command -v nvidia-smi').read().strip()
    if len(has_smi) == 0:
        return None
    smi_str = os.popen('nvidia-smi | tr \'[:upper:]\' \'[:lower:]\' | grep "cuda version:"').read()
    if 'cuda version' not in smi_str:
        return None
    version = re.sub(r'.*cuda version:\s*([0-9]+\.[0-9]+([0-9]+)?).*(\n)?$', r'\g<1>', smi_str)
    return version



def latest_pytorch_version(print_str: str=None,
                           with_cuda: bool=True) -> dict:
    '''
        Checks Python version of currently installed runtime, as well as the PyTorch wheel
        inventory. Returns the latest available and compatible version of torch (up to optionally
        specified argument "max_version"). Prints installation command (Conda or pip) if "print_str"
        is set.

        Arguments:
            - "print_str: str, one of None (default), "Conda", "pip". Prints install command to
              command line if provided.
            - "with_cuda": bool, will check for CUDA-compatible installations if True (default).
    '''
    try:
        # get current Python version (major.minor)
        pyver = re.sub(r'([0-9]+\.[0-9]+).*', r'\g<1>', sys.version.replace('\n', ''))

        # check if CUDA installed & get version
        device_platform = 'cpu'
        if with_cuda:
            cudaver = installed_cuda_version()
            if cudaver is not None:
                device_platform = cudaver

        # get all available PyTorch versions
        with open('install/lib_version_compatibilities.yaml', 'r', encoding='utf-8') as f_pt:
            pt_meta = yaml.safe_load(f_pt)
            pt_meta = pt_meta.get('VERSIONS', pt_meta)['PyTorch']

        # find latest compatible version
        best_match = {
            'cpu': None,
            'cuda': None,
            'cudaver': None,
            'tvver': None
        }
        for ptver, meta in pt_meta.items():
            target = 'cpu'
            match_min = compare_versions(pyver, meta['py'][0])
            match_max = compare_versions(pyver, meta['py'][1])

            if match_min < 0 or match_max > 0:
                # incompatible version of Python
                continue

            if device_platform != 'cpu':
                # match CUDA version as well
                cudamatches = [compare_versions(cudaver, cuver) for cuver in meta['cu']]
                if max(cudamatches) >= 0:
                    # CUDA version matches
                    target = 'cuda'
                    cudamatch = max(enumerate(cudamatches), key=lambda x: x[1])[0]
                    best_match['cudaver'] = meta['cu'][cudamatch]

            if best_match[target] is None or compare_versions(ptver, best_match[target]) > 0:
                best_match[target] = ptver
                best_match['tvver'] = meta['tv']

        # assemble install string
        if best_match['cuda'] is not None:
            format_kwargs = {
                'ptver': str(best_match['cuda']),
                'tvver': str(best_match['tvver']),
                'custr': f'pytorch-cuda={best_match["cudaver"]}',
                'cuidx': 'cu'+str(best_match['cudaver']).replace('.', '')
            }
        else:
            # CPU
            format_kwargs = {
                'ptver': str(best_match['cpu']),
                'tvver': str(best_match['tvver']),
                'custr': 'cpuonly',
                'cuidx': 'cpu'
            }

        if print_str is not None:
            if print_str.lower() == 'conda':
                print(PT_INSTALL_STR_CONDA.format_map(format_kwargs))
            else:
                # pip
                print(PT_INSTALL_STR_PIP.format_map(format_kwargs))
        return best_match
    except Exception as exc:
        if print_str is not None:
            print('echo -e "ERROR: could not automatically fetch PyTorch version ' + \
                    f'(message: {exc}).')
        else:
            raise exc
        return None



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Installation helpers (compatibility, etc.)')
    # parser.add_argument('--lib', type=str,
    #                     default='PyTorch',
    #                     help='Which library to check (currently defaults to "PyTorch").')
    parser.add_argument('--with-cuda', type=int,
                        default=1,
                        help='Set to 1 to query for PyTorch version with CUDA support.')
    parser.add_argument('--format', type=str,
                        default='pip',
                        help='Installer command format; one of "pip" (default), "conda".')
    args = parser.parse_args()

    latest_pytorch_version(print_str=args.format.lower(),
                           with_cuda=bool(args.with_cuda))
