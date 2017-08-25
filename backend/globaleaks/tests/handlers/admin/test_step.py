# -*- coding: utf-8 -*-
import copy

from globaleaks.handlers import admin
from globaleaks.handlers.admin.context import create_context
from globaleaks.handlers.admin.step import create_step
from globaleaks.rest import errors
from globaleaks.tests import helpers
from twisted.internet.defer import inlineCallbacks


class TestStepCollection(helpers.TestHandler):
        _handler = admin.step.StepCollection

        @inlineCallbacks
        def test_post(self):
            """
            Attempt to create a new step via a post request.
            """
            context = yield create_context(copy.deepcopy(self.dummyContext), 'en')
            step = helpers.get_dummy_step()
            step['questionnaire_id'] = context['questionnaire_id']
            handler = self.request(step, role='admin')
            response = yield handler.post()
            self.assertIn('id', response)
            self.assertNotEqual(response.get('questionnaire_id'), None)


class TestStepInstance(helpers.TestHandler):
        _handler = admin.step.StepInstance

        @inlineCallbacks
        def test_put(self):
            """
            Attempt to update a step, changing it presentation order
            """
            context = yield create_context(copy.deepcopy(self.dummyContext), 'en')
            step = helpers.get_dummy_step()
            step['questionnaire_id'] = context['questionnaire_id']
            step = yield create_step(step, 'en')

            step['presentation_order'] = 666

            handler = self.request(step, role='admin')
            response = yield handler.put(step['id'])
            self.assertEqual(step['id'], response['id'])
            self.assertEqual(response['presentation_order'], 666)

        @inlineCallbacks
        def test_delete(self):
            """
            Create a new step, then attempt to delete it.
            """
            context = yield create_context(copy.deepcopy(self.dummyContext), 'en')
            step = helpers.get_dummy_step()
            step['questionnaire_id'] = context['questionnaire_id']
            step = yield create_step(step, 'en')

            handler = self.request(role='admin')
            yield handler.delete(step['id'])
            # second deletion operation should fail
            yield self.assertFailure(handler.delete(step['id']), errors.StepIdNotFound)
