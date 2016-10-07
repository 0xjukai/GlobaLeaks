# -*- coding: UTF-8
#
# submission
# **********
#
# Implements a GlobaLeaks submission, then the operations performed
#   by an HTTP client in /submission URI

import copy
import json
import os

from storm.expr import And, In

from twisted.internet import defer

from globaleaks import models
from globaleaks.orm import transact, transact_ro
from globaleaks.handlers.base import BaseHandler
from globaleaks.handlers.admin.context import db_get_context_steps
from globaleaks.utils.token import TokenList
from globaleaks.rest import errors, requests
from globaleaks.security import sha256
from globaleaks.settings import GLSettings
from globaleaks.utils.structures import Rosetta, get_localized_values
from globaleaks.utils.utility import log, utc_future_date, datetime_now, \
    datetime_to_ISO8601, ISO8601_to_datetime, read_file


def get_submission_sequence_number(itip):
    return "%s-%d" % (itip.creation_date.strftime("%Y%m%d"), itip.progressive)


def db_assign_submission_progressive(store):
    counter = store.find(models.Counter, models.Counter.key == u'submission_sequence').one()
    if not counter:
        counter = models.Counter({'key': u'submission_sequence'})
        store.add(counter)
    else:
        now = datetime_now()
        update = counter.update_date
        if ((now > counter.update_date) and (not((now.year == update.year) and
                                                     (now.month == update.month) and
                                                     (now.day == update.day)))):
            counter.counter = 1
        else:
            counter.counter += 1

        counter.update_date = now

    return counter.counter


def _db_get_archived_field_recursively(field, language):
    for key, value in field.get('attrs', {}).iteritems():
        if key not in field['attrs']: continue
        if 'type' not in field['attrs'][key]: continue

        if field['attrs'][key]['type'] == u'localized':
            if language in field['attrs'][key].get('value', []):
                field['attrs'][key]['value'] = field['attrs'][key]['value'][language]
            else:
                field['attrs'][key]['value'] = ""

    for o in field.get('options', []):
        get_localized_values(o, o, models.FieldOption.localized_keys, language)

    for c in field.get('children', []):
        _db_get_archived_field_recursively(c, language)

    return get_localized_values(field, field, models.Field.localized_keys, language)


def _db_get_archived_questionnaire_schema(store, hash, type, language):
    aqs = store.find(models.ArchivedSchema,
                     models.ArchivedSchema.hash == hash,
                     models.ArchivedSchema.type == type).one()

    if not aqs:
        log.err("Unable to find questionnaire schema with hash %s" % hash)
        questionnaire = []
    else:
        questionnaire = copy.deepcopy(aqs.schema)

    if type == 'questionnaire':
        for step in questionnaire:
            for field in step['children']:
                _db_get_archived_field_recursively(field, language)

            get_localized_values(step, step, models.Step.localized_keys, language)

    elif type == 'preview':
        for field in questionnaire:
            _db_get_archived_field_recursively(field, language)

    return questionnaire


def db_get_archived_questionnaire_schema(store, hash, language):
    return _db_get_archived_questionnaire_schema(store, hash, u'questionnaire', language)


def db_get_archived_preview_schema(store, hash, language):
    return _db_get_archived_questionnaire_schema(store, hash, u'preview', language)


def db_serialize_questionnaire_answers_recursively(answers):
    ret = {}

    for answer in answers:
        if answer.is_leaf:
            ret[answer.key] = answer.value
        else:
            ret[answer.key] = [db_serialize_questionnaire_answers_recursively(group.fieldanswers)
                               for group in answer.groups.order_by(models.FieldAnswerGroup.number)]
    return ret


