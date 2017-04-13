# -*- coding: utf-8 -*-
from twisted.internet.defer import inlineCallbacks

from globaleaks.constants import FIRST_TENANT
from globaleaks.handlers import custodian
from globaleaks.tests import helpers


class TestIdentityAccessRequestInstance(helpers.TestHandlerWithPopulatedDB):
    _handler = custodian.IdentityAccessRequestInstance

    @inlineCallbacks
    def setUp(self):
        yield helpers.TestHandlerWithPopulatedDB.setUp(self)
        yield self.perform_full_submission_actions()

    @inlineCallbacks
    def test_get_new_identityaccessrequest(self):
        iars = yield custodian.get_identityaccessrequest_list(FIRST_TENANT, 'en')

        handler = self.request(user_id = self.dummyCustodianUser['id'], role='custodian')

        yield handler.get(iars[0]['id'])

    @inlineCallbacks
    def test_put_identityaccessrequest_response(self):
        iars = yield custodian.get_identityaccessrequest_list(FIRST_TENANT, 'en')

        handler = self.request(user_id = self.dummyCustodianUser['id'], role='custodian')

        yield handler.get(iars[0]['id'])

        self.responses[0]['response'] = 'authorized'
        self.responses[0]['response_motivation'] = 'oh yeah!'

        handler = self.request(self.responses[0], user_id = self.dummyCustodianUser['id'], role='custodian')
        yield handler.put(iars[0]['id'])

        yield handler.get(iars[0]['id'])


class TestIdentityAccessRequestsCollection(helpers.TestHandlerWithPopulatedDB):
    _handler = custodian.IdentityAccessRequestsCollection

    @inlineCallbacks
    def setUp(self):
        yield helpers.TestHandlerWithPopulatedDB.setUp(self)
        yield self.perform_full_submission_actions()

    @inlineCallbacks
    def test_get(self):
        handler = self.request(user_id=self.dummyCustodianUser['id'], role='custodian')
        yield handler.get()
