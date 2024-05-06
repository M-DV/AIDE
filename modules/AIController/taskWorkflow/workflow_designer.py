'''
    The workflow designer allows users to create and launch
    sophisticated chains of (distributed) training and inference,
    including customization of all available hyperparameters.

    To this end, workflows can be submitted as a Python dict
    object as follows:

        {
            "project": "project_shortname",
            "tasks": [
                {
                    "id": "node0",
                    "type": "train"
                },
                {
                    "id": "node1",
                    "type": "train",
                    "kwargs": {
                        "includeGoldenQuestions": False,
                        "minNumAnnotations": 1
                    }
                },
                "inference"
            ],
            "repeaters": {
                "repeater0": {
                    "id": "repeater0",
                    "type": "repeater",
                    "start_node": "node1",
                    "end_node": "node0",
                    "kwargs": {
                        "num_repetitions": 2
                    }
                }
            },
            "options": {
                "max_num_workers": 3
            }
        }
    
    Note the following:
        - The sequence of tasks to be executed is the order of the
          entries in the list under "tasks."
        - Tasks may be specified as simple names ("train", "inference").
          In this case, parameters will be taken from the global "options"
          provided, or else from the default options if missing (see file
          "defaultOptions.py").
        - Tasks can also be specified as sub-dicts with name and parameters
          under "kwargs." Those have priority over global options, but as
          above, global options or else defaults will be used to auto-complete
          missing options, if necessary.
        - Special repeater entries specify a sequence of nodes via "start_node"
          and "end_node" that is to be looped for "num_repetitions" times. For
          repeater entries to work, the start and end nodes of the loop must be
          specified as a dict and contain an id.
        - Repeater nodes may also have the same id for "start_node" and "end_node,"
          which results in a single task being executed "num_repetitions" times.

    2020-24 Benjamin Kellenberger
'''

from types import ModuleType
from typing import Union
import json
from psycopg2 import sql
import celery

from modules.AIController.backend import celery_interface as aic_int
from modules.AIWorker.backend import celery_interface as aiw_int
from util.helpers import get_class_executable
from .defaultOptions import DEFAULT_WORKFLOW_ARGS



def expand_from_name(index: int,
                     project: str,
                     task_name: str,
                     workflow: dict,
                     project_defaults: dict) -> dict:
    '''
        Creates and returns a task description dict from a task name. Receives the workflow
        description for global arguments, but also resorts to default arguments for auto-completion,
        if necessary.
    '''
    if not task_name in DEFAULT_WORKFLOW_ARGS:
        raise ValueError(f'Unknown task name provided ("{task_name}") for task at index {index}.')

    # default arguments
    task_args = DEFAULT_WORKFLOW_ARGS[task_name]

    # replace with global options if available
    for key in task_args.keys():
        if key in workflow['options']:
            task_args[key] = workflow['options'][key]    #TODO: sanity checks (type, values, etc.)
        elif key in project_defaults[task_name]:
            task_args[key] = project_defaults[task_name][key]

    return {
        'type': task_name,
        'project': project,
        'kwargs': task_args
    }



def verify_model_options(model_class: ModuleType, options: dict) -> bool:
    '''
        Receives an AI model class and a dict of options and calls the class' verification routine
        to check whether options are valid or not. Returns True even if an exception occurs as the
        problem then lies with the model, not the options.
    '''
    if model_class is None or not hasattr(model_class, 'verifyOptions'):
        return True
    try:
        response = model_class.verifyOptions(options)
        if isinstance(response, bool):
            return response
        if isinstance(response, dict) and 'valid' in response:
            return bool(response['valid'])
        return True
    except Exception:
        return True



