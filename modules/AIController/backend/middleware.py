'''
    Middleware for AIController: handles requests and updates to and from the database.

    2019-24 Benjamin Kellenberger
'''

from typing import Tuple, List, Union, Iterable
from datetime import datetime
from uuid import UUID
import re
import json
from constants.annotationTypes import ANNOTATION_TYPES
from ai import PREDICTION_MODELS, ALCRITERION_MODELS
from modules.AIController.backend import celery_interface as aic_int
from modules.AIWorker.backend import celery_interface as aiw_int
from celery import current_app
from psycopg2 import sql

from modules.AIController.taskWorkflow.workflowDesigner import WorkflowDesigner
from modules.AIController.taskWorkflow.workflowTracker import WorkflowTracker
from modules.AIWorker.backend.fileserver import FileServer
from util import celeryWorkerCommons
from util.common import get_project_immutables
from util.helpers import array_split, parse_parameters, get_class_executable, get_library_available

from .messageProcessor import MessageProcessor
from .annotationWatchdog import Watchdog
from .sql_string_builder import SQLStringBuilder



class AIMiddleware():
    '''
        Interface for the AI model side of AIDE between the frontend, database, and AIWorker task
        orchestration.
    '''
    def __init__(self, config, dbConnector, taskCoordinator, passiveMode=False) -> None:
        self.config = config
        self.db_connector = dbConnector
        self.task_coordinator = taskCoordinator
        self.sql_builder = SQLStringBuilder(config)
        self.passive_mode = passiveMode
        self.script_pattern = re.compile(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script\.?>')
        self._init_available_ai_models()

        self.celery_app = current_app
        self.celery_app.set_current()
        self.celery_app.set_default()

        if not self.passive_mode:
            self.message_processor = MessageProcessor(self.celery_app)

            # one watchdog per project. Note: watchdog only created if users poll status (i.e., if
            # there's activity)
            self.watchdogs = {}
            self.workflow_designer = WorkflowDesigner(self.db_connector, self.celery_app)
            self.workflow_tracker = WorkflowTracker(self.db_connector, self.celery_app)
            self.message_processor.start()


    def __del__(self):
        if self.passive_mode:
            return
        self.message_processor.stop()
        for w in self.watchdogs.values():
            w.stop()


    def _check_prediction_model_details(self,
                                        model_key: str,
                                        model: dict,
                                        libs_available: dict) -> Tuple[dict, List[str]]:

        #TODO: 1. using regex to remove scripts is not failsafe; 2. ugly code...
        messages = []

        # remove script tags and validate annotation and prediction types specified
        if 'name' in model and isinstance(model['name'], str):
            model['name'] = re.sub(self.script_pattern, '(script removed)', model['name'])
        else:
            model['name'] = model_key
        if 'description' in model and isinstance(model['description'], str):
            model['description'] = re.sub(self.script_pattern,
                                            '(script removed)',
                                            model['description'])
        else:
            model['description'] = '(no description available)'
        if 'author' in model and isinstance(model['author'], str):
            model['author'] = re.sub(self.script_pattern,
                                        '(script removed)',
                                        model['author'])
        else:
            model['author'] = '(unknown)'

        # check required libraries
        for req in model.get('requires', []):
            if req not in libs_available:
                libs_available[req] = get_library_available(req)
            if not libs_available[req]:
                return None, [f'Required library "{req}" not installed.']

        # check annotationType and predictionType
        for id_str in ('annotation', 'prediction'):
            identifier = f'{id_str}Type'
            if model.get(identifier, None) is None or len(model.get(identifier, '')) == 0:
                return f'Missing or invalid "{identifier}".'
            if isinstance(model[identifier], str):
                model[identifier] = [model[identifier]]
            for idx, atype in enumerate(model[identifier]):
                if atype not in ANNOTATION_TYPES:
                    messages.append(f'{identifier} "{atype}" not understood.')
                    del model['predictionType'][idx]
            if len(model.get(identifier, '')) == 0:
                return None, [f'Missing or invalid "{identifier}".']

        # get default model options
        try:
            model_class = get_class_executable(model_key)
            default_options = model_class.getDefaultOptions()
            model['defaultOptions'] = default_options
        except Exception:
            # no default options available; append no key to signal that there's no options
            pass

        # all checks passed
        return model, messages


    def _check_ranker_model_details(self,
                                    ranker_key: str,
                                    ranker: dict) -> Tuple[dict, List[str]]:

        #TODO: same problems as with prediction models
        if 'name' in ranker and isinstance(ranker['name'], str):
            ranker['name'] = re.sub(self.script_pattern,
                                    '(script removed)',
                                    ranker['name'])
        else:
            ranker['name'] = ranker_key
        if 'author' in ranker and isinstance(ranker['author'], str):
            ranker['author'] = re.sub(self.script_pattern,
                                        '(script removed)',
                                        ranker['author'])
        else:
            ranker['author'] = '(unknown)'
        if 'description' in ranker and isinstance(ranker['description'], str):
            ranker['description'] = re.sub(self.script_pattern,
                                            '(script removed)',
                                            ranker['description'])
        else:
            ranker['description'] = '(no description available)'

        # check predictionType
        if ranker.get('predictionType', None) is None \
                or len(ranker.get('predictionType', '')) == 0:
            # no prediction type specified
            return None, ['No or invalid predictionType specified.']

        if isinstance(ranker['predictionType'], str):
            ranker['predictionType'] = [ranker['predictionType']]
        for idx, rtype in enumerate(ranker['predictionType']):
            if rtype not in ANNOTATION_TYPES:
                print(f'WARNING: prediction type "{rtype}" not understood and ignored.')
                del ranker['predictionType'][idx]
        if ranker['predictionType'] is None or len(ranker['predictionType']) == 0:
            return None, ['No valid prediction type specified']

        # default ranker options
        try:
            ranker_class = get_class_executable(ranker_key)
            default_options = ranker_class.getDefaultOptions()
            ranker['defaultOptions'] = default_options
        except Exception:
            # no default options available; append no key to signal that there's no options
            pass

        # all checks passed
        return ranker, []


    def _init_available_ai_models(self):
        # cache for installed libraries
        libs_available = {}

        models = {
            'prediction': PREDICTION_MODELS,
            'ranking': ALCRITERION_MODELS
        }

        # check prediction models
        models_unavailable = []     # [(model, reason)]
        for model_key, model in models['prediction'].items():
            model, messages = self._check_prediction_model_details(model_key,
                                                                   model,
                                                                   libs_available)

            if model is None:
                # pre-flight check failed
                models_unavailable.append((model_key, '; '.join(messages)))

            else:
                models['prediction'][model_key] = model

        if len(models_unavailable) > 0:
            print(f'WARNING: {len(models_unavailable)} model(s) are not available:')
            for mod, msg in models_unavailable:
                print(f'{mod}: {msg}')

        # check ranking models
        rankers_unavailable = []     # [(ranker, reason)]
        for ranker_key, ranker in models['ranking'].items():
            ranker, messages = self._check_ranker_model_details(ranker_key, ranker)

            if ranker is None:
                # pre-flight check failed
                rankers_unavailable.append((ranker_key, '; '.join(messages)))

            else:
                models['ranking'][ranker_key] = ranker
        if len(rankers_unavailable) > 0:
            print(f'WARNING: {len(rankers_unavailable)} ranker(s) are not available:')
            for mod, msg in rankers_unavailable:
                print(f'{mod}: {msg}')

        self.ai_models = models



    def _init_watchdog(self,
                       project: str,
                       nudge: bool=False,
                       recheck_autotrain_settings: bool=False) -> None:
        '''
            Launches a thread that periodically polls the database for new annotations. Once the
            required number of new annotations is reached, this thread will initiate the training
            process through the middleware. The thread will be terminated and destroyed; a new
            thread will only be re-created once the training process has finished.
        '''
        if self.passive_mode:
            return

        if project not in self.watchdogs:
            self.watchdogs[project] = Watchdog(project,
                                               self.config,
                                               self.db_connector,
                                               self)
            self.watchdogs[project].start()

        if recheck_autotrain_settings:
            # also nudges the watchdog
            self.watchdogs[project].recheckAutotrainSettings()

        elif nudge:
            self.watchdogs[project].nudge()


    def _get_num_available_workers(self) -> int:
        #TODO: message + queue if no worker available
        #TODO: limit to n tasks per worker
        i = self.celery_app.control.inspect()
        if i is not None:
            stats = i.stats()
            if stats is not None:
                return len(i.stats())
        return 1    #TODO


    def _get_project_settings(self, project: str) -> dict:
        query_str = sql.SQL('''SELECT numImages_autoTrain,
            minNumAnnoPerImage, maxNumImages_train,maxNumImages_inference
            FROM aide_admin.project WHERE shortname = %s;''')
        settings = self.db_connector.execute(query_str, (project,), 1)[0]
        return settings


    def get_ai_model_training_info(self, project: str) -> dict:
        '''
            Returns information required to determine whether AI models can be trained
            for a given project.
            This includes:
                - Whether an AI model library is configured for the project
                - Whether at least consumer for each AIController and AIWorker is
                  connected and available
            Returns a dict of this information accordingly.
        '''
        # pylint: disable=consider-using-dict-items,consider-iterating-dictionary
        # pylint: disable=singleton-comparison

        # check whether project has an AI model configured
        ai_model_library = self.db_connector.execute('''
            SELECT ai_model_library
            FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project,), 1)
        try:
            ai_model_library = ai_model_library[0]['ai_model_library']
        except Exception:
            ai_model_library = None

        # check if AIController worker and AIWorker are connected
        aic_w, aiw_w = {}, {}
        workers = celeryWorkerCommons.getCeleryWorkerDetails()
        for w_key in workers.keys():
            try:
                worker = workers[w_key]
                if 'AIController' in worker['modules'] and \
                    worker['modules']['AIController'] == True:
                    aic_w[w_key] = workers[w_key]
                if 'AIWorker' in worker['modules'] and \
                    worker['modules']['AIWorker'] == True:
                    aiw_w[w_key] = workers[w_key]
            except Exception:
                pass

        return {
            'ai_model_library': ai_model_library,
            'workers': {
                'AIController': aic_w,
                'AIWorker': aiw_w
            }
        }


    def get_ongoing_tasks(self, project: str) -> List[str]:
        '''
            Polls Celery via Watchdog and returns a list of IDs of tasks
            that are currently ongoing for the respective project.
        '''
        self._init_watchdog(project)
        return self.watchdogs[project].getOngoingTasks()


    def can_launch_task(self,
                        project: str,
                        auto_launched: bool) -> bool:
        '''
            Polls ongoing tasks for the project in question and retrieves the maximum number of
            tasks that are allowed to be executed concurrently (as per project settings). Returns
            True if one (more) task can be launched, and False otherwise. Only one auto-launched
            taks can be run at a time ("auto_launched" True). The number of user-launched tasks
            depends on the project settings.
        '''
        # query number of currently ongoing tasks
        tasks_ongoing = self.get_ongoing_tasks(project)
        if auto_launched and len(tasks_ongoing) > 0:
            # we only permit one auto-launched task at a time
            return False

        # query number of concurrent tasks allowed as per project settings
        upper_ceiling = self.config.get_property('AIController',
                                                 'max_num_concurrent_tasks',
                                                 dtype=int,
                                                 fallback=2)
        num_concurrent = self.db_connector.execute('''
            SELECT max_num_concurrent_tasks
            FROM aide_admin.project
            WHERE shortname = %s;
        ''', (project,), 1)
        try:
            num_concurrent = num_concurrent[0]['max_num_concurrent_tasks']
            if upper_ceiling > 0:
                num_concurrent = min(num_concurrent, upper_ceiling)
        except Exception:
            num_concurrent = upper_ceiling

        if num_concurrent <= 0:
            return True
        return len(tasks_ongoing) < num_concurrent


    def aide_internal_notify(self, message: str) -> None:
        '''
            Used for AIDE administrative communication between AIController
            and AIWorker(s), e.g. for setting up queues.
        '''
        if self.passive_mode:
            return
        #TODO: not required (yet)


    def get_training_images(self,
                            project: str,
                            minTimestamp: Union[datetime,str]='lastState',
                            includeGoldenQuestions: bool=True,
                            minNumAnnoPerImage: int=0,
                            maxNumImages: int=None,
                            maxNumWorkers: int=-1) -> List[UUID]:
        '''
            Queries the database for the latest images to be used for model training.
            Returns a list with image UUIDs accordingly, split into the number of
            available workers.
        '''
        # sanity checks
        if not (isinstance(minTimestamp, datetime) or \
            minTimestamp == 'lastState' or
            minTimestamp == -1 or \
            minTimestamp is None):
            raise ValueError(
                f'{minTimestamp} is not a recognized property for variable "minTimestamp"')

        # identify number of available workers
        if maxNumWorkers != 1:
            # only query the number of available workers if more than one is specified to save time
            num_workers = min(maxNumWorkers, self._get_num_available_workers())
        else:
            num_workers = maxNumWorkers

        # query image IDs
        query_vals = []

        if minTimestamp is None:
            timestamp_str = sql.SQL('')
        elif minTimestamp == 'lastState':
            timestamp_str = sql.SQL('''
            WHERE iu.last_checked > COALESCE(to_timestamp(0),
            (SELECT MAX(timecreated) FROM {id_cnnstate}))''').format(
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            )
        elif isinstance(minTimestamp, datetime):
            timestamp_str = sql.SQL('WHERE iu.last_checked > COALESCE(to_timestamp(0), %s)')
            query_vals.append(minTimestamp)
        elif isinstance(minTimestamp, int) or isinstance(minTimestamp, float):
            timestamp_str = sql.SQL('''
                WHERE iu.last_checked > COALESCE(to_timestamp(0), to_timestamp(%s))''')
            query_vals.append(minTimestamp)

        # golden questions
        if includeGoldenQuestions:
            gq_str = sql.SQL('')
        else:
            gq_str = sql.SQL('AND isGoldenQuestion != TRUE')

        if minNumAnnoPerImage > 0:
            query_vals.append(minNumAnnoPerImage)

        if maxNumImages is None or not isinstance(maxNumImages, int) or maxNumImages <= 0:
            limit_str = sql.SQL('')
        else:
            limit_str = sql.SQL('LIMIT %s')
            query_vals.append(maxNumImages)

        if minNumAnnoPerImage <= 0:
            query_str = sql.SQL('''
                SELECT newestAnno.image FROM (
                    SELECT image, last_checked FROM {id_iu} AS iu
                    JOIN (
                        SELECT id AS iid
                        FROM {id_img}
                        WHERE (corrupt IS NULL OR corrupt = FALSE)
                        {gqStr}
                    ) AS imgQ
                    ON iu.image = imgQ.iid
                    {timestampStr}
                    ORDER BY iu.last_checked ASC
                    {limitStr}
                ) AS newestAnno;
            ''').format(
                id_iu=sql.Identifier(project, 'image_user'),
                id_img=sql.Identifier(project, 'image'),
                gqStr=gq_str,
                timestampStr=timestamp_str,
                limitStr=limit_str)

        else:
            query_str = sql.SQL('''
                SELECT newestAnno.image FROM (
                    SELECT image, last_checked FROM {id_iu} AS iu
                    JOIN (
                        SELECT id AS iid
                        FROM {id_img}
                        WHERE corrupt IS NULL OR corrupt = FALSE
                    ) AS imgQ
                    ON iu.image = imgQ.iid
                    {timestampStr}
                    {conjunction} image IN (
                        SELECT image FROM (
                            SELECT image, COUNT(*) AS cnt
                            FROM {id_anno}
                            GROUP BY image
                            ) AS annoCount
                        WHERE annoCount.cnt >= %s
                    )
                    ORDER BY iu.last_checked ASC
                    {limitStr}
                ) AS newestAnno;
            ''').format(
                id_iu=sql.Identifier(project, 'image_user'),
                id_img=sql.Identifier(project, 'image'),
                id_anno=sql.Identifier(project, 'annotation'),
                timestampStr=timestamp_str,
                conjunction=(sql.SQL('WHERE') if minTimestamp is None else sql.SQL('AND')),
                limitStr=limit_str)

        image_ids = self.db_connector.execute(query_str, tuple(query_vals), 'all')
        image_ids = [i['image'] for i in image_ids]

        if maxNumWorkers > 1:
            # split for distribution across workers
            # (TODO: also specify subset size for multiple jobs; randomly draw if needed)
            image_ids = array_split(image_ids, max(1, len(image_ids) // num_workers))
        else:
            image_ids = [image_ids]

        return image_ids


    def get_inference_images(self,
                             project: str,
                             goldenQuestionsOnly: bool=False,
                             forceUnlabeled: bool=False,
                             maxNumImages: int=None,
                             maxNumWorkers: int=-1) -> List[UUID]:
        '''
            Queries the database for the latest images to be used for inference after model
            training. Returns a list with image UUIDs accordingly, split into the number of
            available workers.
        '''
        if maxNumImages is None or maxNumImages == -1:
            query_result = self.db_connector.execute('''
                SELECT maxNumImages_inference
                FROM aide_admin.project
                WHERE shortname = %s;''', (project,), 1)
            maxNumImages = query_result[0]['maxnumimages_inference']

        query_vals = (maxNumImages,)

        # load the IDs of the images that are being subjected to inference
        sql_str = self.sql_builder.get_inference_query_string(project,
                                                          forceUnlabeled,
                                                          goldenQuestionsOnly,
                                                          maxNumImages)
        image_ids = self.db_connector.execute(sql_str, query_vals, 'all')
        image_ids = [i['image'] for i in image_ids]

        # split for distribution across workers
        if maxNumWorkers != 1:
            # only query the number of available workers if more than one is specified to save time
            num_available = self._get_num_available_workers()
            if maxNumWorkers == -1:
                maxNumWorkers = num_available   #TODO: more than one process per worker?
            else:
                maxNumWorkers = min(maxNumWorkers, num_available)

        if maxNumWorkers > 1:
            image_ids = array_split(image_ids, max(1, len(image_ids) // maxNumWorkers))
        else:
            image_ids = [image_ids]
        return image_ids



    #TODO: deprecated; replace with workflow
    def start_train_and_inference(self, project, minTimestamp='lastState', minNumAnnoPerImage=0, maxNumImages_train=-1, 
                                    maxNumWorkers_train=1,
                                    forceUnlabeled_inference=True, maxNumImages_inference=-1, maxNumWorkers_inference=1,
                                    author=None):
        '''
            Submits a model training job, followed by inference.
            This is the default behavior for the automated model update, since the newly trained model should directly
            be used to infer new, potentially useful labels.
        '''
        # check if task launching is allowed
        if not self.can_launch_task(project,
                                    True if author is None else False):
            return {
                'status': 1,
                'message': f'The maximum allowed number of concurrent tasks has been reached for project "{project}". Please wait until running tasks are finished.'
            }

        #TODO: sanity checks
        workflow = {
            'project': project,
            'tasks': [
                {
                    'id': '0',
                    'type': 'train',
                    'kwargs': {
                        'min_timestamp': minTimestamp,
                        'min_anno_per_image': minNumAnnoPerImage,
                        'max_num_images': maxNumImages_train,
                        'max_num_workers': maxNumWorkers_train
                    }
                },
                {
                    'id': '1',
                    'type': 'inference',
                    'kwargs': {
                        'force_unlabeled': forceUnlabeled_inference,
                        'max_num_images': maxNumImages_inference,
                        'max_num_workers': maxNumWorkers_inference
                    }
                }
            ],
            'options': {}
        }
        process = self.workflow_designer.parse_workflow(project, workflow)

        # launch workflow
        task_id = self.workflow_tracker.launchWorkflow(project,
                                                       process,
                                                       workflow,
                                                       author)

        return {
            'status': 0,
            'task_id': task_id
        }


    def launch_task(self,
                    project: str,
                    workflow: Union[str,UUID,dict],
                    author=None) -> dict:
        '''
            Accepts a workflow as one of the following three variants:
            - ID (str or UUID): ID of a saved workflow in this project
            - 'default': uses the default workflow for this project
            - dict: an actual workflow as per specifications
            parses it and launches the job if valid.
            Returns the task ID accordingly.
        '''
        # check if task launching is allowed
        if not self.can_launch_task(project,
                                    True if author is None else False):
            return {
                'status': 1,
                'message': 'The maximum allowed number of concurrent tasks has been reached ' + \
                           f'for project "{project}". Please wait until running tasks are finished.'
            }

        if isinstance(workflow, str):
            if workflow.lower() == 'default':
                # load default workflow
                query_str = sql.SQL('''
                    SELECT workflow FROM {id_workflow}
                    WHERE id = (
                        SELECT default_workflow
                        FROM aide_admin.project
                        WHERE shortname = %s
                    );
                ''').format(
                    id_workflow=sql.Identifier(project, 'workflow')
                )
                result = self.db_connector.execute(query_str, (project,), 1)
                if result is None or len(result) == 0:
                    return {
                        'status': 2,
                        'message': f'Workflow with ID "{str(workflow)}" does not exist ' + \
                                   'in this project'
                    }
                workflow = result[0]['workflow']
            else:
                # try first to parse workflow
                try:
                    workflow = json.loads(workflow)
                except Exception:
                    # try to convert to UUID instead
                    try:
                        workflow = UUID(workflow)
                    except Exception:
                        return {
                            'status': 3,
                            'message': f'"{str(workflow)}" is not a valid workflow ID'
                        }

        if isinstance(workflow, UUID):
            # load workflow as per UUID
            query_str = sql.SQL('''
                    SELECT workflow FROM {id_workflow}
                    WHERE id = %s;
                ''').format(
                    id_workflow=sql.Identifier(project, 'workflow')
                )
            result = self.db_connector.execute(query_str, (workflow,), 1)
            if result is None or len(result) == 0:
                return {
                    'status': 2,
                    'message': f'Workflow with ID "{str(workflow)}" does not exist in this project'
                }
            workflow = result[0]['workflow']

        # try to parse workflow
        try:
            process = self.workflow_designer.parse_workflow(project,
                                                            workflow,
                                                            False)
        except Exception as e:
            return {
                'status': 4,
                'message': f'Workflow could not be parsed (message: "{str(e)}")'
            }

        task_id = self.workflow_tracker.launchWorkflow(project,
                                                       process,
                                                       workflow,
                                                       author)

        return {
            'status': 0,
            'task_id': task_id
        }


    def revoke_task(self,
                    project: str,
                    taskID: Union[UUID,str],
                    username: str) -> None:
        '''
            Revokes (aborts) a task with given task ID for a given project, if it exists. Also sets
            an entry in the database (and notes who aborted the task).
        '''
        self.workflow_tracker.revokeTask(username,
                                         project,
                                         taskID)


    def revoke_all_tasks(self,
                         project: str,
                         username: str) -> None:
        '''
            Revokes (aborts) all tasks for a given project.
            Also sets an entry in the database (and notes who aborted
            the task).
        '''
        #TODO: make more elegant
        task_ids = self.get_ongoing_tasks(project)
        for task_id in task_ids:
            self.revoke_task(project, task_id, username)


    def check_status(self,
                     project: str,
                     checkProject: bool,
                     checkTasks: bool,
                     checkWorkers: bool,
                     nudgeWatchdog: bool=False,
                     recheckAutotrainSettings: bool=False) -> dict:
        '''
            Queries the Celery worker results depending on the parameters specified. Returns their
            status accordingly if they exist.
        '''
        status = {}

        # watchdog
        self._init_watchdog(project, nudgeWatchdog, recheckAutotrainSettings)

        # project status
        if checkProject:
            status['project'] = {
                'ai_auto_training_enabled': self.watchdogs[project].getAImodelAutoTrainingEnabled(),
                'num_annotated': self.watchdogs[project].lastCount,
                'num_next_training': self.watchdogs[project].getThreshold()
            }

        # running tasks status
        if checkTasks:
            status['tasks'] = self.workflow_tracker.pollAllTaskStatuses(project)

        # get worker status (this is very expensive, as each worker needs to be pinged)
        if checkWorkers:
            status['workers'] = self.message_processor.poll_worker_status()

        return status


    def getAvailableAImodels(self, project: str=None) -> dict:
        if project is None:
            return {
                'models': self.ai_models
            }
        models = {
            'prediction': {},
            'ranking': self.ai_models['ranking']
        }

        # identify models that are compatible with project's annotation and prediction type
        proj_anno_type, proj_pred_type = get_project_immutables(project, self.db_connector)
        for key, model in self.ai_models['prediction'].items():
            if proj_anno_type in model['annotationType'] and \
                proj_pred_type in model['predictionType']:
                models['prediction'][key] = model

        return {
            'models': models
        }


    def verifyAImodelOptions(self,
                             project: str,
                             modelOptions: dict,
                             modelLibrary: str=None) -> dict:
        '''
            Receives a dict of model options, a model library ID (optional) and verifies whether the
            provided options are valid for the model or not. Uses the following strategies to this
            end:
                1. If the AI model implements the function "verifyOptions", and if that function
                   does not return None, it is being used.
            
                2. Else, this temporarily instanciates a new AI model with the given options and
                   checks whether any errors occur. Returns True if not, but appends a warning that
                   the options could not reliably be verified.
        '''
        # get AI model library if not specified
        if modelLibrary is None or modelLibrary not in self.ai_models['prediction']:
            model_lib = self.db_connector.execute('''
                SELECT ai_model_library
                FROM aide_admin.project
                WHERE shortname = %s;
            ''', (project,), 1)
            modelLibrary = model_lib[0]['ai_model_library']

        model_name = self.ai_models['prediction'][modelLibrary]['name']

        response = None

        model_class = get_class_executable(modelLibrary)
        if hasattr(model_class, 'verifyOptions'):
            response = model_class.verifyOptions(modelOptions)

        if response is None:
            # no verification implemented; alternative
            #TODO: can we always do that on the AIController?
            try:
                model_class(project=project,
                            config=self.config,
                            dbConnector=self.db_connector,
                            fileServer=FileServer(self.config).get_secure_instance(project),
                            options=modelOptions)
                response = {
                    'valid': True,
                    'warnings': [f'A {model_name} instance could be launched, ' + \
                                 'but the settings could not be verified.']
                }
            except Exception as exc:
                # model could not be instantiated; append error
                response = {
                    'valid': False,
                    'errors': [ str(exc) ]
                }

        return response



    def updateAImodelSettings(self,
                              project: str,
                              settings: dict) -> dict:
        '''
            Updates the project's AI model settings. Verifies whether the specified AI and ranking
            model libraries exist on this setup of AIDE. Raises an exception otherwise.

            Also tries to verify any model options provided with the model's built-in function (if
            present and implemented). Returns warnings, errors, etc. about that.
        '''
        # AI libraries installed in AIDE
        models_available = self.getAvailableAImodels()['models']

        # project immutables
        anno_type, pred_type = get_project_immutables(project, self.db_connector)

        # cross-check submitted tokens
        field_names = [
            ('ai_model_enabled', bool),
            ('ai_model_library', str),
            ('ai_alcriterion_library', str),
            ('numimages_autotrain', int),           #TODO: replace this and next four entries with default workflow
            ('minnumannoperimage', int),
            ('maxnumimages_train', int),
            ('maxnumimages_inference', int),
            ('inference_chunk_size', int),
            ('max_num_concurrent_tasks', int),
            ('segmentation_ignore_unlabeled', bool)
        ]
        settings_new, settings_keys_new = parse_parameters(settings,
                                                           field_names,
                                                           absent_ok=True,
                                                           escape=True,
                                                           none_ok=True)

        # verify settings
        add_background_class = False
        force_disable_ai_model = False
        for idx, key in enumerate(settings_keys_new):
            if key == 'ai_model_library':
                model_lib = settings_new[idx]
                if model_lib is None or len(model_lib.strip()) == 0:
                    # no model library specified; disable AI model
                    force_disable_ai_model = True
                else:
                    if not model_lib in models_available['prediction']:
                        raise Exception(f'Model library "{model_lib}" is not installed ' + \
                                            'in this instance of AIDE.')
                    model_selected = models_available['prediction'][model_lib]
                    anno_types_valid = ([model_selected['annotationType']] \
                                         if isinstance(model_selected['annotationType'], str) \
                                            else model_selected['annotationType'])
                    pred_types_valid = ([model_selected['predictionType']] \
                                         if isinstance(model_selected['predictionType'], str) \
                                            else model_selected['predictionType'])
                    if not anno_type in anno_types_valid:
                        raise Exception(f'Model "{model_lib}" does not support ' + \
                                            f'annotations of type "{anno_type}".')
                    if not pred_type in pred_types_valid:
                        raise Exception(f'Model "{model_lib}" does not support ' + \
                                            f'predictions of type "{pred_type}".')

            elif key == 'ai_model_settings':
                # model settings are verified separately
                continue

            elif key == 'ai_alcriterion_library':
                model_lib = settings_new[idx]
                if model_lib is None or len(model_lib.strip()) == 0:
                    # no AL criterion library specified; disable AI model
                    force_disable_ai_model = True
                else:
                    if not model_lib in models_available['ranking']:
                        raise Exception(f'Ranking library "{model_lib}" is not installed ' + \
                                            'in this instance of AIDE.')

            elif key == 'ai_alcriterion_settings':
                # verify model parameters
                #TODO: outsource as well?
                pass

            elif key == 'segmentation_ignore_unlabeled':
                # only check if annotation type is segmentation mask
                if anno_type == 'segmentationMasks' and settings_new[idx] is False:
                    # unlabeled areas are to be treated as "background": add class if not exists
                    add_background_class = True

        if force_disable_ai_model:
            # switch flag
            flag_found = False
            for idx, key in enumerate(settings_keys_new):
                if key == 'ai_model_enabled':
                    settings_new[idx] = False
                    flag_found = True
                    break
            if not flag_found:
                settings_new.append(False)
                settings_keys_new.append('ai_model_enabled')

        # all checks passed; update database
        settings_new.append(project)
        query_str = sql.SQL('''UPDATE aide_admin.project
            SET
            {}
            WHERE shortname = %s;
            '''
        ).format(
            sql.SQL(',').join([sql.SQL(f'{item} = %s') for item in settings_keys_new])
        )
        self.db_connector.execute(query_str, tuple(settings_new), None)

        if add_background_class:
            label_classes = self.db_connector.execute(sql.SQL('''
                    SELECT * FROM {id_lc}
                ''').format(id_lc=sql.Identifier(project, 'labelclass')),
                None, 'all')
            has_background = False
            for lc in label_classes:
                if lc['idx'] == 0:
                    has_background = True
                    break
            if not has_background:
                # find unique name
                lc_names = set(lc['name'] for lc in label_classes)
                bg_name = 'background'
                counter = 0
                while bg_name in lc_names:
                    bg_name = f'background ({counter})'
                    counter += 1
                self.db_connector.execute(sql.SQL('''
                    INSERT INTO {id_lc} (name, idx, hidden)
                    VALUES (%s, 0, true)
                ''').format(id_lc=sql.Identifier(project, 'labelclass')),
                (bg_name,), None)

        response = {'status': 0}

        # check for and verify AI model settings
        if 'ai_model_settings' in settings:
            ai_model_opts_status = self.saveProjectModelSettings(project,
                                                                 settings['ai_model_settings'])
            response['ai_model_settings_status'] = ai_model_opts_status

        return response


    def listModelStates(self,
                        project: str,
                        latestOnly: bool=False) -> List[dict]:
        '''
            Retrieves model states metadata for given project.

            Args:
                - project:      str, project shortname
                - latestOnly:   bool, only returns most recent model state if True (else all)

            Returns:
                - list of dicts, metadata for all model states in order of time created
        '''
        model_libraries = self.getAvailableAImodels()

        # get meta data about models shared through model marketplace
        result = self.db_connector.execute('''
            SELECT id, origin_uuid,
            author, anonymous, public,
            shared, tags, name, description,
            citation_info, license
            FROM aide_admin.modelMarketplace
            --WHERE origin_project = %s OR origin_project IS NULL;          #TODO: check effects of commenting this line
        ''', (project,), 'all')
        if result is not None and len(result):
            model_marketplace_meta = []
            for res in result:
                values = {}
                for key in res.keys():
                    if isinstance(res[key], UUID):
                        values[key] = str(res[key])
                    else:
                        values[key] = res[key]
                model_marketplace_meta.append(values)
        else:
            model_marketplace_meta = []

        # get project-specific model states
        if latestOnly:
            latest_only_str = sql.SQL('''
                WHERE timeCreated = (
                    SELECT MAX(timeCreated)
                    FROM {}
                )
            ''').format(sql.Identifier(project, 'cnnstate'))
        else:
            latest_only_str = sql.SQL('')

        query_str = sql.SQL('''
            SELECT id, marketplace_origin_id, imported_from_marketplace,
                EXTRACT(epoch FROM timeCreated) AS time_created,
                model_library, alCriterion_library, num_pred, labelclass_autoupdate
            FROM (
                SELECT * FROM {id_cnnstate}
                {latestOnlyStr}
            ) AS cnnstate
            LEFT OUTER JOIN (
                SELECT cnnstate, COUNT(cnnstate) AS num_pred
                FROM {id_pred}
                GROUP BY cnnstate
            ) AS pred
            ON cnnstate.id = pred.cnnstate
            ORDER BY time_created DESC;
        ''').format(
            id_cnnstate=sql.Identifier(project, 'cnnstate'),
            id_pred=sql.Identifier(project, 'prediction'),
            latestOnlyStr=latest_only_str
        )
        result = self.db_connector.execute(query_str, None, 'all')
        response = []
        if result is not None and len(result):
            for res in result:
                model_id = str(res['id'])
                try:
                    model_library = model_libraries['models']['prediction'][res['model_library']]
                except Exception:
                    model_library = {
                        'name': '(not found)'
                    }
                model_library['id'] = res['model_library']
                try:
                    rankers = model_libraries['models']['ranking']
                    al_criterion_library = rankers[res['alcriterion_library']]
                except Exception:
                    al_criterion_library = {
                        'name': '(not found)'
                    }
                al_criterion_library['id'] = res['alcriterion_library']

                # Model Marketplace information
                marketplace_info = {}
                for mm in model_marketplace_meta:
                    if model_id == mm['origin_uuid']:
                        # priority: model has been shared to Marketplace
                        marketplace_info = mm
                        break
                    if str(res['marketplace_origin_id']) == mm['id'] \
                        and res['imported_from_marketplace']:
                        # model state comes from Marketplace
                        marketplace_info = mm

                # elif r['marketplace_origin_id'] in modelMarketplaceMeta:
                #     # model state comes from Marketplace
                #     marketplaceInfo = modelMarketplaceMeta[r['marketplace_origin_id']]
                # else:
                #     # model has no relationship to Marketplace
                #     marketplaceInfo = {}

                response.append({
                    'id': model_id,
                    'time_created': res['time_created'],
                    'model_library': model_library,
                    'al_criterion_library': al_criterion_library,
                    'num_pred': (res['num_pred'] if res['num_pred'] is not None else 0),
                    'labelclass_autoupdate': res['labelclass_autoupdate'],
                    'imported_from_marketplace': res['imported_from_marketplace'],
                    'marketplace_info': marketplace_info
                })
        return response


    def deleteModelStates(self,
                          project: str,
                          username: str,
                          modelStateIDs: Union[str, List[str]]) -> UUID:
        '''
            Receives a list of model state IDs (either str or UUID) and launches a task to delete
            them from the database. Unlike training and inference tasks, this one is routed through
            the default taskCoordinator.
        '''
        # verify IDs
        if not isinstance(modelStateIDs, Iterable):
            modelStateIDs = [modelStateIDs]
        modelStateIDs = [str(m) for m in modelStateIDs]
        process = aic_int.delete_model_states.s(project, modelStateIDs)
        task_id = self.task_coordinator.submit_task(project,
                                                   username,
                                                   process,
                                                   'AIController')
        return task_id


    def duplicateModelState(self,
                            project: str,
                            username: str,
                            modelStateID: Union[UUID,str],
                            skipIfLatest: bool=True) -> UUID:
        '''
            Receives a model state ID and creates a copy of it in this project. This copy receives
            the current date, which makes it the most recent model state. If "skipIfLatest" is True
            and the model state with "modelStateID" is already the most recent state, no duplication
            is being performed.
        '''
        if not isinstance(modelStateID, UUID):
            modelStateID = UUID(modelStateID)

        process = aic_int.duplicate_model_state.s(project, modelStateID)
        task_id = self.task_coordinator.submit_task(project,
                                                   username,
                                                   process,
                                                   'AIController')
        return task_id


    def getModelTrainingStatistics(self,
                                   project: str,
                                   username: str,
                                   modelStateIDs: Union[List[str],str]=None) -> UUID:
        '''
            Launches a task to assemble model-provided statistics
            into uniform series.
            Unlike training and inference tasks, this one is routed
            through the default taskCoordinator.
        '''
        # verify IDs
        if modelStateIDs is not None:
            try:
                if not isinstance(modelStateIDs, Iterable):
                    modelStateIDs = [modelStateIDs]
                modelStateIDs = [str(m) for m in modelStateIDs]
            except Exception:
                modelStateIDs = None

        process = aic_int.get_model_training_statistics.s(project, modelStateIDs)
        task_id = self.task_coordinator.submit_task(project,
                                                   username,
                                                   process,
                                                   'AIController')
        return task_id


    def getProjectModelSettings(self, project: str) -> dict:
        '''
            Returns the AI and AL model properties for the given project, as stored in the database.
        '''
        result = self.db_connector.execute('''SELECT ai_model_enabled,
                ai_model_library, ai_model_settings,
                ai_alcriterion_library, ai_alcriterion_settings,
                numImages_autoTrain, minNumAnnoPerImage,
                maxNumImages_train, maxNumImages_inference
                FROM aide_admin.project
                WHERE shortname = %s;
            ''',
            (project,),
            1)
        return result[0]


    def saveProjectModelSettings(self,
                                 project: str,
                                 settings: dict) -> dict:
        '''
            Saves AI model settings for a given project.

            Args:

                - "project":    str, project shortname
                - "settings":   dict, AI model settings to save

            Returns:
                - dict, verification status of provided settings, including potential warnings and
                  errors
        '''
        # verify settings first
        options_verification = self.verifyAImodelOptions(project, settings)
        if options_verification['valid']:
            # save
            if isinstance(settings, dict):
                settings = json.dumps(settings)
            self.db_connector.execute('''
                UPDATE aide_admin.project
                SET ai_model_settings = %s
                WHERE shortname = %s;
            ''', (settings, project), None)
        else:
            options_verification['errors'].append(
                'Model options have not passed verification and where therefore not saved.')
        return options_verification


    def getSavedWorkflows(self, project: str) -> dict:
        '''
            Returns all saved AI workflows for given project.

            Args:
                - "project":    str, project shortname
            
            Returns:
                - dict, workflow metadata with workflow id as key
        '''
        query_str = sql.SQL('''
            SELECT *
            FROM {id_workflow} AS wf
            LEFT OUTER JOIN (
                SELECT default_workflow
                FROM aide_admin.project
                WHERE shortname = %s
            ) AS defwf
            ON wf.id = defwf.default_workflow;
        ''').format(id_workflow=sql.Identifier(project, 'workflow'))
        result = self.db_connector.execute(query_str, (project,), 'all')
        response = {}
        for r in result:
            response[str(r['id'])] = {
                'name': r['name'],
                'workflow': r['workflow'],
                'author': r['username'],
                'time_created': r['timecreated'].timestamp(),
                'time_modified': r['timemodified'].timestamp(),
                'default_workflow': (True if r['default_workflow'] is not None else False)
            }
        return response


    def saveWorkflow(self,
                     project: str,
                     username: str,
                     workflow: dict,
                     workflowID: Union[UUID,str],
                     workflowName: str,
                     setDefault: bool=False) -> dict:
        '''
            Receives a workflow definition (Python dict) to be saved in the database for a given
            project under a provided user name. The workflow definition is first parsed by the
            WorkflowDesigner and checked for validity. If it passes, it is stored in the database.
            If "setDefault" is True, the current workflow is set as the standard workflow, to be
            used for automated model training. Workflows can also be updated if an ID is specified.
        '''
        try:
            # check validity of workflow
            valid = self.workflow_designer.parse_workflow(project,
                                                          workflow,
                                                          True)
            if not valid:
                raise Exception('Workflow is not valid.')   #TODO: detailed error message
            workflow = json.dumps(workflow)

            # check if workflow already exists
            query_args = [workflowName]
            if workflowID is not None:
                query_args.append(UUID(workflowID))
                id_str = sql.SQL(' OR id = %s')
            else:
                id_str = sql.SQL('')

            existing_workflow = self.db_connector.execute(
                sql.SQL('''
                    SELECT id
                    FROM {id_workflow}
                    WHERE name = %s {idStr};
                ''').format(
                    id_workflow=sql.Identifier(project, 'workflow'),
                    idStr=id_str),
                tuple(query_args),
                1
            )
            if existing_workflow is not None and len(existing_workflow) > 0:
                existing_workflow = existing_workflow[0]['id']
            else:
                existing_workflow = None

            # commit to database
            if existing_workflow is not None:
                result = self.db_connector.execute(
                    sql.SQL('''
                        UPDATE {id_workflow}
                        SET name = %s, workflow = %s
                        WHERE id = %s
                        RETURNING id;
                    ''').format(id_workflow=sql.Identifier(project, 'workflow')),
                    (workflowName, workflow, existing_workflow),
                    1
                )
            else:
                result = self.db_connector.execute(
                    sql.SQL('''
                        INSERT INTO {id_workflow} (name, workflow, username)
                        VALUES (%s, %s, %s)
                        RETURNING id;
                    ''').format(id_workflow=sql.Identifier(project, 'workflow')),
                    (workflowName, workflow, username),
                    1
                )
            wid = result[0]['id']

            # set as default if requested
            if setDefault:
                self.db_connector.execute(
                    '''
                        UPDATE aide_admin.project
                        SET default_workflow = %s
                        WHERE shortname = %s;
                    ''',
                    (wid, project,),
                    None
                )
            return {
                'status': 0,
                'id': str(wid)
            }
        except Exception as e:
            return {
                'status': 1,
                'message': str(e)
            }


    def setDefaultWorkflow(self,
                           project: str,
                           workflowID: Union[UUID,str]) -> dict:
        '''
            Receives a str (workflow ID) and sets the associated workflow as default, if it exists
            for a given project.
        '''
        if isinstance(workflowID, str):
            workflowID = UUID(workflowID)
        if workflowID is not None and not isinstance(workflowID, UUID):
            return {
                'status': 2,
                'message': f'Provided argument "{str(workflowID)}" is not a valid workflow ID'
            }
        query_str = sql.SQL('''
            UPDATE aide_admin.project
            SET default_workflow = (
                SELECT id FROM {id_workflow}
                WHERE id = %s
                LIMIT 1
            )
            WHERE shortname = %s
            RETURNING default_workflow;
        ''').format(
            id_workflow=sql.Identifier(project, 'workflow')
        )
        result = self.db_connector.execute(query_str, (workflowID, project,), 1)
        if result is None \
            or len(result) == 0 \
                or str(result[0]['default_workflow']) != str(workflowID):
            return {
                'status': 3,
                'message': f'Provided argument "{str(workflowID)}" is not a valid workflow ID'
            }
        return {
            'status': 0
        }


    def deleteWorkflow(self,
                       project: str,
                       username: str,
                       workflowID: Union[UUID,str,Iterable[Union[UUID,str]]]) -> dict:
        '''
            Receives a str or iterable of str variables under "workflowID" and finds and deletes
            them for a given project. Only deletes them if they were created by the user provided in
            "username", or if they are deleted by a super user.
        '''
        if isinstance(workflowID, str):
            workflowID = [UUID(workflowID)]
        elif not isinstance(workflowID, Iterable):
            workflowID = [workflowID]
        for widx, wid in enumerate(workflowID):
            if not isinstance(wid, UUID):
                workflowID[widx] = UUID(wid)

        workflowID = tuple((w,) for w in workflowID)

        query_str = sql.SQL('''
            DELETE FROM {id_workflow}
            WHERE (
                username = %s
                OR username IN (
                    SELECT name
                    FROM aide_admin.user
                    WHERE isSuperUser = true
                )
            )
            AND id IN %s
            RETURNING id;
        ''').format(
            id_workflow=sql.Identifier(project, 'workflow')
        )
        result = self.db_connector.execute(query_str, (username, workflowID,), 'all')
        result = [str(r['id']) for r in result]

        return {
            'status': 0,
            'workflowIDs': result
        }


    def deleteWorkflow_history(self,
                               project: str,
                               workflowID: Union[UUID,str,Iterable[Union[UUID,str]]],
                               revokeIfRunning: bool=False) -> dict:
        '''
            Receives a str or iterable of str variables under "workflowID" and finds and deletes
            them for a given project. Only deletes them if they were created by the user provided in
            "username", or if they are deleted by a super user. If "revokeIfRunning" is True, any
            workflow with ID given that is still running is aborted first.
        '''
        if workflowID == 'all':
            # get all workflow IDs from DB
            workflowID = self.db_connector.execute(
                sql.SQL('''
                    SELECT id FROM {id_workflowhistory};
                ''').format(
                    id_workflowhistory=sql.Identifier(project, 'workflowhistory')
                ),
                None,
                'all'
            )
            if workflowID is None or len(workflowID) == 0:
                return {
                    'status': 0,
                    'workflowIDs': None
                }
            workflowID = [w['id'] for w in workflowID]

        elif isinstance(workflowID, str):
            workflowID = [UUID(workflowID)]
        elif not isinstance(workflowID, Iterable):
            workflowID = [workflowID]
        for widx, wid in enumerate(workflowID):
            if not isinstance(wid, UUID):
                workflowID[widx] = UUID(wid)

        if len(workflowID) == 0:
            return {
                'status': 0,
                'workflowIDs': None
            }

        if revokeIfRunning:
            WorkflowTracker._revoke_task([{'id': w} for w in workflowID])
        else:
            # skip ongoing tasks
            task_ids_ongoing = self.get_ongoing_tasks(project)
            for tidx, task_id in enumerate(task_ids_ongoing):
                if not isinstance(task_id, UUID):
                    task_ids_ongoing[tidx] = UUID(task_id)
            workflowID = list(set(workflowID).difference(set(task_ids_ongoing)))

        query_str = sql.SQL('''
            DELETE FROM {id_workflowhistory}
            WHERE id IN %s
            RETURNING id;
        ''').format(
            id_workflowhistory=sql.Identifier(project, 'workflowhistory')
        )
        result = self.db_connector.execute(query_str, (tuple(workflowID),), 'all')
        result = [str(r['id']) for r in result]

        return {
            'status': 0,
            'workflowIDs': result
        }


    def getLabelclassAutoadaptInfo(self,
                                   project: str,
                                   modelID: Union[UUID,str]=None) -> dict:
        '''
            Retrieves information on whether the model in a project has been configured to
            automatically incorporate new classes by parameter expansion, as well as whether it is
            actually possible to disable the property (once enabled, it cannot be undone for any
            current model state). Also checks and returns whether AI model implementation actually
            supports label class adaptation.
        '''

        if modelID is not None:
            if not isinstance(modelID, UUID):
                modelID = UUID(modelID)
            model_id_str = sql.SQL('WHERE id = %s')
            query_args = (modelID, project)
        else:
            model_id_str = sql.SQL('''
                WHERE timeCreated = (
                    SELECT MAX(timeCreated)
                    FROM {id_cnnstate}
                )
            ''').format(
                id_cnnstate=sql.Identifier(project, 'cnnstate')
            )
            query_args = (project,)

        query_str = sql.SQL('''
            SELECT 'model' AS row_type, labelclass_autoupdate, NULL AS ai_model_library
            FROM {id_cnnstate}
            {modelIDstr}
            UNION ALL
            SELECT 'project' AS row_type, labelclass_autoupdate, ai_model_library
            FROM "aide_admin".project
            WHERE shortname = %s;
        ''').format(
            id_cnnstate=sql.Identifier(project, 'cnnstate'),
            modelIDstr=model_id_str
        )
        result = self.db_connector.execute(query_str, query_args, 2)
        response = {
            'model': False,
            'model_lib': False,
            'project': False
        }
        for row in result:
            if row['ai_model_library'] is not None:
                # check if AI model library supports adaptation
                model_lib = row['ai_model_library']
                pred_model = self.ai_models['prediction'][model_lib]
                response['model_lib'] = pred_model['canAddLabelclasses']
            response[row['row_type']] = row['labelclass_autoupdate']

        return response


    def setLabelclassAutoadaptEnabled(self,
                                      project: str,
                                      enabled: bool) -> dict:
        '''
            Sets automatic labelclass adaptation to the specified value. This is only allowed if the
            current model state does not already have automatic labelclass adaptation enabled.
        '''
        if not enabled:
            # user requests to disable adaptation; check if possible
            enabled_model = self.getLabelclassAutoadaptInfo(project, None)
            if enabled_model['model']:
                # current model has adaptation enabled; abort
                return False

        result = self.db_connector.execute('''
            UPDATE "aide_admin".project
            SET labelclass_autoupdate = %s
            WHERE shortname = %s
            RETURNING labelclass_autoupdate;
        ''', (enabled, project), 1)

        return result[0]['labelclass_autoupdate']
