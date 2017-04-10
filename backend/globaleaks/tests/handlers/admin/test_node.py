# -*- coding: utf-8 -*-

from twisted.internet.defer import inlineCallbacks

from globaleaks import __version__
from globaleaks.handlers.admin import node
from globaleaks.models.l10n import NodeL10NFactory
from globaleaks.rest.errors import InvalidInputFormat, InvalidModelInput
from globaleaks.tests import helpers

# special guest:
stuff = u"³²¼½¬¼³²"


class TestNodeInstance(helpers.TestHandlerWithPopulatedDB):
    _handler = node.NodeInstance

    @inlineCallbacks
    def test_get(self):
        handler = self.request(role='admin')
        yield handler.get()

        self.assertTrue(self.responses[0]['version'], __version__)

    @inlineCallbacks
    def test_put_update_node(self):
        self.dummyNode['onionservice'] = 'abcdef1234567890.onion'
        self.dummyNode['hostname'] = 'blogleaks.blogspot.com'

        for attrname in NodeL10NFactory.localized_keys:
            self.dummyNode[attrname] = stuff

        handler = self.request(self.dummyNode, role='admin')
        yield handler.put()

        self.assertTrue(isinstance(self.responses[0], dict))
        self.assertTrue(self.responses[0]['version'], __version__)

        for response_key in self.responses[0].keys():
            # some keys are added by GLB, and can't be compared
            if response_key in ['password', 'languages_supported',
                                'version', 'version_db',
                                'configured', 'wizard_done',
                                'receipt_salt', 'languages_enabled',
                                'css', 'favicon', 'homepage', 'logo', 'script']:
                continue

            self.assertEqual(self.responses[0][response_key],
                             self.dummyNode[response_key])

    @inlineCallbacks
    def test_put_update_node_invalid_lang(self):
        self.dummyNode['languages_enabled'] = ["en", "shit"]
        handler = self.request(self.dummyNode, role='admin')

        yield self.assertFailure(handler.put(), InvalidInputFormat)

    @inlineCallbacks
    def test_put_update_node_languages_with_default_not_compatible_with_enabled(self):
        self.dummyNode['languages_enabled'] = ["fr"]
        self.dummyNode['default_language'] = "en"
        handler = self.request(self.dummyNode, role='admin')

        yield self.assertFailure(handler.put(), Exception)

    @inlineCallbacks
    def test_put_update_node_languages_removing_en_adding_fr(self):
        self.dummyNode['languages_enabled'] = ["fr"]
        self.dummyNode['default_language'] = "fr"
        handler = self.request(self.dummyNode, role='admin')

        yield handler.put()

    @inlineCallbacks
    def test_put_update_node_invalid_hidden(self):
        self.dummyNode['onionservice'] = 'invalid'
        self.dummyNode['hostname'] = 'blogleaks.blogspot.com'

        handler = self.request(self.dummyNode, role='admin')

        yield self.assertFailure(handler.put(), InvalidInputFormat)

    @inlineCallbacks
    def test_put_update_node_invalid_public(self):
        self.dummyNode['onionservice'] = 'abcdef1234567890.onion'
        self.dummyNode['hostname'] = '!invalid!'

        handler = self.request(self.dummyNode, role='admin')

        yield self.assertFailure(handler.put(), InvalidInputFormat)

    @inlineCallbacks
    def test_put_update_node_invalid_wbtip_ttl(self):
        self.dummyNode['wbtip_timetolive'] = -10

        handler = self.request(self.dummyNode, role='admin')

        yield self.assertFailure(handler.put(), InvalidModelInput)
