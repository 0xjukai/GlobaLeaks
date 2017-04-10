# -*- coding: UTF-8
# Implementation of the cleaning operations.

import time

from datetime import timedelta

from globaleaks import models
from globaleaks.handlers.admin.context import admin_serialize_context
from globaleaks.handlers.admin.node import db_admin_serialize_node
from globaleaks.handlers.admin.notification import db_get_notification
from globaleaks.handlers.admin.receiver import admin_serialize_receiver
from globaleaks.handlers.rtip import db_delete_itips, serialize_rtip
from globaleaks.jobs.base import GLJob
from globaleaks.orm import transact_sync
from globaleaks.security import overwrite_and_remove
from globaleaks.settings import GLSettings
from globaleaks.utils.templating import Templating
from globaleaks.utils.utility import log, datetime_now, datetime_never, \
    datetime_to_ISO8601


__all__ = ['CleaningSchedule']


def db_clean_expired_wbtips(store, ten_state):
    threshold = datetime_now() - timedelta(days=ten_state.memc.wbtip_timetolive)

    wbtips = store.find(models.WhistleblowerTip, models.WhistleblowerTip.id == models.InternalTip.id,
                                                 models.InternalTip.wb_last_access < threshold)

    for wbtip in wbtips:
        log.info("Disabling WB access to %s" % wbtip.id)
        store.remove(wbtip)


class CleaningSchedule(GLJob):
    name = "Cleaning"
    interval = 24 * 3600
    monitor_interval = 5 * 60

    def get_start_time(self):
         current_time = datetime_now()
         return (3600 * 24) - (current_time.hour * 3600) - (current_time.minute * 60) - current_time.second

    @transact_sync
    def clean_expired_wbtips(self, store, ten_state):
        """
        This function checks all the InternalTips and deletes WhistleblowerTips
        that have not been accessed after `threshold`.
        """
        db_clean_expired_wbtips(store, ten_state)

    @transact_sync
    def clean_expired_itips(self, store):
        """
        This function, checks all the InternalTips and their expiration date.
        if expired InternalTips are found, it removes that along with
        all the related DB entries comment and tip related.
        """
        db_delete_itips(store, store.find(models.InternalTip, models.InternalTip.expiration_date < datetime_now()))

    @transact_sync
    def check_for_expiring_submissions(self, store, ten_state):
        threshold = datetime_now() + timedelta(hours=ten_state.memc.notif.tip_expiration_threshold)
        receivers = store.find(models.Receiver)
        for receiver in receivers:
            rtips = store.find(models.ReceiverTip, models.ReceiverTip.internaltip_id == models.InternalTip.id,
                                                   models.InternalTip.expiration_date < threshold,
                                                   models.ReceiverTip.receiver_id == models.Receiver.id,
                                                   models.Receiver.id == receiver.id)

            if rtips.count() == 0:
              continue

            user = receiver.user
            language = user.language
            node_desc = db_admin_serialize_node(store, language)
            notification_desc = db_get_notification(store, language)

            receiver_desc = admin_serialize_receiver(store, receiver, language)

            if rtips.count() == 1:
                rtip = rtips[0]
                tip_desc = serialize_rtip(store, rtip, user.language)
                context_desc = admin_serialize_context(store, rtip.internaltip.context, language)

                data = {
                   'type': u'tip_expiration',
                   'node': node_desc,
                   'context': context_desc,
                   'receiver': receiver_desc,
                   'notification': notification_desc,
                   'tip': tip_desc
                }

            else:
                tips_desc = []
                earliest_expiration_date = datetime_never()

                for rtip in rtips:
                    if rtip.internaltip.expiration_date < earliest_expiration_date:
                        earliest_expiration_date = rtip.internaltip.expiration_date

                    tips_desc.append(serialize_rtip(store, rtip, user.language))

                data = {
                   'type': u'tip_expiration_summary',
                   'node': node_desc,
                   'notification': notification_desc,
                   'receiver': receiver_desc,
                   'expiring_submission_count': rtips.count(),
                   'earliest_expiration_date': datetime_to_ISO8601(earliest_expiration_date)
                }

            subject, body = Templating().get_mail_subject_and_body(data)

            mail = models.Mail({
               'address': receiver_desc['mail_address'],
               'subject': subject,
               'body': body
            })

            store.add(mail)

    @transact_sync
    def clean_db(self, store):
        # delete stats older than 3 months
        store.find(models.Stats, models.Stats.start < datetime_now() - timedelta(3*(365/12))).remove()

        # delete anomalies older than 1 months
        store.find(models.Anomalies, models.Anomalies.date < datetime_now() - timedelta(365/12)).remove()

    @transact_sync
    def get_files_to_secure_delete(self, store):
        return [file_to_delete.filepath for file_to_delete in store.find(models.SecureFileDelete)]

    @transact_sync
    def commit_file_deletion(self, store, filepath):
        store.find(models.SecureFileDelete, models.SecureFileDelete.filepath == filepath).remove()

    def perform_secure_deletion_of_files(self):
        files_to_delete = self.get_files_to_secure_delete()

        for file_to_delete in files_to_delete:
            self.start_time = time.time()
            log.debug("Starting secure delete of file %s" % file_to_delete)
            overwrite_and_remove(file_to_delete)
            self.commit_file_deletion(file_to_delete)
            current_run_time = time.time() - self.start_time
            log.debug("Ending secure delete of file %s (execution time: %.2f)" % (file_to_delete, current_run_time))

    def operation(self):
        for ten_state in app_state.tenant_states.values():
            self.clean_expired_wbtips(ten_state)

        self.clean_expired_itips()

        for ten_state in app_state.tenant_states.values():
            self.check_for_expiring_submissions(ten_state)

        self.clean_db()

        self.perform_secure_deletion_of_files()
