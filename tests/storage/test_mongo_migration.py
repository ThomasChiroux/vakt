import json
import re
import unittest

import pytest

from vakt.storage.mongo import *
from vakt.rules.base import Rule
from vakt.guard import Inquiry, Guard
from .test_mongo import DB_NAME, COLLECTION, create_client


@pytest.mark.integration
class TestMigration0To1x0x3:

    @pytest.fixture()
    def migration(self):
        client = create_client()
        storage = MongoStorage(client, DB_NAME, collection=COLLECTION)
        yield Migration0To1x1x0(storage)
        client[DB_NAME][COLLECTION].delete_many({})
        client.close()

    def test_order(self, migration):
        assert 1 == migration.order

    def test_has_access_to_storage(self, migration):
        assert hasattr(migration, 'storage') and migration.storage is not None

    def test_up(self, migration):
        migration.up()
        created_indices = [i['name'] for i in migration.storage.collection.list_indexes()]
        assert created_indices == ['_id_', 'actions_idx', 'subjects_idx', 'resources_idx']

    def test_down(self, migration):
        migration.down()
        left_indices = [i['name'] for i in migration.storage.collection.list_indexes()]
        assert left_indices == ['_id_']


# Custom classes for TestMigration1x1x0To1x1x1
class WithObject(Rule):  # pragma: no cover
    def __init__(self, val):
        self.val = re.compile(val)

    def satisfied(self, what=None, inquiry=None):
        return True


class Simple(Rule):   # pragma: no cover
    def __init__(self, val):
        self.val = val

    def satisfied(self, what=None, inquiry=None):
        return True


