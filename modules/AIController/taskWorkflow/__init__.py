'''
    2020-24 Benjamin Kellenberger
'''

from typing import Union



def task_ids_match(workflow: Union[list,dict,str], task_id: str) -> bool:
    '''
        Iterates through all the subtasks in a given workflow and compares their IDs with the given
        taskID. Returns True if one of them matches and False otherwise.
    '''
    if isinstance(workflow, list):
        for wf in workflow:
            if task_ids_match(wf, task_id):
                return True
    elif isinstance(workflow, dict):
        if 'id' in workflow:
            if workflow['id'] == task_id:
                return True
        if 'children' in workflow:
            if task_ids_match(workflow['children'], task_id):
                return True
    elif isinstance(workflow, str):
        if workflow == task_id:
            return True
    return False
