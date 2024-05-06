'''
    Contains keyword arguments and their default values for workflows. Used to auto-complete
    arguments that are missing in submitted workflows. Workflow items with all the given arguments
    are then parsed into actual Celery workflows by the workflow designer.

    2020-24 Benjamin Kellenberger
'''



DEFAULT_WORKFLOW_ARGS = {
    'train': {
        'min_timestamp': 'lastState',
        'min_anno_per_image': 0,
        'include_golden_questions': False,   #TODO
        'max_num_images': -1,
        'max_num_workers': -1
    },
    'inference': {
        'force_unlabeled': False,       #TODO
        'golden_questions_only': False, #TODO
        'max_num_images': -1,
        'max_num_workers': -1
    },
    #TODO
}



# Default workflow to execute on auto-training if no custom one specified. Some parameters (e.g.,
# "max_num_images", "max_num_workers") may be overridden depending on the project settings regarding
# the default workflow.
DEFAULT_WORKFLOW_AUTOTRAIN = {
    'tasks': [
        {
            'id': 'default_train',
            'type': 'train',
            'kwargs': {
                'min_timestamp': 'lastState',
                'numEpochs': 1,
                'min_anno_per_image': 0,
                'include_golden_questions': True,
                'max_num_images': 0,
                'max_num_workers': 1
            }
        },
        {
            'id': 'default_inference',
            'type': 'inference',
            'kwargs': {
                'force_unlabeled': True,
                'golden_questions_only': False,
                'numEpochs': 1,
                'max_num_workers': 1
            }
        },
    ]
}


# DEFAULT_WORKFLOW_INFERENCE_NEW = {
#     # default workflow for performing inference on newly uploaded images
#     "project": None,
#     "tasks": [
#         {
#             "id": "inference",
#             "type": "inference",
#             "kwargs": {
#                 "numEpochs": 1,
#                 "forceUnpredicted": True    #TODO: implement
#             }
#         }
#     ]
# }
