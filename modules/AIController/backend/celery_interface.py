'''
    Wrapper for the Celery message broker concerning
    the AIController.

    2020-24 Benjamin Kellenberger
'''

import os
from typing import List, Iterable, Union
from datetime import datetime
from uuid import UUID
from celery import current_app

from modules.AIController.backend.functional import AIControllerWorker
from util.configDef import Config



# init AIController middleware
modules = os.environ['AIDE_MODULES']
passive_mode = (os.environ['PASSIVE_MODE']=='1' if 'PASSIVE_MODE' in os.environ else False) or \
                'aicontroller' not in modules.lower()
aim = AIControllerWorker(Config(), current_app)



@current_app.task(name='AIController.get_training_images')
def get_training_images(blank,
                        project: str,
                        epoch: int,
                        num_epochs: int,
                        min_timestamp: Union[datetime,str], #='lastState',
                        tags: Iterable,
                        include_golden_questions: bool=True,
                        min_num_anno_per_image: int=0,
                        max_num_images: int=None,
                        num_workers: int=1) -> List[UUID]:
    '''
        Interface for Celery task to return list of image UUIDs used for training.
    '''
    return aim.get_training_images(project,
                                   epoch,
                                   num_epochs,
                                   min_timestamp,
                                   tags,
                                   include_golden_questions,
                                   min_num_anno_per_image,
                                   max_num_images,
                                   num_workers)


@current_app.task(name='AIController.get_inference_images')
def get_inference_images(blank,
                         project: str,
                         epoch: int,
                         num_epochs: int,
                         tags: Iterable,
                         golden_questions_only: bool=False,
                         force_unlabeled: bool=False,
                         max_num_images: int=None,
                         num_workers: int=1) -> List[UUID]:
    '''
        Interface for Celery task to return list of image UUIDs to perform inference on.
    '''
    return aim.get_inference_images(project,
                                    epoch,
                                    num_epochs,
                                    tags,
                                    golden_questions_only,
                                    force_unlabeled,
                                    max_num_images,
                                    num_workers)


@current_app.task(name='AIController.delete_model_states')
def delete_model_states(project: str,
                        model_state_ids: Iterable[Union[UUID, str]]) -> List[UUID]:
    '''
        Interface for Celery task to delete model states with given UUID. Returns a list with
        invalid model state UUIDs (i.e., not found in database).
    '''
    return aim.delete_model_states(project, model_state_ids)


@current_app.task(name='AIController.get_model_training_statistics')
def get_model_training_statistics(project: str,
                                  model_state_ids: Iterable[Union[UUID, str]]=None,
                                  model_libraries: Iterable[str]=None,
                                  skip_imported_models: bool=True) -> dict:
    '''
        Interface for Celery task to return training statistics for optional model states and/or
        libraries.
    '''
    return aim.get_model_training_statistics(project,
                                             model_state_ids,
                                             model_libraries,
                                             skip_imported_models)


@current_app.task(name='AIController.duplicate_model_state')
def duplicate_model_state(project: str,
                          model_state_id: Union[UUID, str],
                          skip_if_latest: bool=True) -> str:
    '''
        Interface for Celery task to duplicate model state with given UUID. Returns UUID string of
        the duplicated state.
    '''
    return aim.duplicate_model_state(project,
                                     model_state_id,
                                     skip_if_latest)