def db_serialize_questionnaire_answers(store, tip):
    if isinstance(tip, models.InternalTip):
        internaltip = tip
    else:
        internaltip = tip.internaltip

    questionnaire = db_get_archived_questionnaire_schema(store, internaltip.questionnaire_hash, GLSettings.memory_copy.default_language)

    answers_ids = []
    filtered_answers_ids = []
    for s in questionnaire:
        for f in s['children']:
            if 'key' in f and f['key'] == 'whistleblower_identity':
                if isinstance(tip, models.InternalTip) or \
                   f['attrs']['visibility_subject_to_authorization']['value'] == False or \
                   (isinstance(tip, models.ReceiverTip) and tip.can_access_whistleblower_identity):
                    answers_ids.append(f['id'])
                else:
                    filtered_answers_ids.append(f['id'])
            else:
                answers_ids.append(f['id'])

    answers = store.find(models.FieldAnswer, And(models.FieldAnswer.internaltip_id == internaltip.id,
                                                 In(models.FieldAnswer.key, answers_ids)))

    return db_serialize_questionnaire_answers_recursively(answers)


def db_save_questionnaire_answers(store, internaltip_id, entries):
    ret = []

    for key, value in entries.iteritems():
        field_answer = models.FieldAnswer({
            'internaltip_id': internaltip_id,
            'key': key
        })
        store.add(field_answer)
        if isinstance(value, list):
            field_answer.is_leaf = False
            field_answer.value = ""
            n = 0
            for entries in value:
                group = models.FieldAnswerGroup({
                  'fieldanswer_id': field_answer.id,
                  'number': n
                })
                store.add(group)
                group_elems = db_save_questionnaire_answers(store, internaltip_id, entries)
                for group_elem in group_elems:
                    group.fieldanswers.add(group_elem)
                n += 1
        else:
            field_answer.is_leaf = True
            field_answer.value = unicode(value)
        ret.append(field_answer)

    return ret


def extract_answers_preview(questionnaire, answers):
    preview = {}

    preview.update({f['id']: copy.deepcopy(answers[f['id']])
    for s in questionnaire for f in s['children'] if f['preview'] and f['id'] in answers})

    return preview


def db_archive_questionnaire_schema(store, questionnaire, questionnaire_hash):
    if store.find(models.ArchivedSchema, 
                  models.ArchivedSchema.hash == questionnaire_hash).count() <= 0:

        aqs = models.ArchivedSchema()
        aqs.hash = questionnaire_hash
        aqs.type = u'questionnaire'
        aqs.schema = questionnaire
        store.add(aqs)

        aqsp = models.ArchivedSchema()
        aqsp.hash = questionnaire_hash
        aqsp.type = u'preview'
        aqsp.schema = [f for s in aqs.schema for f in s['children'] if f['preview']]
        store.add(aqsp)


def serialize_internaltip(store, internaltip, language):
    context = internaltip.context
    mo = Rosetta(context.localized_keys)
    mo.acquire_storm_object(context)

    return {
        'id': internaltip.id,
        'creation_date': datetime_to_ISO8601(internaltip.creation_date),
        'update_date': datetime_to_ISO8601(internaltip.update_date),
        'expiration_date': datetime_to_ISO8601(internaltip.expiration_date),
        'progressive': internaltip.progressive,
        'sequence_number': get_submission_sequence_number(internaltip),
        'context_id': internaltip.context_id,
        'context_name': mo.dump_localized_key('name', language),
        'questionnaire': db_get_archived_questionnaire_schema(store, internaltip.questionnaire_hash, language),
        'tor2web': internaltip.tor2web,
        'timetolive': context.tip_timetolive,
        'enable_comments': context.enable_comments,
        'enable_messages': context.enable_messages,
        'enable_two_way_comments': internaltip.enable_two_way_comments,
        'enable_two_way_messages': internaltip.enable_two_way_messages,
        'enable_attachments': internaltip.enable_attachments,
        'enable_whistleblower_identity': internaltip.enable_whistleblower_identity,
        'identity_provided': internaltip.identity_provided,
        'identity_provided_date': datetime_to_ISO8601(internaltip.identity_provided_date),
        'show_recipients_details': context.show_recipients_details,
        'status_page_message': mo.dump_localized_key('status_page_message', language),
        'total_score': internaltip.total_score,
        'answers': db_serialize_questionnaire_answers(store, internaltip),
        'encrypted_answers': internaltip.encrypted_answers,
        'encrypted': internaltip.encrypted,
        'wb_cckey_pub': internaltip.wb_cckey_pub,
        'wb_last_access': datetime_to_ISO8601(internaltip.wb_last_access),
        'wb_access_counter': internaltip.wb_access_counter
    }


