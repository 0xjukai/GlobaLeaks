# -*- coding: UTF-8
import time

from globaleaks.utils.mailutils import schedule_exception_email, extract_exception_traceback_and_send_email
from globaleaks.utils.utility import log
from twisted.internet import task, defer, reactor, threads

test_reactor = None

TRACK_LAST_N_EXECUTIONS = 10


class BaseJob(task.LoopingCall):
    name = "unnamed"
    interval = 1
    low_time = -1
    high_time = -1
    mean_time = -1
    start_time = -1
    active = None
    last_executions = []
    threaded = True

    def __init__(self):
        self.job = task.LoopingCall.__init__(self, self.run)
        self.clock = reactor if test_reactor is None else test_reactor

    def start(self, interval):
        task.LoopingCall.start(self, interval)

    @defer.inlineCallbacks
    def stop(self):
        if self.running:
            task.LoopingCall.stop(self)

        if self.active is not None:
            yield self.active

    def schedule(self):
        delay = self.get_start_time()
        delay = delay if delay > 1 else 1
        self.clock.callLater(delay, self.start, self.interval)
        return self

    @defer.inlineCallbacks
    def run(self):
        self.begin()

        try:
            if self.threaded:
                yield threads.deferToThread(self.operation)
            else:
                yield self.operation()
        except Exception as e:
            self.on_error(e)

        self.end()

    def begin(self):
        self.active = defer.Deferred()
        self.start_time = int(time.time() * 1000)
        self.last_executions=self.last_executions[:TRACK_LAST_N_EXECUTIONS - 1]
        self.last_executions.append((self.start_time, -1))

    def end(self):
        self.end_time = int(time.time() * 1000)
        last_execution = self.last_executions.pop()
        self.last_executions.append((last_execution[0], self.end_time))

        current_run_time = self.end_time - self.start_time

        # discard empty cycles from stats
        if self.mean_time == -1:
            self.mean_time = current_run_time
        else:
            self.mean_time = (self.mean_time * 0.7) + (current_run_time * 0.3)

        if self.low_time == -1 or current_run_time < self.low_time:
            self.low_time = current_run_time

        if self.high_time == -1 or current_run_time > self.high_time:
            self.high_time = current_run_time

        self.active.callback(None)
        self.active = None

    def operation(self):
        return

    def get_start_time(self):
        return 0

    def on_error(self, excep):
        log.err("Exception while running %s" % self.name)
        log.exception(excep)
        extract_exception_traceback_and_send_email(excep)


class LoopingJob(BaseJob):
    interval = 60

    # The minimum interval (seconds) the job has taken to execute before an
    # exception will be recorded. If the job does not finish, every monitor_interval
    # after the first exception another will be generated.
    monitor_interval = 60
    monitor_period = 5 * 60
    last_monitor_check_failed = 0 # Epoch start

    def on_error(self, excep):
        error = "Job %s died with runtime %.4f [low: %.4f, high: %.4f]" % \
                (self.name, self.mean_time, self.low_time, self.high_time)
        log.err(error)
        log.exception(excep)
        extract_exception_traceback_and_send_email(excep)


class LoopingJobsMonitor(LoopingJob):
    name = "jobs monitor"
    interval = 1

    def __init__(self, jobs_list):
        LoopingJob.__init__(self)
        self.jobs_list = jobs_list

    def operation(self):
        current_time = time.time()

        error_msg = ""
        for job in self.jobs_list:
            if job.active is None:
                continue

            execution_time = current_time - job.start_time

            time_from_last_failed_check = current_time - job.last_monitor_check_failed

            if (execution_time > job.monitor_interval
                and time_from_last_failed_check > job.monitor_interval):

                job.last_monitor_check_failed = current_time

                if execution_time < 60:
                    error = "Job %s is taking more than %d seconds to execute" % (job.name, execution_time)
                elif execution_time < 3600:
                    minutes = int(execution_time / 60)
                    error = "Job %s is taking more than %d minutes to execute" % (job.name, minutes)
                else:
                    hours = int(execution_time / 3600)
                    error = "Job %s is taking more than %d hours to execute" % (job.name, hours)
                error_msg += error + '\n'
                log.err(error)

        if error_msg != "":
            schedule_exception_email(error_msg)