def get_training_signature(project: str,
                           task_args: dict,
                           is_first_node: bool=False,
                           model_class: ModuleType=None) -> celery.chain:
    '''
        Creates a Celery.chain for model training.
    '''
    epoch = task_args['epoch']
    num_epochs = task_args['numEpochs']
    num_workers = task_args['max_num_workers']
    ai_model_settings = task_args.get('ai_model_settings', None)
    if not verify_model_options(model_class, ai_model_settings):
        ai_model_settings = None

    # initialize list for Celery chain tasks
    task_list = []

    if not 'data' in task_args:
        # no list of images provided; prepend getting training images
        min_num_anno_per_image = task_args['min_anno_per_image']
        if isinstance(min_num_anno_per_image, str):
            if len(min_num_anno_per_image) > 0:
                min_num_anno_per_image = int(min_num_anno_per_image)
            else:
                min_num_anno_per_image = None

        max_num_images = task_args['max_num_images']
        if isinstance(max_num_images, str):
            if len(max_num_images) > 0:
                max_num_images = int(max_num_images)
            else:
                max_num_images = None

        img_task_kwargs = {'project': project,
                           'epoch': epoch,
                           'numEpochs': num_epochs,
                           'minTimestamp': task_args['min_timestamp'],
                           'includeGoldenQuestions': task_args['include_golden_questions'],
                           'minNumAnnoPerImage': min_num_anno_per_image,
                           'maxNumImages': max_num_images,
                           'numWorkers': num_workers}
        if is_first_node:
            # first node: prepend update model task and fill blank
            img_task_kwargs['blank'] = None
            update_model_kwargs = {'project': project,
                                   'numEpochs': num_epochs,
                                   'blank': None}
            task_list.append(
                celery.group([
                    aic_int.get_training_images.s(**img_task_kwargs).set(queue='AIController'),
                    aiw_int.call_update_model.s(**update_model_kwargs).set(queue='AIWorker')
                ])
            )
        else:
            task_list.append(
                aic_int.get_training_images.s(**img_task_kwargs).set(queue='AIController')
            )

        train_args = {
            'epoch': epoch,
            'numEpochs': num_epochs,
            'project': project,
            'aiModelSettings': ai_model_settings
        }

    else:
        train_args = {
            'data': task_args['data'],
            'epoch': epoch,
            'numEpochs': num_epochs,
            'project': project,
            'aiModelSettings': ai_model_settings
        }

    if num_workers > 1:
        # distribute training; also need to call model state averaging
        train_tasks = []
        for w in range(num_workers):
            train_kwargs = {**train_args, **{'index': w}}
            train_tasks.append(aiw_int.call_train.s(**train_kwargs).set(queue='AIWorker'))
        task_list.append(
            celery.chord(
                train_tasks,
                aiw_int.call_average_model_states.si(**{'epoch': epoch,
                            'numEpochs': num_epochs,
                            'project': project,
                            'aiModelSettings': ai_model_settings}).set(queue='AIWorker')
            )
        )
    else:
        # training on single worker
        train_kwargs = {**train_args, **{'index': 0}}
        task_list.append(
            aiw_int.call_train.s(**train_kwargs).set(queue='AIWorker')
        )
    return celery.chain(task_list)



def get_inference_signature(project: str,
                            task_args: dict,
                            is_first_node: bool=False,
                            model_class: ModuleType=None) -> celery.chain:
    '''
        Creates a Celery.chain for inference.
    '''
    epoch = task_args['epoch']
    num_epochs = task_args['numEpochs']
    num_workers = task_args['max_num_workers']
    max_num_images = task_args['max_num_images']
    if isinstance(max_num_images, str):
        if len(max_num_images):
            max_num_images = int(max_num_images)
        else:
            max_num_images = None
    ai_model_settings = task_args.get('ai_model_settings', None)
    if not verify_model_options(model_class, ai_model_settings):
        ai_model_settings = None
    al_criterion_settings = task_args.get('alcriterion_settings', None)

    # initialize list for Celery chain tasks
    task_list = []

    if not 'data' in task_args:
        # no list of images provided; prepend getting inference images
        img_task_kwargs = {'project': project,
                           'epoch': epoch,
                           'numEpochs': num_epochs,
                           'goldenQuestionsOnly': task_args['golden_questions_only'],
                           'maxNumImages': max_num_images,
                           'numWorkers': num_workers}
        if is_first_node:
            # first task to be executed; prepend model update and fill blanks
            img_task_kwargs['blank'] = None
            update_model_kwargs = {'project': project,
                                'numEpochs': num_epochs,
                                'blank': None}
            task_list.append(
                celery.group([
                    aic_int.get_inference_images.s(**img_task_kwargs).set(queue='AIController'),
                    aiw_int.call_update_model.s(**update_model_kwargs).set(queue='AIWorker')
                ])
            )
        else:
            task_list.append(
                aic_int.get_inference_images.s(**img_task_kwargs).set(queue='AIController')
            )

        inference_args = {
            'epoch': epoch,
            'numEpochs': num_epochs,
            'project': project,
            'aiModelSettings': ai_model_settings,
            'alCriterionSettings': al_criterion_settings
        }

    else:
        inference_args = {
            'data': task_args['data'],
            'epoch': epoch,
            'numEpochs': num_epochs,
            'project': project,
            'aiModelSettings': ai_model_settings,
            'alCriterionSettings': al_criterion_settings
        }

    if num_workers > 1:
        # distribute inference
        inference_tasks = []
        for w in range(num_workers):
            inference_kwargs = {**inference_args, **{'index':w}}
            inference_tasks.append(
                aiw_int.call_inference.s(**inference_kwargs).set(queue='AIWorker'))
        task_list.append(celery.group(inference_tasks))

    else:
        # training on single worker
        inference_kwargs = {**inference_args, **{'index':0}}
        task_list.append(
            aiw_int.call_inference.s(**inference_kwargs).set(queue='AIWorker')
        )
    return celery.chain(task_list)



