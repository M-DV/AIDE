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
passiveMode = (os.environ['PASSIVE_MODE']=='1' if 'PASSIVE_MODE' in os.environ else False) or \
                'aicontroller' not in modules.lower()
aim = AIControllerWorker(Config(), current_app)



@current_app.task(name='AIController.get_training_images')
def get_training_images(blank,
                        project: str,
                        epoch: int,
                        numEpochs: int,
                        minTimestamp: Union[datetime,str]='lastState',
                        includeGoldenQuestions: bool=True,
                        minNumAnnoPerImage: int=0,
                        maxNumImages: int=None,
                        numWorkers: int=1) -> List[UUID]:
    '''
        Interface for Celery task to return list of image UUIDs used for training.
    '''
    return aim.get_training_images(project,
                                   epoch,
                                   numEpochs,
                                   minTimestamp,
                                   includeGoldenQuestions,
                                   minNumAnnoPerImage,
                                   maxNumImages,
                                   numWorkers)


@current_app.task(name='AIController.get_inference_images')
def get_inference_images(blank,
                         project: str,
                         epoch: int,
                         numEpochs: int,
                         goldenQuestionsOnly: bool=False,
                         forceUnlabeled: bool=False,
                         maxNumImages: int=None,
                         numWorkers: int=1) -> List[UUID]:
    '''
        Interface for Celery task to return list of image UUIDs to perform inference on.
    '''
    return aim.get_inference_images(project,
                                    epoch,
                                    numEpochs,
                                    goldenQuestionsOnly,
                                    forceUnlabeled,
                                    maxNumImages,
                                    numWorkers)


@current_app.task(name='AIController.delete_model_states')
def delete_model_states(project: str,
                        modelStateIDs: Iterable[Union[UUID, str]]) -> List[UUID]:
    '''
        Interface for Celery task to delete model states with given UUID. Returns a list with
        invalid model state UUIDs (i.e., not found in database).
    '''
    return aim.delete_model_states(project, modelStateIDs)


@current_app.task(name='AIController.get_model_training_statistics')
def get_model_training_statistics(project: str,
                                  modelStateIDs: Iterable[Union[UUID, str]]=None,
                                  modelLibraries: Iterable[str]=None,
                                  skipImportedModels: bool=True) -> dict:
    '''
        Interface for Celery task to return training statistics for optional model states and/or
        libraries.
    '''
    return aim.get_model_training_statistics(project,
                                             modelStateIDs,
                                             modelLibraries,
                                             skipImportedModels)


@current_app.task(name='AIController.duplicate_model_state')
def duplicate_model_state(project: str,
                          modelStateID: Union[UUID, str],
                          skipIfLatest: bool=True) -> str:
    '''
        Interface for Celery task to duplicate model state with given UUID. Returns UUID string of
        the duplicated state.
    '''
    return aim.duplicate_model_state(project, modelStateID, skipIfLatest)
