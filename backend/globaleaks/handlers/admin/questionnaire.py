# -*- coding: UTF-8
#
#   /admin/questionnaires
#   *****
# Implementation of the code executed on handler /admin/questionnaires
#

from globaleaks import models
from globaleaks.handlers.admin.field import db_import_fields
from globaleaks.handlers.base import BaseHandler
from globaleaks.handlers.public import serialize_step, serialize_questionnaire
from globaleaks.orm import transact
from globaleaks.rest import errors, requests
from globaleaks.utils.structures import fill_localized_keys
from globaleaks.utils.utility import log


def db_get_questionnaire_list(store, language):
    questionnaires = store.find(models.Questionnaire)

    return [serialize_questionnaire(store, questionnaire, language) for questionnaire in questionnaires]


@transact
def get_questionnaire_list(store, language):
    """
    Returns the questionnaire list.

    :param store: the store on which perform queries.
    :param language: the language in which to localize data.
    :return: a dictionary representing the serialization of the questionnaires.
    """
    return db_get_questionnaire_list(store, language)


def db_get_questionnaire(store, questionnaire_id, language):
    """
    Returns:
        (dict) the questionnaire with the specified id.
    """
    questionnaire = store.find(models.Questionnaire, models.Questionnaire.id == questionnaire_id).one()

    if not questionnaire:
        log.err("Requested invalid questionnaire")
        raise errors.QuestionnaireIdNotFound

    return serialize_questionnaire(store, questionnaire, language)


@transact
def get_questionnaire(store, questionnaire_id, language):
    return db_get_questionnaire(store, questionnaire_id, language)


def fill_questionnaire_request(request, language):
    fill_localized_keys(request, models.Questionnaire.localized_keys, language)
    return request


def db_update_questionnaire(store, questionnaire, request, language):
    request = fill_questionnaire_request(request, language)

    questionnaire.update(request)

    return questionnaire


def db_create_questionnaire(store, request, language):
    request = fill_questionnaire_request(request, language)

    steps = request['steps']
    del request['steps']

    questionnaire = models.Questionnaire(request)

    store.add(questionnaire)

    return questionnaire


@transact
def create_questionnaire(store, request, language):
    """
    Creates a new questionnaire from the request of a client.

    We associate to the questionnaire the list of receivers and if the receiver is
    not valid we raise a ReceiverIdNotFound exception.

    Args:
        (dict) the request containing the keys to set on the model.

    Returns:
        (dict) representing the configured questionnaire
    """
    questionnaire = db_create_questionnaire(store, request, language)

    return serialize_questionnaire(store, questionnaire, language)


@transact
def update_questionnaire(store, questionnaire_id, request, language):
    """
    Updates the specified questionnaire. If the key receivers is specified we remove
    the current receivers of the Questionnaire and reset set it to the new specified
    ones.
    If no such questionnaire exists raises :class:`globaleaks.errors.QuestionnaireIdNotFound`.

    Args:
        questionnaire_id:

        request:
            (dict) the request to use to set the attributes of the Questionnaire

    Returns:
            (dict) the serialized object updated
    """
    questionnaire = store.find(models.Questionnaire, models.Questionnaire.id == questionnaire_id).one()
    if not questionnaire:
        raise errors.QuestionnaireIdNotFound

    questionnaire = db_update_questionnaire(store, questionnaire, request, language)

    return serialize_questionnaire(store, questionnaire, language)


@transact
def delete_questionnaire(store, questionnaire_id):
    """
    Deletes the specified questionnaire. If no such questionnaire exists raises
    :class:`globaleaks.errors.QuestionnaireIdNotFound`.

    Args:
        questionnaire_id: the questionnaire id of the questionnaire to remove.
    """
    questionnaire = store.find(models.Questionnaire, models.Questionnaire.id == questionnaire_id).one()
    if not questionnaire:
        log.err("Invalid questionnaire requested in removal")
        raise errors.QuestionnaireIdNotFound

    store.remove(questionnaire)


class QuestionnairesCollection(BaseHandler):
    check_roles = 'admin'
    cache_resource = True
    invalidate_cache = True

    def get(self):
        """
        Return all the questionnaires.

        Parameters: None
        Response: adminQuestionnaireList
        Errors: None
        """
        return get_questionnaire_list(self.request.language)

    def post(self):
        """
        Create a new questionnaire.

        Request: AdminQuestionnaireDesc
        Response: AdminQuestionnaireDesc
        Errors: InvalidInputFormat, ReceiverIdNotFound
        """
        validator = requests.AdminQuestionnaireDesc if self.request.language is not None else requests.AdminQuestionnaireDescRaw

        request = self.validate_message(self.request.content.read(), validator)

        return create_questionnaire(request, self.request.language)


class QuestionnaireInstance(BaseHandler):
    check_roles = 'admin'
    invalidate_cache = True

    def put(self, questionnaire_id):
        """
        Update the specified questionnaire.

        Parameters: questionnaire_id
        Request: AdminQuestionnaireDesc
        Response: AdminQuestionnaireDesc
        Errors: InvalidInputFormat, QuestionnaireIdNotFound, ReceiverIdNotFound

        Updates the specified questionnaire.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminQuestionnaireDesc)

        return update_questionnaire(questionnaire_id, request, self.request.language)

    def delete(self, questionnaire_id):
        """
        Delete the specified questionnaire.

        Request: AdminQuestionnaireDesc
        Response: None
        Errors: InvalidInputFormat, QuestionnaireIdNotFound
        """
        return delete_questionnaire(questionnaire_id)