def serialize_internalfile(ifile):
    ifile_dict = {
        'id': ifile.id,
        'creation_date': datetime_to_ISO8601(ifile.internaltip.creation_date),
        'internaltip_id': ifile.internaltip_id,
        'name': ifile.name,
        'file_path': ifile.file_path,
        'content_type': ifile.content_type,
        'size': ifile.size,
    }

    return ifile_dict


def serialize_receiverfile(rfile):
    return {
        'id' : rfile.id,
        'creation_date': datetime_to_ISO8601(rfile.internalfile.creation_date),
        'internaltip_id': rfile.internalfile.internaltip_id,
        'internalfile_id': rfile.internalfile_id,
        'receivertip_id': rfile.receivertip_id,
        'name': rfile.internalfile.name,
        'file_path': rfile.file_path,
        'content_type': rfile.internalfile.content_type,
        'size': rfile.internalfile.size,
        'downloads': rfile.downloads,
        'last_access': datetime_to_ISO8601(rfile.last_access),
        'status': rfile.status,
        'href': "/rtip/" + rfile.receivertip_id + "/download/" + rfile.id
    }


def serialize_whistleblowertip(store, wbtip, language):
    itip = wbtip.internaltip

    ret = serialize_internaltip(store, itip, language)

    ret['files'] = [serialize_internalfile(internalfile) for internalfile in itip.internalfiles]

    ret['wb_cckey_prv_penc'] = wbtip.wb_cckey_prv_penc

    return ret


def serialize_receivertip(store, rtip, language):
    ret = serialize_internaltip(store, rtip.internaltip, language)

    ret['files'] = db_get_rtip_files(store, rtip.receiver_id, rtip.id)

    ret['id'] = rtip.id
    ret['label'] = rtip.label
    ret['last_access'] = datetime_to_ISO8601(rtip.last_access)
    ret['access_counter'] = rtip.access_counter
    ret['enable_notifications'] = rtip.enable_notifications

    return ret


def db_get_rtip(store, user_id, rtip_id):
    rtip = store.find(models.ReceiverTip, models.ReceiverTip.id == unicode(rtip_id),
                      models.ReceiverTip.receiver_id == user_id).one()

    if not rtip:
        raise errors.TipIdNotFound

    return rtip


@transact
def get_rtip(store, user_id, rtip_id, language):
    rtip = db_get_rtip(store, user_id, rtip_id)

    # increment receiver access count
    rtip.access_counter += 1
    rtip.last_access = datetime_now()

    log.debug("Tip %s access granted to user %s (%d)" %
              (rtip.id, rtip.receiver.user.name, rtip.access_counter))

    return serialize_receivertip(store, rtip, language)


def db_get_rtip_files(store, user_id, rtip_id):
    rtip = db_get_rtip(store, user_id, rtip_id)

    receiver_files = store.find(models.ReceiverFile,
                                models.ReceiverFile.receivertip_id == rtip.id)

    return [serialize_receiverfile(receiverfile)
            for receiverfile in receiver_files]


@transact_ro
def get_rtip_files(store, user_id, rtip_id):
    return db_get_rtip_files(store, user_id, rtip_id)


def db_create_receivertip(store, receiver, internaltip):
    """
    Create models.ReceiverTip for the required tier of models.Receiver.
    """
    log.debug('Creating receivertip for receiver: %s' % receiver.id)

    receivertip = models.ReceiverTip()
    receivertip.internaltip_id = internaltip.id
    receivertip.receiver_id = receiver.id

    store.add(receivertip)

    return receivertip


def create_receivertips(store, submission, receiver_id_list):
    rtips_count = 0

    context = submission.context

    if context.maximum_selectable_receivers and \
                    len(receiver_id_list) > context.maximum_selectable_receivers:
        raise errors.SubmissionValidationFailure("Submission failure: provided an invalid number of receivers")

    for receiver in store.find(models.Receiver, In(models.Receiver.id, receiver_id_list)):
        if context not in receiver.contexts:
            continue

        if receiver.user.cckey_pub == "":
            continue

        rtip = db_create_receivertip(store, receiver, submission)

        log.debug("Created ReceiverTip %s for tip %s" % \
                  (rtip.id, submission.id))

        rtips_count += 1

    if rtips_count == 0:
        raise errors.SubmissionValidationFailure("Submission failure: required at least one receiver")

    return rtips_count


