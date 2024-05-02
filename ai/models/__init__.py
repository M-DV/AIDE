'''
    Parent model class, providing code shells for the AIWorker.

    2019-24 Benjamin Kellenberger
'''

from typing import Any, Union, Iterable



class AIModel:
    '''
        {aremt} base class for general AI model.
    '''
    def __init__(self, project, config, dbConnector, fileServer, options=None):
        '''
            Model constructor. This is called by both the AIWorker and AIController
            modules when starting up.
            Args:
                "project":      str, name of the current AIDE project
                "config":       Configuration for the platform
                "dbConnector":  Access to the project database
                "fileServer":   Access to the instance storing the images
                "options":      A custom set of options in JSON format for this model
        '''
        self.project = project
        self.config = config
        self.dbConnector = dbConnector
        self.fileServer = fileServer
        self.options = options

        # verify options if possible
        opts_verified = self.verifyOptions(options)
        if opts_verified is not None and isinstance(opts_verified, dict):
            if 'valid' in opts_verified and not opts_verified['valid']:
                raise ValueError('Model options appear to be invalid.')
            if 'options' in opts_verified and isinstance(opts_verified['options'], dict):
                self.options = opts_verified['options']
        else:
            try:
                self.options = self.getDefaultOptions()
            except Exception:
                # not implemented or other error; leave it to the subclass
                pass

        # query how to treat unlabeled areas
        unlabeled = dbConnector.execute('''
            SELECT annotationtype, segmentation_ignore_unlabeled
            FROM aide_admin.project
            WHERE shortname = %s;
            ''', (project,), 1)
        try:
            annotation_type = unlabeled[0]['annotationtype']
            if annotation_type == 'segmentationMasks':
                self.ignore_unlabeled = unlabeled[0]['segmentation_ignore_unlabeled']
            else:
                self.ignore_unlabeled = True
        except Exception as e:
            self.ignore_unlabeled = True
            print(f'WARNING: project "{project}" has invalid specifications ' + \
                  'on how to treat unlabeled pixels')
            print(f'(error: "{str(e)}"). Ignoring unlabeled pixels by default.')


    @staticmethod
    def getDefaultOptions() -> Any:
        '''
            Returns default model options (as base for overriding or if no custom options have been
            provided.)
        '''
        raise NotImplementedError('not implemented for base class.')


    def getOptions(self) -> Any:
        '''
            Returns model options for current instance.
        '''
        return self.options


    @staticmethod
    def verifyOptions(options: Any) -> Union[dict,bool]:
        '''
            Placeholder to verify whether a given dict of options are valid or not. To be overridden
            by subclasses.
            
            Args:
                "options":  Any, object containing parameters for a model (e.g., a dict).
            
            Returns:
                - None if the subclass does not support the method (for compatibility reasons with
                  legacy implementations)
                - True/False if the given options are valid/invalid (minimal format)
                - A dict with the following entries:
                    - 'valid': bool, True/False if the given options are valid/invalid.
                    - 'warnings': list of strings containing warnings encountered during
                                  parsing (optional).
                    - 'errors': list of strings containing errors encountered during par-
                                sing (optional).
                    - 'options': dict of updated options that will be used instead of the
                                 provided ones. This can be used to e.g. auto-complete mis- sing
                                 parameters in the provided options, or auto-correct simple
                                 mistakes. If provided, these values will be used in the GUI in lieu
                                 of what the user specified (optional).
        '''
        return None


    def train(self,
              stateDict: bytes,
              data: dict,
              updateStateFun: callable) -> bytes:
        '''
            Training function. This function gets called by each individual AIWorkers
            when the model is supposed to be trained for another round.
            Args:
                "stateDict":        bytes, contains the model's current state
                "data":             dict, contains the image metadata to be trained on
                "updateStateFun":   callable, function handle for updating the progress to the
                                    AIController
            
            Returns:
                bytes, contains the model state after training
        '''
        raise NotImplementedError('not implemented for base class.')


    def average_model_states(self,
                             stateDicts: Iterable[bytes],
                             updateStateFun: callable) -> bytes:
        '''
            Averaging function. If AIDE is configured to distribute training to multiple
            AIWorkers, and if multiple AIWorkers are attached, this function will be called
            by exactly one AIWorker after the "train" function has finished.
            Args:
                "stateDicts":       list, contains N bytes objects containing model states as
                                    trained by the N AIWorkers attached
                "updateStateFun":   callable, function handle for updating the progress to the
                                    AIController

            Returns:
                bytes, contains the combined model states
        '''
        raise NotImplementedError('not implemented for base class.')


    # #TODO: this is commented out temporarily to not break compatibility with unoptimized models
    # def update_model(self, stateDict, data, updateStateFun):
    #     '''
    #         Updater function. Modifies the model to incorporate newly
    #         added label classes.
    #         Implementers are advised to employ advanced heuristics, such as weight
    #         combinations of a model's classification part.
    #         Note that it may be that the model is already adapted for all the label classes
    #         present in "data", in which case no modifications are required.
    #         Args:
    #             stateDict: a bytes object containing the latest model state
    #             data: a dict object containing the metadata of the images to
    #                   be used for subsequent processes (train or inference)
    #             updateStateFun: function handle for updating the progress to the
    #                             AIController

    #         Returns:
    #             stateDict: a bytes object containing the updated model states    
    #     '''
    #     raise NotImplementedError('not implemented for base class.')


    def inference(self,
                  stateDict: bytes,
                  data: dict,
                  updateStateFun: callable) -> dict:
        '''
            Inference function. This gets called everytime the model is supposed to be run on a set
            of images. The inference job might be distributed to multiple AIWorkers, but there is no
            need to worry about concurrency or race conditions, as each inference job is handled
            separately.
            Args:
                "stateDict":        bytes, contains the latest model state
                "data":             dict, contains the metadata of the images the model needs to
                                    predict
                "updateStateFun":   callable, function handle for updating the progress to the
                                    AIController

            Returns:
                dict, containing the image metadata and model predictions
        '''
        raise NotImplementedError('not implemented for base class.')
