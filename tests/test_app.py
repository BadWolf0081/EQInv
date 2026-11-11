import io
import json
import unittest
from unittest.mock import patch

from app import app
from inventory import parse_inventory
from test_inventory import EXPORT


class Cursor:
    def __init__(self, state):
        self.state = state
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, values=None):
        if query.startswith("INSERT INTO uploads"):
            self.state["uploads"].append({"id": len(self.state["uploads"]) + 1,
                                          "filename": values[0], "character_name": values[1],
                                          "server_name": values[2], "raw_text": values[3],
                                          "rows_json": values[4], "uploaded_at": "2026-01-01"})
        elif query.startswith("SELECT id, filename"):
            if values is not None:
                match = next((upload for upload in self.state["uploads"] if upload["id"] == values[0]), None)
            else:
                match = self.state["uploads"][-1] if self.state["uploads"] else None
            self.result = match.copy() if match else None
        elif query.startswith("SELECT item_id"):
            self.result = list(self.state["items"].values())
        else:
            raise AssertionError(query)

    def executemany(self, query, values):
        if query.startswith("INSERT INTO item_data"):
            for item_id, types, stats in values:
                self.state["items"][item_id] = {"item_id": item_id, "aug_types_json": types, "stats_json": stats}
        elif query.startswith("INSERT INTO items"):
            for item_id, name in values:
                self.state["catalog"].setdefault(item_id, name)
        else:
            raise AssertionError(query)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class Connection:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return Cursor(self.state)

    def commit(self):
        self.state["commits"] += 1


