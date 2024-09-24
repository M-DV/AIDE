'''
    2024 Benjamin Kellenberger
'''

from threading import Thread, Event
from celery import current_app



class TaskWatchdog(Thread):
    '''
        Periodically polls the Celery backend for running tasks in a separate (non-blocking) thread.
    '''
    def __init__(self) -> None:
        super().__init__()

        self.tasks = {}             # task_id: task_meta
        self.timer = Event()
        self._stop_event = Event()
        self.setDaemon(True)        # required to enable external shutdown of thread


    def _check_ongoing_tasks(self) -> None:
        self.tasks = {}
        tasks_active = current_app.control.inspect().active()   #TODO: failsafety?
        if not isinstance(tasks_active, dict):
            tasks_active = {}
        for worker_id, tasks in tasks_active.items():
            for task_meta in tasks:
                task_meta['worker_id'] = worker_id
                self.tasks[task_meta['id']] = task_meta


    def nudge(self) -> None:
        '''
            Force re-checks running tasks.
        '''
        self._check_ongoing_tasks()


    def stop(self) -> None:
        '''
            Terminates periodic querying for annotations.
        '''
        self._stop_event.set()


    @property
    def stopped(self) -> bool:
        '''
            Returns True if the stop event for annotation querying is set (and False otherwise).
        '''
        return self._stop_event.is_set()


    def run(self) -> None:
        '''
            Main thread event. Periodically checks for ongoing tasks with a dynamically adjusting
            delay.
        '''
        while True:
            if self.stopped:
                return
            self._check_ongoing_tasks()
            self.timer.wait(10)     #TODO: delay
