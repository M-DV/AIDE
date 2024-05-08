'''
    Common functionalities for Celery workers (AIController, AIWorker, FileServer).

    2020-24 Benjamin Kellenberger
'''

import os
from celery import current_app
from constants.version import AIDE_VERSION



def _get_modules() -> dict:
    modules = os.environ['AIDE_MODULES'].split(',')
    modules = set(m.strip().lower() for m in modules)
    return {
        'AIController': ('aicontroller' in modules),
        'AIWorker': ('aiworker' in modules),
        'FileServer': ('fileserver' in modules)
    }



@current_app.task(name='general.get_worker_details')
def get_worker_details() -> dict:
    '''
        Returns properties of the current AIWorker (AIDE version, etc.)
    '''
    # get modules
    return {
        'aide_version': AIDE_VERSION,
        'modules': _get_modules()
        #TODO: GPU capabilities, CPU?
    }



def get_celery_worker_details() -> dict:
    '''
        Queries all Celery workers for their details (name, URL, capabilities, AIDE version,
        etc.)
    '''
    result = {}

    inspect = current_app.control.inspect()
    workers = inspect.stats()

    if workers is None or len(workers) == 0:
        return result

    for worker in workers:
        aiw_v = get_worker_details.s()
        try:
            res = aiw_v.apply_async(queue=worker)
            res = res.get(timeout=20)                   #TODO: timeout (in seconds)
            if res is None:
                raise TimeoutError('connection timeout')
            result[worker] = res
            result[worker]['online'] = True
        except Exception as exc:
            result[worker] = {
                'online': False,
                'message': str(exc)
            }
    return result
