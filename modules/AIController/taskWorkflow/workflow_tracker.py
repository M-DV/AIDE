'''
    The WorkflowTracker is responsible for launching tasks and retrieving (sub-) task IDs for each
    submitted workflow, so that each (sub-) task's status can be queried. Launched workflows are
    also added to the workflow history table in the RDB.

    2020-24 Benjamin Kellenberger
'''

from typing import Iterable, Tuple, List, Union
from uuid import UUID
import json
from psycopg2 import sql
from celery import Task
from celery.result import ResultBase, AsyncResult, GroupResult



class WorkflowTracker:
    '''
        The WorkflowTracker is responsible for launching and aborting model workflow Celery tasks
        and querying statuses.
    '''
    def __init__(self, db_connector, celery_app):
        self.db_connector = db_connector
        self.celery_app = celery_app

        self.tasks_active = {}       # for caching


    @staticmethod
    def get_task_ids(result: ResultBase) -> List[str]:
        '''
            Receives a Celery result and returns a list of (sub-) task IDs in order.
        '''
        def _assemble_ids(result):
            def _get_task_id(result):
                res = {'id': result.id}
                if isinstance(result, GroupResult):
                    res['children'] = []
                    for child in result.children:
                        task, _ = _get_task_id(child)
                        res['children'].append(task)
                return res, result.id
            tasks = []
            res, _ = _get_task_id(result)
            tasks.append(res)
            if result.parent is not None:
                tasks.extend(_assemble_ids(result.parent))
            return tasks

        tasks = _assemble_ids(result)
        tasks.reverse()
        return tasks


    @staticmethod
    def get_tasks_info(tasks: Union[dict,str],
                       forget_if_finished: bool=True) -> Tuple[dict,bool,List[str]]:
        '''
            Receives a dict of tasks (or a JSON-parseable str) and retrieves results and messages
            for each. Calls Celery's "forget" routine for finished tasks if "forget_if_finished" is
            True.

            Args:
                - "tasks":              dict, containing task IDs as keys and metadata as values
                - "forget_if_finished": bool, calls Celery's "forget" routine for finished tasks if
                                        True (default).

            Returns:
                - dict, containing task IDs as keys and metadata (including results and messages) as
                  values
                - bool, True if the last task in the dict has finished and False otherwise
                - list, containing error messages if present
        '''
        if tasks is None:
            return None, False, None
        if isinstance(tasks, str):
            tasks = json.loads(tasks)
        errors = []
        for tidx, task in enumerate(tasks):
            result = AsyncResult(task['id'])
            if result.ready():
                tasks[tidx]['successful'] = result.successful()
                if tasks[tidx]['successful']:
                    tasks[tidx]['info'] = None
                else:
                    try:
                        error = str(result.get())
                        errors.append(error)
                    except Exception as e:
                        error = str(e)
                        errors.append(error)
                    tasks[tidx]['info'] = {}
                    tasks[tidx]['info']['message'] = error
                if forget_if_finished:
                    result.forget()
            elif result.info is not None:
                tasks[tidx]['info'] = result.info
            if result.status is not None:
                tasks[tidx]['status'] = result.status
            if 'children' in task:
                num_done = 0
                num_children = len(task['children'])
                for key in range(num_children):
                    c_res = AsyncResult(task['children'][key]['id'])
                    if c_res.ready():
                        num_done += 1
                        tasks[tidx]['children'][key]['successful'] = c_res.successful()
                        if tasks[tidx]['children'][key]['successful']:
                            tasks[tidx]['children'][key]['info'] = None
                        else:
                            try:
                                error = str(c_res.get())
                                errors.append(error)
                            except Exception as e:
                                error = str(e)
                                errors.append(error)
                            tasks[tidx]['children'][key]['info'] = {}
                            tasks[tidx]['children'][key]['info']['message'] = error
                        if forget_if_finished:
                            c_res.forget()
                    elif c_res.info is not None:
                        tasks[tidx]['children'][key]['info'] = c_res.info
                    if c_res.status is not None:
                        tasks[tidx]['children'][key]['status'] = c_res.status
                tasks[tidx]['num_done'] = num_done
                if num_done == num_children:
                    tasks[tidx]['status'] = 'SUCCESSFUL'

        last_result = AsyncResult(tasks[-1]['id'])
        has_finished = last_result.ready()

        return tasks, has_finished, errors


    @staticmethod
    def _revoke_task(tasks: Union[dict, Iterable[dict]]) -> None:
        if isinstance(tasks, dict) and 'id' in tasks:
            AsyncResult(tasks['id']).revoke(terminate=True)
        elif isinstance(tasks, Iterable):
            for task in tasks:
                WorkflowTracker._revoke_task(task)


    def _cache_task(self,
                    project: str,
                    task_id: Union[UUID, str],
                    task_details: Union[dict, str]) -> None:
        if project not in self.tasks_active:
            self.tasks_active[project] = {}
        if isinstance(task_details, str):
            task_details = json.loads(task_details)
        if not isinstance(task_id, str):
            task_id = str(task_id)
        self.tasks_active[project][task_id] = task_details


    def _remove_from_cache(self,
                           project: str,
                           task_id: Union[UUID, str]) -> None:
        if not project in self.tasks_active:
            return
        if not isinstance(task_id, str):
            task_id = str(task_id)
        if not task_id in self.tasks_active[project]:
            return
        del self.tasks_active[project][task_id]


    def launch_workflow(self,
                        project: str,
                        task: Task,
                        workflow: dict,
                        author: str=None) -> str:
        '''
            Receives a Celery task chain and the original, unexpanded workflow description (see
            WorkflowDesigner), and launches the task chain. Unravels the resulting Celery
            AsyncResult and retrieves all (sub-) task IDs and the like, and adds an entry to the
            data- base with it for other workers to be able to query. Stores it locally for caching.

            If the author is None (i.e., workflow was automatically initiated), the function first
            checks whether another auto-launched workflow is still running for this project. Since
            only one such workflow is permitted to run at a time per project, it then refuses to
            launch another one. Currently running workflows are identified through the database and
            Celery running status, if needed.

            Args:
                - project:      Project shortname
                - task:         Celery object (typically a chain) that contains all tasks to be
                                executed in the workflow
                - workflow:     Task workflow description, as acceptable by the WorkflowDesigner. We
                                store the original, non-expanded workflows, so that they can be
                                easily reused and visualized from the history, if required.
                - author:       Name of the workflow initiator. May be None if the workflow was
                                auto-launched.

            Returns:
                str, task UUID of launched workflow
        '''

        # create entry in database
        query_str = sql.SQL('''
            INSERT INTO {id_wHistory} (workflow, launchedBy)
            VALUES (%s, %s)
            RETURNING id;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory')
        )
        res = self.db_connector.execute(query_str, (json.dumps(workflow), author,), 1)
        task_id = res[0]['id']

        # submit workflow
        task_result = task.apply_async(task_id=str(task_id),
                        queue='AIWorker',
                        ignore_result=False,
                        # result_extended=True,
                        # headers={'headers':{'project':project,'submitted': str(current_time())}}
                        )

        # unravel subtasks with children and IDs
        taskdef = WorkflowTracker.get_task_ids(task_result)

        # add task names
        tasknames_flat = []
        def _flatten_names(task):
            if hasattr(task, 'tasks'):
                # chain or chord
                for subtask in task.tasks:
                    _flatten_names(subtask)

                tasknames_flat.append(task.name)

                if hasattr(task, 'body'):
                    # chord
                    tasknames_flat.append(task.body.name)
            else:
                tasknames_flat.append(task.name)
        _flatten_names(task)

        global t_idx
        t_idx = 0
        def _assign_names(taskdef):
            global t_idx
            if isinstance(taskdef, list):
                for td in taskdef:
                    _assign_names(td)
            else:
                if 'children' in taskdef:
                    for child in taskdef['children']:
                        _assign_names(child)
                taskdef['name'] = tasknames_flat[t_idx]
            t_idx += 1
        _assign_names(taskdef)

        # commit to DB
        query_str = sql.SQL('''
            UPDATE {id_wHistory}
            SET tasks = %s
            WHERE id = %s;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory')
        )
        self.db_connector.execute(query_str,
                                 (json.dumps(taskdef), task_id,),
                                 None)
        task_id = str(task_id)

        # cache locally
        self._cache_task(project,
                         task_id,
                         taskdef)

        return task_id


    def poll_task_status(self,
                         project: str,
                         task_id: str) -> dict:
        '''
            Receives a project shortname and task ID and queries Celery for status updates,
            including for subtasks. If the task has finished, the "forget()" method is called to
            clear the Celery queue.
        '''
        if project not in self.tasks_active or \
            task_id not in self.tasks_active[project]:
            # project not cached; get from database
            query_str = sql.SQL('''
                SELECT tasks FROM {id_wHistory}
                WHERE id = %s
                ORDER BY timeCreated DESC;
            ''').format(
                id_wHistory=sql.Identifier(project, 'workflowhistory')
            )
            result = self.db_connector.execute(query_str, (task_id,), 1)
            tasks = result[0]['tasks']

            # cache locally
            self._cache_task(project, task_id, tasks)

        else:
            tasks = self.tasks_active[project][task_id]

        # poll for updates
        tasks, has_finished, errors = WorkflowTracker.get_tasks_info(tasks, False)

        # commit missing details to database if finished
        if has_finished:
            query_str = sql.SQL('''
                UPDATE {id_wHistory}
                SET timeFinished = NOW(),
                succeeded = %s,
                messages = %s
                WHERE id = %s;
            ''').format(
                id_wHistory=sql.Identifier(project, 'workflowhistory')
            )
            self.db_connector.execute(query_str,
                (len(errors)==0, json.dumps(errors), task_id), None)

            # remove from Celery and from local cache
            WorkflowTracker.get_tasks_info(tasks, True)
            self._remove_from_cache(project, task_id)

        return tasks


    def get_active_task_ids(self, project: str) -> List[str]:
        '''
            Receives a project shortname and queries the database for unfinished and running tasks.
            Also caches them locally for faster access.
        '''
        response = []

        query_str = sql.SQL('''
            SELECT id, tasks FROM {id_wHistory}
            WHERE timeFinished IS NULL
            AND succeeded IS NULL
            AND abortedBy IS NULL
            ORDER BY timeCreated DESC;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory')
        )
        result = self.db_connector.execute(query_str, None, 'all')

        for r in result:
            task_id = r['id']
            response.append(task_id)
            self._cache_task(project, task_id, r['tasks'])

        return response


    def get_tasks(self,
                  project: str,
                  running_or_finished: str='both',
                  min_time_created: float=None,
                  limit: int=None) -> List[dict]:
        '''
            Retrieves all tasks that have been submitted at some point.
            Args:
                - "running_or_finished":    str, whether to retrieve only running ('running'),
                                            only finished ('finished'), or both ('both') tasks.
                - "min_time_created":       float, minimum date and time when tasks had been
                                            created.
                - "limit":                  int, limit on the number of tasks retrieved.
            
            Returns:
                list, containing dict entries for all tasks found.
        '''
        query_criteria = ''
        query_args = []
        running_or_finished = running_or_finished.lower()
        if running_or_finished == 'running':
            query_criteria = 'WHERE timeFinished IS NULL'
        elif running_or_finished == 'finished':
            query_criteria = 'WHERE timeFinished IS NOT NULL'
        if min_time_created is not None:
            query_criteria += ('WHERE ' if len(query_criteria) == 0 else ' AND ')
            query_criteria += 'timeCreated > %s'
            query_args.append(min_time_created)
        if isinstance(limit, int):
            query_criteria += ' LIMIT %s'
            query_args.append(limit)

        query_str = sql.SQL('''
            SELECT * FROM {id_wHistory}
            {queryCriteria}
            ORDER BY timeCreated DESC;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory'),
            queryCriteria=sql.SQL(query_criteria)
        )
        result = self.db_connector.execute(query_str,
                                          (None if len(query_args) == 0 \
                                          else tuple(query_args)), 'all')
        response = []
        for r in result:
            response.append({
                'id': str(r['id']),
                'launched_by': r['launchedby'],
                'aborted_by': r['abortedby'],
                'time_created': r['timecreated'].timestamp(),
                'time_finished': (r['timefinished'].timestamp() \
                                    if r['timefinished'] is not None else None),
                'succeeded': r['succeeded'],
                'messages': r['messages'],
                'tasks': (json.loads(r['tasks']) \
                                if isinstance(r['tasks'], str) else r['tasks']),
                'workflow': (json.loads(r['workflow']) \
                                if isinstance(r['workflow'], str) else r['workflow'])
            })
        return response


    def poll_all_task_statuses(self, project: str) -> list:
        '''
            Retrieves all running tasks in a project and returns their IDs, together with a status
            update for each.
        '''
        tasks_active = self.get_tasks(project, running_or_finished='both')

        for tidx, task_meta in enumerate(tasks_active):
            chain_status = self.poll_task_status(project, task_meta['id'])
            if chain_status is not None:
                tasks_active[tidx]['children'] = chain_status

        return tasks_active


    def revoke_task(self,
                    username: str,
                    project: str,
                    task_id: str) -> None:
        '''
            Revokes (cancels) an ongoing task.
        '''
        # check if task with ID exists
        if project not in self.tasks_active or \
            task_id not in self.tasks_active[project]:
            # query database
            query_str = sql.SQL('''
                SELECT tasks FROM {id_wHistory}
                WHERE id = %s;
            ''').format(
                id_wHistory=sql.Identifier(project, 'workflowhistory')
            )
            result = self.db_connector.execute(query_str, (task_id,), 1)
            tasks = result[0]['tasks']
        else:
            tasks = self.tasks_active[project][task_id]

        # revoke everything
        if isinstance(tasks, str):
            tasks = json.loads(tasks)
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    task = json.loads(task)
                WorkflowTracker._revoke_task(task)

        # commit to DB
        query_str = sql.SQL('''
            UPDATE {id_wHistory}
            SET timeFinished = NOW(),
            succeeded = FALSE,
            abortedBy = %s
            WHERE id = %s;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory')
        )
        self.db_connector.execute(query_str, (username, task_id), None)


    def delete_workflow(self,
                        project: str,
                        ids: Union[UUID, Iterable[UUID], str],
                        revoke_running: bool=False) -> None:
        '''
            Removes workflow entries from the database. Input "ids" may either be a UUID, an
            Iterable of UUIDs, or "all", in which case all workflows are removed from the project.
            If "revoke_running" is True, all workflows with given IDs that happen to still be
            running are aborted. Otherwise, their deletion is skipped.
        '''
        workflow_ids = []
        if ids == 'all':
            # get all workflow IDs from DB
            if revoke_running:
                running_str = sql.SQL('')
            else:
                running_str = sql.SQL('WHERE timefinished IS NOT NULL')

            workflow_ids = self.db_connector.execute(
                sql.SQL('''
                    SELECT id FROM {id_workflowhistory}
                    {runningStr};
                ''').format(
                    id_workflowhistory=sql.Identifier(project, 'workflowhistory'),
                    runningStr=running_str
                ),
                None,
                'all'
            )

        else:
            if isinstance(ids, str):
                ids = [UUID(ids)]
            elif not isinstance(ids, Iterable):
                ids = [ids]
            for w, next_id in enumerate(ids):
                if not isinstance(next_id, UUID):
                    next_id = UUID(next_id)
                workflow_ids.append({'id': next_id})

        if revoke_running:
            # no need to commit revoke to DB since we're going to delete the workflows anyway
            WorkflowTracker._revoke_task(workflow_ids)

        # delete from database
        self.db_connector.execute(sql.SQL('''
            DELETE FROM {id_workflowhistory}
            WHERE id IN %s;
            '''
        ).format(
            id_workflowhistory=sql.Identifier(project, 'workflowhistory'),
        ), tuple((w['id'],) for w in workflow_ids))
