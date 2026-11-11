import json
import unittest

from db import catalog_items, initialize


class Cursor:
    def __init__(self, state):
        self.state = state
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, values=None):
        if query.lstrip().startswith("CREATE TABLE"):
            return
        if query.startswith("SELECT id, rows_json"):
            self.result = [row for row in self.state["uploads"] if row["id"] > values[0]][:50]
            return
        raise AssertionError(query)

    def executemany(self, query, values):
        if not query.startswith("INSERT INTO items"):
            raise AssertionError(query)
        for item_id, name in values:
            self.state["items"].setdefault(item_id, name)

    def fetchall(self):
        return self.result


class Connection:
    def __init__(self, uploads):
        self.state = {"uploads": uploads, "items": {}, "commits": 0}

    def cursor(self):
        return Cursor(self.state)

    def commit(self):
        self.state["commits"] += 1


class CatalogTests(unittest.TestCase):
    def test_backfills_all_batches_in_order_and_is_idempotent(self):
        uploads = [
            {"id": number, "rows_json": json.dumps([
                {"item_id": 1, "name": f"Name {number}"},
                {"item_id": number + 10, "name": f"Item {number}"},
                {"item_id": 0, "name": "Empty"},
            ])}
            for number in range(1, 53)
        ]
        connection = Connection(uploads)
        initialize(connection)
        self.assertEqual(len(connection.state["items"]), 53)
        self.assertEqual(connection.state["items"][1], "Name 1")
        self.assertNotIn(0, connection.state["items"])
        initialize(connection)
        self.assertEqual(len(connection.state["items"]), 53)
        self.assertEqual(connection.state["items"][1], "Name 1")

    def test_invalid_prior_upload_does_not_commit_backfill(self):
        connection = Connection([{"id": 1, "rows_json": "invalid json"}])
        with self.assertRaises(ValueError):
            initialize(connection)
        self.assertEqual(connection.state["commits"], 0)

    def test_empty_slots_only_need_no_insert(self):
        connection = Connection([])
        catalog_items(connection.cursor(), [{"item_id": 0, "name": "Empty"}])
        self.assertEqual(connection.state["items"], {})
