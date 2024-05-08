'''
    Wrapper for the Celery message broker concerning
    the AIWorker(s).

    2019-24 Benjamin Kellenberger
'''

import os
from celery import current_app

from modules.AIWorker.app import AIWorker
from modules.Database.app import Database
from util.configDef import Config



# init AIWorker
modules = os.environ['AIDE_MODULES']
passive_mode = (os.environ['PASSIVE_MODE']=='1' if 'PASSIVE_MODE' in os.environ else False) \
                or 'aiworker' not in modules.lower()
config = Config()
worker = AIWorker(config, Database(config), passive_mode)



@current_app.task(name='AIWorker.aide_internal_notify')
def aide_internal_notify(message):
    return worker.aide_internal_notify(message)



@current_app.task(name='AIWorker.call_update_model', rate_limit=1)
def call_update_model(blank,
                      num_epochs,
                      project):
    return worker.call_update_model(num_epochs, project)



@current_app.task(name='AIWorker.call_train', rate_limit=1)
def call_train(data,
               index,
               epoch,
               num_epochs,
               project,
               ai_model_settings):
    if len(data) == 2 and data[1] is None:
        # model update call preceded training task; ignore empty output of it
        data = data[0]

    is_subset = len(data) > 1
    if index < len(data):
        return worker.call_train(data[index],
                                 epoch,
                                 num_epochs,
                                 project,
                                 is_subset,
                                 ai_model_settings)

    # worker not needed
    print(f'[{project}] Subset {index} requested, but only {len(data)} chunk(s) provided. ' + \
        ' Skipping...')
    return 0



@current_app.task(name='AIWorker.call_average_model_states', rate_limit=1)
def call_average_model_states(blank,
                              epoch,
                              num_epochs,
                              project,
                              ai_model_settings):
    return worker.call_average_model_states(epoch,
                                            num_epochs,
                                            project,
                                            ai_model_settings)



@current_app.task(name='AIWorker.call_inference')
def call_inference(data,
                   index,
                   epoch,
                   num_epochs,
                   project,
                   ai_model_settings=None,
                   al_criterion_settings=None):
    if len(data) == 2 and data[1] is None:
        # model update call preceded inference task; ignore empty output of it
        data = data[0]

    if index < len(data):
        return worker.call_inference(data[index],
                                     epoch,
                                     num_epochs,
                                     project,
                                     ai_model_settings,
                                     al_criterion_settings)

    # worker not needed
    print(f'[{project}] Subset {index} requested, but only {len(data)} chunk(s) provided. ' + \
        ' Skipping...')
    return 0


@current_app.task(name='AIWorker.verify_model_state')
def verify_model_state(project):
    raise NotImplementedError('Not yet fully implemented nor used.')
    # return worker.verify_model_state(project)
