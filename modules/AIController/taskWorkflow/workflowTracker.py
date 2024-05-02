'''
    The WorkflowTracker is responsible for launching tasks and retrieving (sub-) task IDs for each
    submitted workflow, so that each (sub-) task's status can be queried. Launched workflows are
    also added to the workflow history table in the RDB.

    2020-24 Benjamin Kellenberger
'''

from typing import Iterable
from uuid import UUID
import json
from psycopg2 import sql
import celery
from celery.result import AsyncResult, GroupResult



class WorkflowTracker:

    def __init__(self, dbConnector, celeryApp):
        self.dbConnector = dbConnector
        self.celeryApp = celeryApp

        self.activeTasks = {}       # for caching



    @staticmethod
    def getTaskIDs(result):
        def _assemble_ids(result):
            def _get_task_id(result):
                r = {'id': result.id}
                if isinstance(result, GroupResult):
                    r['children'] = []
                    # r['children'] = {}
                    for child in result.children:
                        task, _ = _get_task_id(child)
                        r['children'].append(task)
                        # r['children'][taskID] = task
                return r, result.id
            tasks = []
            r, _ = _get_task_id(result)
            tasks.append(r)
            if result.parent is not None:
                tasks.extend(_assemble_ids(result.parent))
            return tasks

        tasks = _assemble_ids(result)
        tasks.reverse()
        return tasks



    @staticmethod
    def getTasksInfo(tasks, forgetIfFinished=True):
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
                if forgetIfFinished:
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
                        if forgetIfFinished:
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
    def _revoke_task(tasks):
        if isinstance(tasks, dict) and 'id' in tasks:
            AsyncResult(tasks['id']).revoke(terminate=True)
            # celery.task.control.revoke(tasks['id'], terminate=True)
        elif isinstance(tasks, Iterable):
            for task in tasks:
                WorkflowTracker._revoke_task(task)



    def _cache_task(self, project, taskID, taskDetails):
        if not project in self.activeTasks:
            self.activeTasks[project] = {}
        if isinstance(taskDetails, str):
            taskDetails = json.loads(taskDetails)
        if not isinstance(taskID, str):
            taskID = str(taskID)
        self.activeTasks[project][taskID] = taskDetails


    def _remove_from_cache(self, project, taskID):
        if not project in self.activeTasks:
            return
        if not isinstance(taskID, str):
            taskID = str(taskID)
        if not taskID in self.activeTasks[project]:
            return
        del self.activeTasks[project][taskID]


    def launchWorkflow(self, project, task, workflow, author=None):
        '''
            Receives a Celery task chain and the original, unexpanded workflow description (see
            WorkflowDesigner), and launches the task chain. Unravels the resulting Celery
            AsyncResult and retrieves all (sub-) task IDs and the like, and adds an entry to the
            data- base with it for other workers to be able to query. Stores it locally for caching.

            Inputs:
                - project:      Project shortname
                - task:         Celery object (typically a chain) that
                                contains all tasks to be executed in the workflow
                - workflow:     Task workflow description, as acceptable
                                by the WorkflowDesigner. We store the ori- ginal, non-expanded
                                workflows, so that they can be easily reused and visualized from the
                                history, if required.
                - author:       Name of the workflow initiator. May be
                                None if the workflow was auto-launched.

            If the author is None (i.e., workflow was automatically initi- ated), the function first
            checks whether another auto-launched workflow is still running for this project. Since
            only one such workflow is permitted to run at a time per project, it then refuses to
            launch another one. Currently running workflows are identified through the database and
            Celery running status, if needed.
        '''

        # create entry in database
        query_str = sql.SQL('''
            INSERT INTO {id_wHistory} (workflow, launchedBy)
            VALUES (%s, %s)
            RETURNING id;
        ''').format(
            id_wHistory=sql.Identifier(project, 'workflowhistory')
        )
        res = self.dbConnector.execute(query_str, (json.dumps(workflow), author,), 1)
        task_id = res[0]['id']


        # submit workflow
        task_result = task.apply_async(task_id=str(task_id),
                        queue='AIWorker',
                        ignore_result=False,
                        # result_extended=True,
                        # headers={'headers':{'project':project,'submitted': str(current_time())}}
                        )

        # unravel subtasks with children and IDs
        taskdef = WorkflowTracker.getTaskIDs(task_result)

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
        self.dbConnector.execute(query_str,
                                 (json.dumps(taskdef), task_id,),
                                 None)
        task_id = str(task_id)

        # cache locally
        self._cache_task(project,
                         task_id,
                         taskdef)

        return task_id



    def pollTaskStatus(self, project, taskID):
        '''
            Receives a project shortname and task ID and queries
            Celery for status updates, including for subtasks.
            If the task has finished, the "forget()" method is
            called to clear the Celery queue.
        '''

        if project not in self.activeTasks or \
            taskID not in self.activeTasks[project]:
            # project not cached; get from database
            query_str = sql.SQL('''
                SELECT tasks FROM {id_wHistory}
                WHERE id = %s
                ORDER BY timeCreated DESC;
            ''').format(
                id_wHistory=sql.Identifier(project, 'workflowhistory')
            )
            result = self.dbConnector.execute(query_str, (taskID,), 1)
            tasks = result[0]['tasks']

            # cache locally
            self._cache_task(project, taskID, tasks)

        else:
            tasks = self.activeTasks[project][taskID]

        # poll for updates
        tasks, has_finished, errors = WorkflowTracker.getTasksInfo(tasks, False)

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
            self.dbConnector.execute(query_str,
                (len(errors)==0, json.dumps(errors), taskID), None)

            # remove from Celery and from local cache
            WorkflowTracker.getTasksInfo(tasks, True)
            self._remove_from_cache(project, taskID)

        return tasks



    def getActiveTaskIDs(self, project):
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
        result = self.dbConnector.execute(query_str, None, 'all')

        for r in result:
            task_id = r['id']
            response.append(task_id)
            self._cache_task(project, task_id, r['tasks'])

        return response



    def getTasks(self, project, runningOrFinished='both', min_timeCreated=None, limit=None):
        '''
            Retrieves all tasks that have been submitted at some point.
            Inputs:
                - "runningOrFinished":  Whether to retrieve only running ('running'),
                                        only finished ('finished'), or both ('both')
                                        tasks.
                - "min_timeCreated":    Minimum date and time when tasks had been created.
                - "limit":              Limit the number of tasks retrieved.
            
            Returns a list with dict entries for all tasks found.
        '''
        query_criteria = ''
        query_args = []
        runningOrFinished = runningOrFinished.lower()
        if runningOrFinished == 'running':
            query_criteria = 'WHERE timeFinished IS NULL'
        elif runningOrFinished == 'finished':
            query_criteria = 'WHERE timeFinished IS NOT NULL'
        if min_timeCreated is not None:
            query_criteria += ('WHERE ' if len(query_criteria) == 0 else ' AND ')
            query_criteria += 'timeCreated > %s'
            query_args.append(min_timeCreated)
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
        result = self.dbConnector.execute(query_str,
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



    def pollAllTaskStatuses(self, project: str) -> list:
        '''
            Retrieves all running tasks in a project and returns their IDs, together with a status
            update for each.
        '''
        tasks_active = self.getTasks(project, runningOrFinished='both')

        for tidx, task_id in enumerate(tasks_active):
            chain_status = self.pollTaskStatus(project, task_id)
            if chain_status is not None:
                tasks_active[tidx]['children'] = chain_status

        return tasks_active


    def revokeTask(self, username, project, taskID):
        '''
            Revokes (cancels) an ongoing task.
        '''
        # check if task with ID exists
        if project not in self.activeTasks or \
            taskID not in self.activeTasks[project]:
            # query database
            query_str = sql.SQL('''
                SELECT tasks FROM {id_wHistory}
                WHERE id = %s;
            ''').format(
                id_wHistory=sql.Identifier(project, 'workflowhistory')
            )
            result = self.dbConnector.execute(query_str, (taskID,), 1)
            tasks = result[0]['tasks']
        else:
            tasks = self.activeTasks[project][taskID]

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
        self.dbConnector.execute(query_str, (username, taskID), None)

        #TODO: return value?


    def deleteWorkflow(self, project, ids, revokeIfRunning=False):
        '''
            Removes workflow entries from the database. Input "ids" may either be a UUID, an
            Iterable of UUIDs, or "all", in which case all workflows are removed from the project.
            If "revokeIfRunning" is True, all workflows with given IDs that happen to still be
            running are aborted. Otherwise, their deletion is skipped.
        '''
        workflow_ids = []
        if ids == 'all':
            # get all workflow IDs from DB
            if revokeIfRunning:
                runningStr = sql.SQL('')
            else:
                runningStr = sql.SQL('WHERE timefinished IS NOT NULL')

            workflow_ids = self.dbConnector.execute(
                sql.SQL('''
                    SELECT id FROM {id_workflowhistory}
                    {runningStr};
                ''').format(
                    id_workflowhistory=sql.Identifier(project, 'workflowhistory'),
                    runningStr=runningStr
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

        if revokeIfRunning:
            # no need to commit revoke to DB since we're going to delete the workflows anyway
            WorkflowTracker._revoke_task(workflow_ids)

        # delete from database
        self.dbConnector.execute(sql.SQL('''
            DELETE FROM {id_workflowhistory}
            WHERE id IN %s;
            '''
        ).format(
            id_workflowhistory=sql.Identifier(project, 'workflowhistory'),
        ), tuple((w['id'],) for w in workflow_ids))

