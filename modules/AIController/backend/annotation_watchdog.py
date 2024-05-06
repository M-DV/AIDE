'''
    2019-24 Benjamin Kellenberger
'''

import json
from threading import Thread, Event
import math
from psycopg2 import sql
from celery import current_app

from ..taskWorkflow.defaultOptions import DEFAULT_WORKFLOW_AUTOTRAIN
from ..taskWorkflow import task_ids_match



class Watchdog(Thread):
    '''
        Threadable class that periodically polls the database for new annotations (i.e., images that
        have been screened since the creation date of the last model state). If the number of newly
        screened images reaches or exceeds a threshold as defined in the configuration file, a
        'train' task is submitted to the Celery worker(s) and this thread is terminated.
    '''
    def __init__(self, project, config, db_connector, middleware) -> None:
        super().__init__()
        self.project = project
        self.config = config
        self.db_connector = db_connector
        self.middleware = middleware

        self.timer = Event()
        self._stop_event = Event()

        # waiting times (seconds)
        self.max_wait_time = 1800
        self.min_wait_time = 20
        self.current_wait_time = self.min_wait_time     # modulated based on progress and activity

        self.last_count = 0                             # for difference tracking

        self._load_properties()

        self._check_ongoing_tasks()


    def _check_ongoing_tasks(self) -> None:
        #TODO: limit to AIModel tasks
        self.tasks_running = []
        tasks_running_db = {}
        query_result = None
        try:
            query_result = self.db_connector.execute(
                sql.SQL('''
                    SELECT id, tasks, timeFinished, succeeded, abortedBy
                    FROM {}
                    WHERE launchedBy IS NULL AND timeFinished IS NULL;
                ''').format(sql.Identifier(self.project, 'workflowhistory')),
                None, 'all'
            )
        except Exception:
            # couldn't query database anymore, assume project is dead and kill watchdog
            self.stop()
            return
        if query_result is not None:
            for task in query_result:
                #TODO: fields to choose?
                if task['timefinished'] is None and \
                    task['abortedby'] is None:
                    tasks_running_db[task['id']] = json.loads(task['tasks'])

        tasks_orphaned = set()
        tasks_active = current_app.control.inspect().active()
        if not isinstance(tasks_active, dict):
            tasks_active = {}
        for task_key, task_db in tasks_running_db.items():
            # auto-launched workflow running according to database; check Celery for completeness
            if len(tasks_active) == 0:
                # no task is running; flag all in DB as "orphaned"
                tasks_orphaned.add(task_key)

            else:
                for key in tasks_active:
                    for task in tasks_active[key]:
                        # check type of task
                        task_name = task['name'].lower()
                        if not (task_name.startswith('aiworker') or \
                            task_name in ('aicontroller.get_training_images', \
                                          'aicontroller.get_inference_images')):
                            # task is not AI model training-related; skip
                            continue

                        if task_ids_match(task_db, task['id']):
                            # confirmed task running
                            self.tasks_running.append(task['id'])
                        else:
                            # task not running; check project and flag as such in database
                            try:
                                project = task['kwargs']['project']
                                if project == self.project:
                                    tasks_orphaned.add(task_key)
                            except Exception:
                                continue

        # vice-versa: check running tasks and re-enable them if flagged as orphaned in DB
        tasks_resurrected = set()
        for key in tasks_active:
            for task in tasks_active[key]:

                # check type of task
                task_name = task['name'].lower()
                if not (task_name.startswith('aiworker') or \
                    task_name in ('aicontroller.get_training_images', \
                                  'aicontroller.get_inference_images')):
                    # task is not AI model training-related; skip
                    continue

                try:
                    project = task['kwargs']['project']
                    task_id = task['id']
                    if project == self.project and task_id not in tasks_running_db:
                        tasks_resurrected.add(task_id)
                        self.tasks_running.append(task_id)
                except Exception:
                    continue

        tasks_orphaned = tasks_orphaned.difference(tasks_resurrected)

        # clean up orphaned tasks
        if len(tasks_orphaned) > 0:
            self.db_connector.execute(sql.SQL('''
                UPDATE {}
                SET timeFinished = NOW(), succeeded = FALSE,
                    messages = 'Auto-launched task did not finish'
                WHERE id IN %s;
            ''').format(sql.Identifier(self.project, 'workflowhistory')),
                (tuple((t,) for t in tasks_orphaned),), None)

        # resurrect running tasks if needed
        if len(tasks_resurrected) > 0:
            self.db_connector.execute(sql.SQL('''
                UPDATE {}
                SET timeFinished = NULL, succeeded = NULL, messages = NULL
                WHERE id IN %s;
            ''').format(sql.Identifier(self.project, 'workflowhistory')),
                (tuple((t,) for t in tasks_resurrected),), None)


    def _load_properties(self) -> None:
        '''
            Loads project auto-train properties, such as the number of images until re-training,
            from the database.
        '''
        self.properties = self.db_connector.execute('''SELECT * FROM aide_admin.project
                                                       WHERE shortname = %s''',
                                                    (self.project,),
                                                    1)
        self.properties = self.properties[0]
        if self.properties['numimages_autotrain'] is None:
            # auto-training disabled
            self.properties['numimages_autotrain'] = -1
        if self.properties['minnumannoperimage'] is None:
            self.properties['minnumannoperimage'] = 0
        min_num_anno = self.properties['minnumannoperimage']
        if min_num_anno > 0:
            min_num_anno_str = sql.SQL('''
                WHERE image IN (
                    SELECT cntQ.image FROM (
                        SELECT image, count(*) AS cnt FROM {id_anno}
                        GROUP BY image
                    ) AS cntQ WHERE cntQ.cnt > %s
                )
            ''').format(
                id_anno=sql.Identifier(self.project, 'annotation')
            )
            self.query_vals = (min_num_anno,)
        else:
            min_num_anno_str = sql.SQL('')
            self.query_vals = None
        self.query_str = sql.SQL('''
            SELECT COUNT(image) AS count FROM (
                SELECT image, MAX(last_checked) AS lastChecked FROM {id_iu}
                {minNumAnnoString}
                GROUP BY image
            ) AS query
            WHERE query.lastChecked > (
                SELECT MAX(timeCreated) FROM (
                    SELECT to_timestamp(0) AS timeCreated
                    UNION (
                        SELECT MAX(timeCreated) AS timeCreated FROM {id_cnnstate}
                    )
            ) AS tsQ);
        ''').format(
            id_iu=sql.Identifier(self.project, 'image_user'),
            id_cnnstate=sql.Identifier(self.project, 'cnnstate'),
            minNumAnnoString=min_num_anno_str)

        # default workflow (if no custom one provided)
        self.default_workflow = DEFAULT_WORKFLOW_AUTOTRAIN.copy()
        self.default_workflow['tasks'][0]['kwargs'].update({
            'min_anno_per_image': self.properties['minnumannoperimage'],
            'max_num_images': self.properties.get('maxnumimages_train', 0),
            'max_num_workers': self.config.get_property('AIController',
                                                        'maxNumWorkers_train',
                                                        dtype=int,
                                                        fallback=1)
        })
        self.default_workflow['tasks'][1]['kwargs'].update({
            'max_num_images': self.properties.get('maxnumimages_inference', 0),
            'max_num_workers': self.config.get_property('AIController',
                                                        'maxNumWorkers_train',
                                                        dtype=int,
                                                        fallback=1)
        })


    def nudge(self) -> None:
        '''
            Notifies the watchdog that users are active; in this case the querying interval is
            shortened.
        '''
        self.current_wait_time = self.min_wait_time


    def recheck_autotrain_settings(self) -> None:
        '''
            Force re-check of auto-train mode of project. To be called whenever auto-training is
            changed through the configuration page.
        '''
        self._load_properties()
        self.nudge()


    def get_threshold(self) -> int:
        '''
            Returns the number of images that have to be checked for the current project to initiate
            the auto-training sequence.
        '''
        return self.properties['numimages_autotrain']


    def get_model_autotrain_enabled(self) -> bool:
        '''
            Returns True if an AI model auto-training schedule is set for the current project (and
            False otherwise).
        '''
        return self.properties['ai_model_enabled']


    def get_ongoing_tasks(self) -> list:
        '''
            Returns a list of UUIDs of tasks currently ongoing (unfinished) in project.
        '''
        self._check_ongoing_tasks()
        return self.tasks_running


    def stop(self) -> None:
        '''
            Terminates periodic querying for annotations.
        '''
        self._stop_event.set()


    def stopped(self) -> bool:
        '''
            Returns True if the stop event for annotation querying is set (and False otherwise).
        '''
        return self._stop_event.is_set()


    def run(self) -> None:
        '''
            Main thread event. Periodically polls for new annotations (with a dynamically adjusting
            delay). As soon as the number of images checked by annotators matches or exceeds the
            project-specific threshold, the automatic AI model training/inference routine will be
            launched. If a project has automated AI model re-training enabled but no specific
            workflow set, a standard training-inference task will be launched. If the number of
            images checked does not yet match the threshold, function will adjust the periodic
            polling interval according to activity.
        '''
        while True:
            if self.stopped():
                return

            # check if project still exists (TODO: less expensive alternative?)
            project_exists = self.db_connector.execute('''
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s
                        AND table_name = 'workflowhistory'
                    );
                ''', (self.project,), 1)
            if not project_exists[0]['exists']:
                # project doesn't exist anymore; terminate process
                self.stop()
                return

            is_task_ongoing = len(self.get_ongoing_tasks()) > 0

            if self.get_model_autotrain_enabled() and self.get_threshold() > 0:

                # check if AIController worker and AIWorker are available
                ai_model_info = self.middleware.get_ai_model_training_info(self.project)
                has_aic_worker = len(ai_model_info['workers']['AIController']) > 0
                has_aiw_worker = len(ai_model_info['workers']['AIWorker']) > 0

                # poll for user progress
                count = self.db_connector.execute(self.query_str,
                                                  self.query_vals,
                                                  1)
                if count is None:
                    # project got deleted
                    return
                count = count[0]['count']

                if not is_task_ongoing and \
                    count >= self.properties['numimages_autotrain'] and \
                        has_aic_worker and has_aiw_worker:
                    # threshold exceeded; load workflow
                    default_workflow_id = self.db_connector.execute('''
                        SELECT default_workflow FROM aide_admin.project
                        WHERE shortname = %s;
                    ''', (self.project,), 1)
                    default_workflow_id = default_workflow_id[0]['default_workflow']

                    try:
                        if default_workflow_id is not None:
                            # default workflow set
                            self.middleware.launch_task(self.project, default_workflow_id, None)

                        else:
                            # no workflow set; launch standard training-inference chain
                            self.middleware.launch_task(self.project,
                                                        self.default_workflow,
                                                        None)

                    except Exception:
                        # error in case auto-launched task is already ongoing; ignore
                        pass

                else:
                    # users are still labeling; update waiting time
                    progress_perc = count / self.properties['numimages_autotrain']
                    wait_time_frac = (0.8*(1 - math.pow(progress_perc, 4))) + \
                                        (0.2 * (1 - math.pow((count - self.last_count)/\
                                            max(1, count + self.last_count), 2)))

                    self.current_wait_time = max(self.min_wait_time,
                                                 min(self.max_wait_time,
                                                     self.max_wait_time * wait_time_frac))
                    self.last_count = count


            # wait in intervals to be able to listen to nudges
            seconds_waited = 0
            while seconds_waited < self.current_wait_time:
                self.timer.wait(seconds_waited)
                seconds_waited += 10     # be able to respond every ten seconds