def create_celery_task(project: str,
                       task_description: dict,
                       is_first_task: bool,
                       verify_only: bool=False,
                       model_class: ModuleType=None) -> Union[celery.chain, bool]:
    '''
        Receives a task description (full dict with name and kwargs) and creates true Celery task
        routines from it. If "verifyOnly" is set to True, it just returns a bool indi- cating
        whether the task description is valid (True) or not (False). Accounts for special cases,
        such as:
            - train: if more than one worker is specified, the task is
                        a chain of distributed training and model state averaging.
            - train and inference: if no list of image IDs is provided,
                                    a job of retrieving the latest set of images is prepended.
            - etc.
        
        Returns a Celery job that can be appended to a global chain, or else a bool indicating if
        the task could be created or not (if "verify_only" is True).
    '''
    try:
        task_name = task_description['type'].lower()
        if task_name == 'train':
            task = get_training_signature(project,
                                          task_description['kwargs'],
                                          is_first_task,
                                          model_class)
        elif task_name == 'inference':
            task = get_inference_signature(project,
                                           task_description['kwargs'],
                                           is_first_task,
                                           model_class)
        else:
            task = None
    except Exception:
        task = None
    if verify_only:
        return task is not None
    return task



class WorkflowDesigner:
    '''
        Server backend class for parsing, saving, and launching workflow graph definitions.
    '''
    def __init__(self, db_connector, celery_app):
        self.db_connector = db_connector
        self.celery_app = celery_app


    def _get_num_available_workers(self) -> int:
        #TODO: improve...
        num_workers = 0
        i = self.celery_app.control.inspect()
        if i is not None:
            queues_active = i.active_queues()
            if queues_active is not None:
                for queue_name in queues_active.keys():
                    queue = queues_active[queue_name]
                    for subqueue in queue:
                        if 'name' in subqueue and subqueue['name'] == 'AIWorker':
                            num_workers += 1
        return num_workers


    def _get_project_defaults(self, project: str) -> dict:
        '''
            Queries and returns default values for some project-specific parameters.
        '''
        query_str = sql.SQL('''
            SELECT minNumAnnoPerImage, maxNumImages_train, maxNumImages_inference,
            ai_model_library
            FROM aide_admin.project
            WHERE shortname = %s;
        ''')
        result = self.db_connector.execute(query_str, (project,), 1)
        result = result[0]
        return {
            'train': {
                'min_anno_per_image': result['minnumannoperimage'],
                'max_num_images': result['maxnumimages_train']
            },
            'inference': {
                'max_num_images': result['maxnumimages_inference']
            },
            'ai_model_library': result['ai_model_library']
        }


    def parse_workflow(self,
                       project: str, workflow: Union[dict,str],
                       verify_only: bool=False) -> Union[celery.chain,bool]:
        '''
            Parses a workflow as described in the header of this file. Auto- completes missing
            arguments and provides appropriate function ex- pansion wherever needed (e.g., "train"
            may become "get images" > "train across multiple workers" > "average model states").

            If "verify_only" is set to True, the function returns a bool indi- cating whether the
            workflow is valid (True) or not (False). Else, it returns a Celery chain that can be
            submitted to the task queue via the AIController's middleware.
        '''

        #TODO: sanity checks
        if not isinstance(workflow, dict):
            workflow = json.loads(workflow)
        if not 'options' in workflow:
            workflow['options'] = {}    # for compatibility

        # get number of available workers
        num_workers_max = self._get_num_available_workers()

        # get default project settings for some of the parameters
        project_defaults = self._get_project_defaults(project)

        # initialize model instance to verify options if possible
        try:
            model_class = get_class_executable(project_defaults['ai_model_library'])
            # if hasattr(modelClass, 'verifyOptions'):
            #     response = modelClass.verifyOptions(modelOptions)
        except Exception:
            model_class = None

        # expand task specifications with repeaters
        workflow_expanded = workflow['tasks']
        if 'repeaters' in workflow:
            # get node order first
            node_order = []
            node_index = {}
            for idx, node in enumerate(workflow_expanded):
                if isinstance(node, dict) and 'id' in node:
                    node_order.append(node['id'])
                    node_index[node['id']] = idx

            # get start node for repeaters
            start_node_ids = {}
            for key in workflow['repeaters']:
                start_node = workflow['repeaters'][key]['start_node']
                start_node_ids[start_node] = key

            # process repeaters front to back (start with first)
            for node_id in node_order:
                if node_id in start_node_ids:
                    # find indices of start and end node
                    start_node_idx = node_index[node_id]
                    repeater_id = start_node_ids[node_id]
                    end_node_idx = node_index[workflow['repeaters'][repeater_id]['end_node']]

                    # extract and expand sub-workflow
                    sub_workflow = workflow['tasks'][end_node_idx:start_node_idx+1]
                    target_sub_workflow = []
                    num_reps = workflow['repeaters'][repeater_id]['kwargs']['num_repetitions']
                    for _ in range(num_reps):
                        target_sub_workflow.extend(sub_workflow.copy())

                    # insert after
                    workflow_expanded = workflow_expanded[:start_node_idx+1] + \
                                                target_sub_workflow + \
                                                workflow_expanded[start_node_idx+1:]

        # epoch counter (only training jobs can increment it)
        epoch = 1

        # parse entries in workflow
        task_descriptions = []
        for tidx, task_spec in enumerate(workflow_expanded):
            if isinstance(task_spec, str):
                # task name provided
                if task_spec in ('repeater', 'connector'):
                    continue
                #auto-expand into dict first
                task_description = expand_from_name(tidx,
                                                    project,
                                                    task_spec,
                                                    workflow,
                                                    project_defaults)
                task_name = task_description['type']

            elif isinstance(task_spec, dict):
                # task dictionary provided; verify and auto-complete if necessary
                task_description = task_spec.copy()
                if 'type' not in task_description:
                    raise ValueError(f'Task at index {tidx} is of unknown type.')
                task_name = task_description['type']
                if task_name in ('repeater', 'connector'):
                    continue
                if task_name not in DEFAULT_WORKFLOW_ARGS:
                    raise ValueError(f'Unknown task type provided ("{task_name}") ' + \
                                     f'for task at index {tidx}.')

            default_args = DEFAULT_WORKFLOW_ARGS[task_name].copy()
            if 'kwargs' not in task_description:
                # no arguments provided; add defaults
                task_description['kwargs'] = default_args

                # replace with global arguments wherever possible
                for key in task_description['kwargs'].keys():
                    if key in workflow['options']:
                        task_description['kwargs'][key] = workflow['options'][key]
                    elif key in project_defaults[task_name]:
                        task_description['kwargs'][key] = project_defaults[task_name][key]

            else:
                # arguments provided; auto-complete wherever needed
                for key in default_args.keys():
                    if not key in task_description['kwargs']:
                        if key in workflow['options']:
                            # global option available
                            task_description['kwargs'][key] = workflow['options'][key]
                        elif key in project_defaults[task_name]:
                            # fallback 1: default project setting
                            task_description['kwargs'][key] = project_defaults[task_name][key]
                        else:
                            # fallback 2: default option
                            task_description['kwargs'][key] = default_args[key]

            if 'max_num_workers' in task_description['kwargs']:
                if isinstance(task_description['kwargs']['max_num_workers'], str):
                    if len(task_description['kwargs']['max_num_workers']) > 0:
                        task_description['kwargs']['max_num_workers'] = \
                            int(task_description['kwargs']['max_num_workers'])
                    else:
                        task_description['kwargs']['max_num_workers'] = \
                            default_args['max_num_workers']

                task_description['kwargs']['max_num_workers'] = min(
                    task_description['kwargs']['max_num_workers'],
                    num_workers_max
                )
            else:
                task_description['kwargs']['max_num_workers'] = default_args['max_num_workers']

            task_description['kwargs']['epoch'] = epoch
            if task_name.lower() == 'train':
                epoch += 1

            task_descriptions.append(task_description)

        # construct celery tasks out of descriptions
        tasklist = []
        for tidx, task_description in enumerate(task_descriptions):
            # add number of epochs as argument
            task_description['kwargs']['numEpochs'] = epoch
            task = create_celery_task(project,
                                      task_description,
                                      is_first_task=tidx==0,
                                      verify_only=verify_only,
                                      model_class=model_class)
            tasklist.append(task)

        if verify_only:
            #TODO: detailed warnings and errors
            return all(tasklist)

        return celery.chain(tasklist)
