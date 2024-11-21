'''
    2019-24 Benjamin Kellenberger
'''

from typing import Tuple, Iterable, Union
from uuid import UUID
import json
from modules.AIWorker.backend.worker import functional
from modules.AIWorker.backend import fileserver
from util.logDecorator import LogDecorator
from util.helpers import get_class_executable



class AIWorker():
    '''
        Main AI model training/inference class.
    '''
    def __init__(self,
                 config,
                 db_connector,
                 passive_mode=False,
                 verbose_start=False) -> None:
        self.config = config

        if verbose_start:
            print('AIWorker'.ljust(LogDecorator.get_ljust_offset()), end='')

        try:
            self.db_connector = db_connector
            self.passive_mode = passive_mode
            self._init_fileserver()
        except Exception as exc:
            if verbose_start:
                LogDecorator.print_status('fail')
            raise Exception(f'Could not launch AIWorker (message: "{str(exc)}").') from exc

        if verbose_start:
            LogDecorator.print_status('ok')


    def _init_fileserver(self):
        '''
            The AIWorker has a special routine to detect whether the instance it is running on
            also hosts the file server. If it does, data are loaded directly from disk to avoid
            going through the loopback network.
        '''
        self.file_server = fileserver.FileServer(self.config)


    def _init_model_instance(self,
                             project: str,
                             model_library: str,
                             model_settings: str) -> object:
        # try to parse model settings
        if model_settings is not None and len(model_settings):
            if isinstance(model_settings, str):
                try:
                    model_settings = json.loads(model_settings)
                except Exception as err:
                    print(f'WARNING: could not read model options. Error message: {err}.')
                    model_settings = None
        else:
            model_settings = None

        # import class object
        model_class = get_class_executable(model_library)

        # create AI model instance
        return model_class(project=project,
                            config=self.config,
                            dbConnector=self.db_connector,
                            fileServer=self.file_server.get_secure_instance(project),
                            options=model_settings)


    def _init_al_criterion_instance(self,
                                    project: str,
                                    al_library: str,
                                    al_settings: str) -> object:
        '''
            Creates the Active Learning (AL) criterion provider instance.
        '''
        if al_library is None:
            # no AL criterion; AIDE tries to use model confidences by default
            return None

        # try to parse settings
        if al_settings is not None and len(al_settings):
            try:
                al_settings = json.loads(al_settings)
            except Exception as err:
                print(f'WARNING: could not read AL criterion options. Error message: {err}.')
                al_settings = None
        else:
            al_settings = None

        # import class object
        model_class = get_class_executable(al_library)

        # create AI model instance
        return model_class(project=project,
                            config=self.config,
                            dbConnector=self.db_connector,
                            fileServer=self.file_server.get_secure_instance(project),
                            options=al_settings)


    def _get_model_instance(self,
                            project: str,
                            model_settings_override=None) -> Tuple[object, object, int]:
        '''
            Returns the class instance of the model specified in the given
            project.
            TODO: cache models?
        '''
        # get model settings for project
        query_str = '''
            SELECT ai_model_library, ai_model_settings, inference_chunk_size FROM aide_admin.project
            WHERE shortname = %s;
        '''
        result = self.db_connector.execute(query_str,
                                           (project,),
                                           1)
        model_library = result[0]['ai_model_library']
        model_settings = (result[0]['ai_model_settings'] if model_settings_override is None \
                          else model_settings_override)

        # create new model instance
        model_instance = self._init_model_instance(project,
                                                   model_library,
                                                   model_settings)

        inference_chunk_size = result[0]['inference_chunk_size']
        chunk_size_limit = self.config.get_property('AIWorker',
                                                    'inference_batch_size_limit',
                                                    dtype=int,
                                                    fallback=-1)
        if inference_chunk_size is None:
            inference_chunk_size = chunk_size_limit
        elif chunk_size_limit > 0:
            inference_chunk_size = min(inference_chunk_size, chunk_size_limit)

        return model_instance, model_library, inference_chunk_size


    def _get_al_criterion_instance(self,
                                   project: str,
                                   model_settings_override=None) -> object:
        '''
            Returns the class instance of the Active Learning model
            specified in the project.
            TODO: cache models?
        '''
        # get model settings for project
        query_str = '''
            SELECT ai_alCriterion_library, ai_alCriterion_settings FROM aide_admin.project
            WHERE shortname = %s;
        '''
        result = self.db_connector.execute(query_str,
                                           (project,),
                                           1)
        model_library = result[0]['ai_alcriterion_library']
        model_settings = (result[0]['ai_alcriterion_settings'] if model_settings_override is None \
                          else model_settings_override)

        # create new model instance
        model_instance = self._init_al_criterion_instance(project,
                                                          model_library,
                                                          model_settings)

        return model_instance


    def aide_internal_notify(self, message: str) -> None:
        '''
            Used for AIDE administrative communication between AIController
            and AIWorker(s), e.g. for setting up queues.
        '''
        # not required (yet)
        pass


    def call_update_model(self,
                          num_epochs: int,
                          project: str,
                          ai_model_settings: dict=None) -> object:

        # get project-specific model
        model_instance, model_library, _ = self._get_model_instance(project, ai_model_settings)

        return functional._call_update_model(project,
                                             num_epochs,
                                             model_instance,
                                             model_library,
                                             self.db_connector)


    def call_train(self,
                   data: dict,
                   epoch: int,
                   num_epochs: int,
                   project: str,
                   is_subset: bool,
                   ai_model_settings: dict=None) -> object:

        # get project-specific model
        model_instance, model_library, _ = self._get_model_instance(project, ai_model_settings)

        return functional._call_train(project,
                                      data,
                                      epoch,
                                      num_epochs,
                                      is_subset,
                                      model_instance,
                                      model_library,
                                      self.db_connector)


    def call_average_model_states(self,
                                  epoch: int,
                                  num_epochs: int,
                                  project: str,
                                  ai_model_settings: dict=None) -> object:

        # get project-specific model
        model_instance, model_library, _ = self._get_model_instance(project, ai_model_settings)
        
        return functional._call_average_model_states(project,
                                                     epoch,
                                                     num_epochs,
                                                     model_instance,
                                                     model_library,
                                                     self.db_connector)


    def call_inference(self,
                       image_ids: Iterable[Union[str,UUID]],
                       epoch: int,
                       num_epochs: int,
                       project: str,
                       ai_model_settings: dict=None,
                       al_criterion_settings: dict=None) -> object:

        # get project-specific model and AL criterion
        model_instance, model_library, chunk_size = self._get_model_instance(project,
                                                                             ai_model_settings)
        al_criterion_instance = self._get_al_criterion_instance(project, al_criterion_settings)

        return functional._call_inference(project,
                                          image_ids,
                                          epoch,
                                          num_epochs,
                                          model_instance,
                                          model_library,
                                          al_criterion_instance,
                                          self.db_connector,
                                          chunk_size)


    def verify_model_state(self,
                           project: str,
                           model_library: str,
                           state_dict: bytes,
                           model_options: dict) -> None:
        '''
            Launches a dummy training-averaging-inference chain
            on a received model state and returns True if the chain
            could be executed without any errors (else False). Does
            not store anything in the database.
            Inputs:
                - project:      str, project shortname (used to retrieve
                                sample data)
                - modelLibrary: str, identifier of the AI model
                - stateDict:    bytes object, AI model state
                - modelOptions: str, model settings to be tested
                                (optional)
            
            Returns a dict with the following entries:
                - valid:    bool, True if the provided state dict and
                            (optionally) model options are valid (i.e.,
                            can be used to perform training, averaging,
                            and inference), or False otherwise.
                - messages: str, text describing the error(s) encounte-
                            red if there are any.
        '''
        #TODO
        raise NotImplementedError('Not yet implemented.')