class AppTests(unittest.TestCase):
    def setUp(self):
        self.state = {"uploads": [], "items": {}, "catalog": {}, "commits": 0}
        self.patcher = patch("app.connect", side_effect=lambda: Connection(self.state))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.token = session["csrf_token"]

    def test_upload_and_item_enrichment(self):
        response = self.client.post("/upload", data={"csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"First earring", response.data)
        self.assertIn(b"Second earring", response.data)
        self.assertIn(b"2 equipped augment(s) have unknown types", response.data)
        self.assertEqual(self.state["uploads"][0]["raw_text"], EXPORT.decode())
        csv = b"id,aug_types,ac,hp\n11,7,40,120\n12,8,10,200\n"
        response = self.client.post("/item-data", data={"csrf_token": self.token, "items": (io.BytesIO(csv), "items.csv")}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Imported item data for 2 items", response.data)
        self.assertIn(b"0 equipped augment(s) have unknown types", response.data)
        table = response.data.split(b'<tbody>')[1].split(b'</tbody>')[0]
        self.assertLess(table.index(b"Second aug"), table.index(b"First aug"))
        self.assertIn(b"Ear 2", table)
        self.assertEqual(self.state["commits"], 2)

    def test_rejects_malformed_upload_without_database_write(self):
        response = self.client.post("/upload", data={"csrf_token": self.token, "inventory": (io.BytesIO(b"invalid"), "bad.txt")},
                                    follow_redirects=True)
        self.assertIn(b"Expected the EverQuest inventory header", response.data)
        self.assertEqual(self.state["uploads"], [])
        self.assertEqual(self.state["commits"], 0)

    def test_unknown_ac_not_ranked_as_zero(self):
        parsed = parse_inventory(EXPORT, "Example_Test-Inventory.txt")
        self.state["uploads"].append({"id": 1, "filename": parsed["filename"], "character_name": parsed["character"],
                                      "server_name": parsed["server"], "uploaded_at": "2026-01-01",
                                      "rows_json": json.dumps(parsed["rows"])})
        csv = b"id,aug_types,ac\n11,7,\n12,8,0\n"
        response = self.client.post("/item-data", data={"csrf_token": self.token, "items": (io.BytesIO(csv), "items.csv")}, follow_redirects=True)
        table = response.data.split(b'<tbody>')[1].split(b'</tbody>')[0]
        self.assertLess(table.index(b"Second aug"), table.index(b"First aug"))
        self.assertIn(b"Unknown", table)

    def test_database_failure_is_visible(self):
        with patch("app.connect", side_effect=OSError("database unavailable")):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Cannot connect to the database", response.data)

    def test_post_requires_form_token(self):
        response = self.client.post("/upload", data={"inventory": (io.BytesIO(EXPORT), "example.txt")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.state["uploads"], [])

    def test_multiple_uploads_are_retained(self):
        for name in ("First_Server-Inventory.txt", "Second_Server-Inventory.txt"):
            response = self.client.post("/upload", data={
                "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), name)
            }, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.state["uploads"]), 2)
        self.assertIn(b"Second", response.data)
        self.assertEqual(self.state["uploads"][0]["raw_text"], EXPORT.decode())

    def test_catalog_collects_unique_items_and_preserves_metadata(self):
        csv = b"id,aug_types,ac\n11,7,40\n"
        self.client.post("/item-data", data={"csrf_token": self.token, "items": (io.BytesIO(csv), "items.csv")})
        for contents in (EXPORT, EXPORT.replace(b"First aug", b"Renamed aug")):
            response = self.client.post("/upload", data={
                "csrf_token": self.token, "inventory": (io.BytesIO(contents), "Test_Server-Inventory.txt")
            })
            self.assertEqual(response.status_code, 302)
        self.assertEqual(self.state["catalog"], {
            1: "First earring", 11: "First aug", 2: "Second earring", 12: "Second aug",
            3: "Bag", 4: "Nested item", 13: "Nested aug", 42: "A mount",
        })
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"])["ac"], 40)

    def test_item_details_show_stats_types_and_correct_children(self):
        response = self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        }, follow_redirects=True)
        self.assertIn(b'/uploads/1/items/0', response.data)
        self.assertIn(b'/uploads/1/items/1', response.data)
        self.assertIn(b'/uploads/1/items/7', response.data)
        csv = b"id,aug_types,ac,hp,heroic_int\n1,,50,500,20\n11,7|8,42,100,12\n12,8,,0,\n"
        self.client.post("/item-data", data={"csrf_token": self.token, "items": (io.BytesIO(csv), "items.csv")})
        response = self.client.get("/uploads/1/items/0")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"First earring", response.data)
        self.assertIn(b"First aug", response.data)
        self.assertNotIn(b"Second aug", response.data)
        self.assertIn(b"7 / 8", response.data)
        self.assertIn(b"HEROIC INT", response.data)
        self.assertIn(b">42<", response.data)
        self.assertIn(b'/uploads/1/items/1', response.data)
        response = self.client.get("/uploads/1/items/3")
        self.assertIn(b"Second aug", response.data)
        self.assertIn(b"Second earring", response.data)
        self.assertIn(b">Unknown<", response.data)
        self.assertIn(b">0<", response.data)
        response = self.client.get("/uploads/1/items/4")
        self.assertIn(b"Nested item", response.data)
        self.assertNotIn(b"Nested aug", response.data)
        self.assertIn(b"Not imported", response.data)
        response = self.client.get("/uploads/1/items/7")
        self.assertIn(b"Keyring", response.data)
        self.assertIn(b"A mount", response.data)

    def test_item_links_keep_upload_identity_and_validate_indices(self):
        for contents in (EXPORT, EXPORT.replace(b"First earring", b"New earring")):
            self.client.post("/upload", data={
                "csrf_token": self.token, "inventory": (io.BytesIO(contents), "Example_Test-Inventory.txt")
            })
        self.assertIn(b"First earring", self.client.get("/uploads/1/items/0").data)
        self.assertIn(b"New earring", self.client.get("/uploads/2/items/0").data)
        self.assertEqual(self.client.get("/uploads/1/items/9999").status_code, 404)
        self.assertEqual(self.client.get("/uploads/999/items/0").status_code, 404)
        with patch("app.connect", side_effect=OSError("database unavailable")):
            self.assertEqual(self.client.get("/uploads/1/items/0").status_code, 503)

    def test_empty_slots_are_not_clickable(self):
        data = b"Location\tName\tID\tCount\tSlots\nEar\tEarring\t1\t1\t6\nEar-Slot1\tEmpty\t0\t0\t0\n"
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(data), "Example_Test-Inventory.txt")
        })
        response = self.client.get("/uploads/1/items/0")
        self.assertIn(b"Empty", response.data)
        self.assertNotIn(b'/uploads/1/items/1', response.data)
        self.assertEqual(self.client.get("/uploads/1/items/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
