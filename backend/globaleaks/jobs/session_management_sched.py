# -*- coding: UTF-8
# Implement reset of variables related to sessions

from globaleaks.jobs.base import LoopingJob
from globaleaks.settings import GLSettings
from globaleaks.utils.utility import log

__all__ = ['SessionManagementSchedule']


class SessionManagementSchedule(LoopingJob):
    name = "Session Management"
    interval = 60
    monitor_interval = 10

    def operation(self):
        """
        This scheduler is responsible for:
            - Reset of failed login attempts counters
            - Reset the api_token suspension
        """
        GLSettings.failed_login_attempts = 0
        GLSettings.appstate.api_token_session_suspended = False
