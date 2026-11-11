import copy
import io
import unittest
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

import profiles


EXPORT = b"Location\tName\tID\tCount\tSlots\nHead\tHelm\t1\t1\t0\n"


class Cursor:
    def __init__(self, state):
        self.state = state
        self.result = None
        self.lastrowid = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, values=None):
        if query.startswith("INSERT INTO discord_accounts"):
            self.state["accounts"].add(values[0])
        elif query.startswith("SELECT discord_id FROM discord_accounts"):
            self.result = {"discord_id": values[0]}
        elif query.startswith("SELECT identity_hash FROM character_profiles WHERE discord_id = %s AND"):
            self.result = {"identity_hash": values[1]} if (values[0], values[1]) in self.state["profiles"] else None
        elif query.startswith("SELECT COUNT(*) AS count"):
            self.result = {"count": sum(user == values[0] for user, _ in self.state["profiles"])}
        elif query.startswith("INSERT INTO uploads"):
            self.lastrowid = len(self.state["uploads"]) + 1
            self.state["uploads"].append({"id": self.lastrowid, "character_name": values[1], "server_name": values[2]})
        elif query.startswith("INSERT INTO upload_owners"):
            self.state["owners"][values[0]] = values[1]
        elif query.startswith("INSERT INTO character_profiles"):
            user, key, character, server, upload = values
            self.state["profiles"][(user, key)] = {"character_name": character, "server_name": server, "upload_id": upload}
        elif query.startswith("SELECT upload_id FROM upload_owners"):
            self.result = {"upload_id": values[1]} if self.state["owners"].get(values[1]) == values[0] else None
        elif query.startswith("SELECT character_name, server_name, upload_id FROM character_profiles"):
            self.result = [row for (user, key), row in self.state["profiles"].items() if user == values[0]]
        elif query.startswith("SELECT identity_hash FROM character_profiles WHERE discord_id"):
            self.result = [{"identity_hash": key} for user, key in self.state["profiles"] if user == values[0]]
        elif query.startswith("SELECT u.id, u.character_name"):
            self.result = [row for row in self.state["uploads"] if row["id"] not in self.state["owners"]]
        else:
            raise AssertionError(query)

    def executemany(self, query, values):
        if not query.startswith("INSERT INTO items"):
            raise AssertionError(query)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class Connection:
    def __init__(self, state):
        self.original = state
        self.state = copy.deepcopy(state)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return Cursor(self.state)

    def commit(self):
        self.original.clear()
        self.original.update(self.state)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.state = {"accounts": set(), "uploads": [], "owners": {}, "profiles": {}}
        patcher = patch("profiles.connect", side_effect=lambda: Connection(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, name, user="1"):
        return profiles.save_profile(FileStorage(stream=io.BytesIO(EXPORT), filename=name), user)

    def test_limit_replacement_identity_and_user_isolation(self):
        first = self.upload("Hero_Server-Inventory.txt")
        for i in range(9):
            self.upload(f"Toon{i}_Server-Inventory.txt")
        with self.assertRaisesRegex(ValueError, "10 character profiles"):
            self.upload("Extra_Server-Inventory.txt")
        self.assertEqual(len(self.state["uploads"]), 10)
        latest = self.upload("hero_server-Inventory.txt")
        self.assertEqual(len(profiles.list_profiles("1")), 10)
        self.assertNotEqual(first, latest)
        self.assertTrue(profiles.owns_upload("1", first))
        self.assertFalse(profiles.owns_upload("2", first))
        other = self.upload("Hero_Server-Inventory.txt", "2")
        self.assertTrue(profiles.owns_upload("2", other))
        self.assertEqual(len(profiles.list_profiles("2")), 1)
        self.assertNotEqual(profiles.identity_key("Hero", "A"), profiles.identity_key("Hero", "B"))
        with self.assertRaises(ValueError):
            self.upload("unknown.txt")

    def test_claim_legacy_preserves_latest_and_fails_atomically(self):
        self.state["uploads"] = [
            {"id": 1, "character_name": "Hero", "server_name": "Test"},
            {"id": 2, "character_name": "hero", "server_name": "test"},
        ]
        self.assertEqual(profiles.claim_legacy("1"), (2, 1))
        self.assertEqual(profiles.list_profiles("1")[0]["upload_id"], 2)
        self.assertTrue(profiles.owns_upload("1", 1))
        self.state["uploads"].append({"id": 3, "character_name": None, "server_name": None})
        with self.assertRaises(ValueError):
            profiles.claim_legacy("2")
        self.assertNotIn(3, self.state["owners"])

    def test_claim_rejects_conflict_and_limit_without_assigning(self):
        self.upload("Hero_Test-Inventory.txt")
        self.state["uploads"].append({"id": 2, "character_name": "hero", "server_name": "test"})
        with self.assertRaisesRegex(ValueError, "conflict"):
            profiles.claim_legacy("1")
        self.assertNotIn(2, self.state["owners"])
        self.state["uploads"][-1] = {"id": 2, "character_name": "Extra", "server_name": "test"}
        for i in range(9):
            self.upload(f"Toon{i}_Test-Inventory.txt")
        with self.assertRaisesRegex(ValueError, "exceed"):
            profiles.claim_legacy("1")
        self.assertNotIn(2, self.state["owners"])


if __name__ == "__main__":
    unittest.main()