@pytest.mark.integration
class TestMigration1x1x0To1x1x1:
    class MockLoggingHandler(logging.Handler):
        def __init__(self, *args, **kwargs):
            self.messages = {}
            super().__init__(*args, **kwargs)

        def emit(self, record):
            level = record.levelname.lower()
            if level not in self.messages:
                self.messages[level] = []
            self.messages[level].append(record.getMessage())

    @pytest.fixture()
    def storage(self):
        client = create_client()
        storage = MongoStorage(client, DB_NAME, collection=COLLECTION)
        yield storage
        client[DB_NAME][COLLECTION].delete_many({})
        client.close()

    def test_order(self, storage):
        migration = Migration1x1x0To1x1x1(storage)
        assert 2 == migration.order

    def test_up(self, storage):
        migration = Migration1x1x0To1x1x1(storage)
        # prepare docs that might have been saved by users in v 1.1.0
        docs = [
            (
                """
                { "_id" : 10, "uid" : 10, "description" : null, "subjects" : [ ], "effect" : "allow", 
                "resources" : [ ], "actions" : [ ], "rules" : { "secret" : 
                "{\\"type\\": \\"vakt.rules.string.StringEqualRule\\", \\"contents\\": {\\"val\\": \\"i-am-a-foo\\"}}", 
                "name":"{\\"type\\": \\"vakt.rules.string.StringEqualRule\\", \\"contents\\":{\\"val\\": \\"Max\\"}}" }}
                """,
                """
                { "_id" : 10, "actions" : [ ], "description" : null, "effect" : "allow", "resources" : [ ], 
                "rules" : { "name" : {"py/object": "vakt.rules.string.StringEqualRule", "val": "Max" },
                "secret" : {"py/object": "vakt.rules.string.StringEqualRule", "val": "i-am-a-foo"} }, 
                "subjects" : [ ], "uid" : 10 }
                """
            ),
            (
                """
                { "_id" : 20, "uid" : 20, "description" : "foo bar", "subjects" : [ "<.*>" ], "effect" : "allow",
                "resources" : [ "<.*>" ], "actions" : [ "<.*>" ], "rules" : { "secret" :
                "{\\"type\\": \\"vakt.rules.string.StringEqualRule\\", \\"contents\\": {\\"val\\": \\"John\\"}}" } }
                """,
                """
                { "_id" : 20, "actions" : [ "<.*>" ], "description" : "foo bar", "effect" : "allow",
                "resources" : [ "<.*>" ], "rules" : { "secret" :
                { "py/object": "vakt.rules.string.StringEqualRule", "val": "John"} }, "subjects" : [ "<.*>" ],
                "uid" : 20 }
                """
            ),
            (
                """
                { "_id" : 30, "uid" : 30, "description" : "foo bar", "subjects" : [ "<.*>" ], "effect" : "allow",
                "resources" : [ "<.*>" ], "actions" : [ "<.*>" ], "rules" : {  } }
                """,
                """
                { "_id" : 30, "actions" : [ "<.*>" ], "description" : "foo bar", "effect" : "allow",
                "resources" : [ "<.*>" ], "rules" : {  }, "subjects" : [ "<.*>" ], "uid" : 30 }
                """
            ),
            (
                """
                { "_id" : 40, "uid" : 40, "description" : null, "subjects" : [ "<.*>" ], "effect" : "allow", 
                "resources" : [ "<.*>" ], "actions" : [ "<.*>" ], "rules" : 
                { "num" : 
                "{\\"type\\": \\"storage.test_mongo_migration.Simple\\", \\"contents\\": {\\"val\\": \\"123\\"}}", 
                "a" : "{\\"type\\": \\"vakt.rules.string.StringEqualRule\\", \\"contents\\": {\\"val\\": \\"foo\\"}}" }}
                """,
                """
                { "_id" : 40, "actions" : [ "<.*>" ], "description" : null, "effect" : "allow",  "resources" : ["<.*>"],
                "rules" : { "a" : {"py/object": "vakt.rules.string.StringEqualRule", "val": "foo"},
                "num" : { "py/object": "storage.test_mongo_migration.Simple", "val": "123"} }, "subjects" : ["<.*>"],
                "uid" : 40 }
                """
            ),
            (
                """
                { "_id" : 50, "uid" : 50, "description" : null, "subjects" : [ ], "effect" : "allow", "resources" : [ ], 
                "actions" : [ ], "rules" : { "num" : 
                "{\\"type\\": \\"storage.test_mongo_migration.Simple\\", \\"contents\\": {\\"val\\": \\"46\\"}}" } }
                """,
                """
                { "_id" : 50, "actions" : [ ], "description" : null, "effect" : "allow", "resources" : [ ],
                "rules" : { "num" : { "py/object": "storage.test_mongo_migration.Simple", "val": "46"} },
                "subjects" : [ ], "uid" : 50 }
                """
            ),
        ]
        for (doc, _) in docs:
            d = b_json.loads(doc)
            migration.storage.collection.insert_one(d)

        migration.up()

        # test no new docs were added and no docs deleted
        assert len(docs) == len(list(migration.storage.collection.find({})))
        # test Policy.from_json() is called without errors for each doc (implicitly)
        assert len(docs) == len(list(migration.storage.get_all(1000, 0)))
        # test string contents of each doc
        for (doc, result_doc) in docs:
            new_doc = migration.storage.collection.find_one({'uid': json.loads(doc)['uid']})
            expected = result_doc.replace("\n", '').replace(' ', '')
            actual = json.dumps(new_doc, sort_keys=True).replace("\n", '').replace(' ', '')
            assert expected == actual
        # test full guard allowance run
        g = Guard(migration.storage, RegexChecker())
        inq = Inquiry(action='foo', resource='bar', subject='Max', context={'val': 'foo', 'num': '123'})
        assert g.is_allowed(inq)

    def test_down(self, storage):
        assertions = unittest.TestCase('__init__')
        migration = Migration1x1x0To1x1x1(storage)
        # prepare docs that might have been saved by users in v 1.1.1
        docs = [
            (
                """
                {"_id":1,"actions":[],"description":null,"effect":"deny","resources":[],"rules":
                {"name":{"py/object":"vakt.rules.string.RegexMatchRule",
                "regex":{"pattern":"[Mm]ax","py/object":"_sre.SRE_Pattern"}},
                "secret":{"py/object":"vakt.rules.string.StringEqualRule","val":"i-am-a-foo"}},
                "subjects":[],"uid":1}
                """,
                None
            ),
            (
                """
                {"_id":2,"actions":["<.*>"],"description":"foobar","effect":"deny",
                "resources":["<.*>"],"rules":{"secret":{"py/object":"vakt.rules.string.StringEqualRule","val":"John"}},
                "subjects":["<.*>"],"uid":2}
                """,
                """
                {"_id":2,"actions":["<.*>"],"description":"foobar","effect":"deny",
                "resources":["<.*>"],"rules":{"secret":
                "{\\"contents\\": {\\"val\\": \\"John\\"}, \\"type\\": \\"vakt.rules.string.StringEqualRule\\"}"},
                "subjects":["<.*>"],"uid":2}
                """
            ),
            (
                """
                {"_id":3,"actions":["<.*>"],"description":"foobar","effect":"deny",
                "resources":["<.*>"],"rules":{},"subjects":["<.*>"],"uid":3}
                """,
                """
                {"_id":3,"actions":["<.*>"],"description":"foobar","effect":"deny",
                "resources":["<.*>"],"rules":{},"subjects":["<.*>"],"uid":3}
                """
            ),
            (
                """
                {"_id":4,"actions":[],"description":null,"effect":"deny","resources":[],
                "rules":{"digit":{"py/object":"test_storage_mongo.WithObject",
                "val":{"pattern":"\\\\d+","py/object":"_sre.SRE_Pattern"}},
                "num":{"py/object":"storage.test_mongo_migration.Simple","val":"123"}},"subjects":[],"uid":4}
                """,
                None
            ),
            (
                """
                {"_id":5,"actions":[],"description":null,"effect":"deny","resources":[],"rules":
                {"num":{"py/object":"storage.test_mongo_migration.Simple","val":"46"}},"subjects":[],"uid":5}
                """,
                """
                {"_id":5,"actions":[],"description":null,"effect":"deny","resources":[],"rules":
                {"num":
                "{\\"contents\\": {\\"val\\": \\"46\\"}, \\"type\\": \\"storage.test_mongo_migration.Simple\\"}"},
                "subjects":[],"uid":5}
                """
            ),
            (
                """
                {"_id":"6","uid":"6"}
                """,
                None
            ),
        ]
        for (doc, _) in docs:
            d = b_json.loads(doc)
            migration.storage.collection.insert_one(d)

        # set logger for capturing output
        l = logging.getLogger('vakt.storage.mongo')
        log_handler = self.MockLoggingHandler()
        l.setLevel(logging.INFO)
        l.addHandler(log_handler)

        migration.down()

        # test no new docs were added and no docs deleted
        assert len(docs) == len(list(migration.storage.collection.find({})))
        # test Policy.from_json() is called without errors for each doc (implicitly)
        assert len(docs) == len(list(migration.storage.get_all(1000, 0)))
        # test string contents of each doc
        for (doc, expected_doc) in docs:
            if not expected_doc:  # some policies should be left as-is if not converted
                expected_doc = doc
            new_doc = migration.storage.collection.find_one({'uid': json.loads(doc)['uid']})
            assertions.assertDictEqual(json.loads(expected_doc), new_doc)
        # test failed policies report
        # info
        assert 'info' in log_handler.messages
        assert 9 == len(log_handler.messages['info'])
        assert 'Trying to migrate Policy with UID: 5' in log_handler.messages['info']
        assert 'Policy with UID was migrated: 5' in log_handler.messages['info']
        # warn
        assert 'warning' in log_handler.messages
        assert 2 == len(log_handler.messages['warning'])
        assert "Irreversible Policy. vakt.rules.string.RegexMatchRule could not be stored in v1.1.0. Mongo doc:" in \
               log_handler.messages['warning'][0]
        assert "'_id': 1" in log_handler.messages['warning'][0]
        assert "Irreversible Policy. Custom rule class contains non-primitive data {'" in \
               log_handler.messages['warning'][1]
        assert "'_id': 4" in log_handler.messages['warning'][1]
        # error
        assert 'error' in log_handler.messages
        assert 2 == len(log_handler.messages['warning'])
        assert "Unexpected exception occurred while migrating Policy:" in log_handler.messages['error'][0]
        assert "'uid': '6'" in log_handler.messages['error'][0]
        assert 'Migration was unable to convert some Policies, but' in log_handler.messages['error'][1]
        assert 'Mongo IDs of failed Policies are:' in log_handler.messages['error'][1]
        assert "[1, 4, '6']" in log_handler.messages['error'][1]