def db_create_submission(store, token_id, request, t2w, language):
    # the .get method raise an exception if the token is invalid
    token = TokenList.get(token_id)

    token.use()

    answers = request['answers']

    context = store.find(models.Context, models.Context.id == request['context_id']).one()
    if not context:
        raise errors.ContextIdNotFound

    submission = models.InternalTip()

    # TODO validate if the reponse is a valid openpgp message.
    submission.encrypted_answers = request['encrypted_answers']

    submission.progressive = db_assign_submission_progressive(store)

    submission.expiration_date = utc_future_date(days=context.tip_timetolive)

    # this is get from the client as it the only possibility possible
    # that would fit with the end to end submission.
    # the score is only an indicator and not a critical information so we can accept to
    # be fooled by the malicious user.
    submission.total_score = request['total_score']

    # The use of Tor2Web is detected by the basehandler and the status forwared  here;
    # The status is used to keep track of the security level adopted by the whistleblower
    submission.tor2web = t2w

    submission.context_id = context.id

    submission.wb_cckey_pub = request['wb_cckey_pub']

    submission.enable_two_way_comments = context.enable_two_way_comments
    submission.enable_two_way_messages = context.enable_two_way_messages
    submission.enable_attachments = context.enable_attachments
    submission.enable_whistleblower_identity = context.questionnaire.enable_whistleblower_identity

    if submission.enable_whistleblower_identity and request['identity_provided']:
        submission.identity_provided = True
        submission.identity_provided_date = datetime_now()

    try:
        questionnaire = db_get_context_steps(store, context.id, None)
        questionnaire_hash = unicode(sha256(json.dumps(questionnaire)))

        submission.questionnaire_hash = questionnaire_hash
        submission.preview = extract_answers_preview(questionnaire, answers)

        store.add(submission)

        db_archive_questionnaire_schema(store, questionnaire, questionnaire_hash)

        db_save_questionnaire_answers(store, submission.id, answers)
    except Exception as excep:
        log.err("Submission create: fields validation fail: %s" % excep)
        raise excep

    for filedesc in token.uploaded_files:
        new_file = models.InternalFile()
        new_file.name = filedesc['filename']
        new_file.description = ""
        new_file.content_type = filedesc['content_type']
        new_file.size = filedesc['body_len']
        new_file.internaltip_id = submission.id
        new_file.submission = filedesc['submission']
        new_file.file_path = filedesc['body_filepath']
        store.add(new_file)

        log.debug("=> file associated %s|%s (%d bytes)" %
                  (new_file.name, new_file.content_type, new_file.size))

    wbtip = models.WhistleblowerTip()
    wbtip.id = submission.id
    wbtip.auth_token_hash = request['auth_token_hash']
    wbtip.wb_cckey_prv_penc = request['wb_cckey_prv_penc']
    store.add(wbtip)

    rtips_count = create_receivertips(store, submission, request['receivers'])

    log.debug("Finalized submission creating %d ReceiverTip(s)" % rtips_count)

    return serialize_whistleblowertip(store, wbtip, language)


@transact
def create_submission(store, token_id, request, t2w, language):
    return db_create_submission(store, token_id, request, t2w, language)


class SubmissionInstance(BaseHandler):
    """
    This is the interface to create, populate and complete a submission.
    """
    @BaseHandler.transport_security_check('whistleblower')
    @BaseHandler.unauthenticated
    @defer.inlineCallbacks
    def put(self, token_id):
        """
        Parameter: token_id
        Request: SubmissionDesc
        Response: SubmissionDesc

        PUT finalize the submission
        """
        request = self.validate_message(self.request.body, requests.SubmissionDesc)

        submission = yield create_submission(token_id, request,
                                             self.check_tor2web(),
                                             self.request.language)
        self.set_status(202)  # Updated, also if submission if effectively created (201)
        self.write(submission)
