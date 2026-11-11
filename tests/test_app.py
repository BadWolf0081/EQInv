import io
import html
import json
import gzip
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymysql
from PIL import Image

from app import app, dashboard
from inventory import parse_inventory
from test_inventory import EXPORT
from test_icon_detection import item_window


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
        elif query.startswith("SELECT item_id, name FROM lucy_items"):
            self.result = self.state["lucy"].get(values[0])
        elif query.startswith("SELECT id FROM item_screenshots"):
            images = self.state["screenshots"].get(values[0], [])
            self.result = {"id": len(images)} if images else None
        elif query.startswith("SELECT id, image_data FROM item_screenshots"):
            images = self.state["screenshots"].get(values[0], [])
            index = values[1] if len(values) > 1 else len(images)
            self.result = {"id": index, "image_data": images[index - 1]} if 1 <= index <= len(images) else None
        elif query.startswith("SELECT image_data FROM item_screenshots"):
            images = self.state["screenshots"].get(values[0], [])
            index = values[1] if len(values) > 1 else len(images)
            self.result = {"image_data": images[index - 1]} if 1 <= index <= len(images) else None
        elif query.startswith("SELECT item_id FROM item_icons"):
            self.result = [{"item_id": item_id} for item_id in values if item_id in self.state["icons"]]
        elif query.startswith("SELECT DISTINCT item_id FROM item_screenshots"):
            self.result = [{"item_id": item_id} for item_id in values if self.state["screenshots"].get(item_id)]
        elif query.startswith("SELECT image_data FROM item_icons"):
            image = self.state["icons"].get(values[0])
            self.result = {"image_data": image} if image else None
        elif query.startswith("SELECT item_id"):
            self.result = list(self.state["items"].values())
        elif query.startswith("INSERT INTO item_icons"):
            self.state["icons"][values[0]] = values[1]
        elif query.startswith("INSERT INTO item_screenshots"):
            item_id, image_data = values
            self.state["screenshots"].setdefault(item_id, []).append(image_data)
        elif query.startswith("INSERT INTO item_data"):
            item_id, types, stats = values
            if item_id in self.state["items"]:
                raise pymysql.err.IntegrityError(1062, "duplicate item")
            self.state["items"][item_id] = {"item_id": item_id, "aug_types_json": types, "stats_json": stats}
        else:
            raise AssertionError(query)

    def executemany(self, query, values):
        if query.startswith("INSERT INTO item_data"):
            for item_id, types, stats in values:
                self.state["items"][item_id] = {"item_id": item_id, "aug_types_json": types, "stats_json": stats}
        elif query.startswith("INSERT INTO items"):
            for item_id, name in values:
                self.state["catalog"].setdefault(item_id, name)
        elif query.startswith("INSERT INTO lucy_items"):
            for item_id, name in values:
                self.state["lucy"][item_id] = {"item_id": item_id, "name": name}
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
        self.state = {"uploads": [], "items": {}, "catalog": {}, "lucy": {}, "screenshots": {}, "icons": {}, "commits": 0}
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

    def test_inventory_window_slot_identity_and_screenshot_links(self):
        export = (
            "Location\tName\tID\tCount\tSlots\n"
            "Ear\tFirst earring\t1\t1\t1\n"
            "Ear-Slot1\tFirst aug\t11\t1\t0\n"
            "Ear\tSecond earring\t2\t1\t1\n"
            "Wrist\tFirst wrist\t3\t1\t0\n"
            "Wrist\tSecond wrist\t4\t1\t0\n"
            "Fingers\tFirst ring\t5\t1\t0\n"
            "Fingers\tSecond ring\t6\t1\t0\n"
            "Head\tEmpty\t0\t0\t0\n"
            "Primary\tSword\t7\t1\t0\n"
            "Range\tBow\t8\t1\t0\n"
            "General 1\tBag\t9\t1\t1\n"
            "General 1-Slot1\tNested item\t10\t1\t0\n"
            "General 11\tExtra bag\t12\t1\t0\n"
        ).encode()
        parsed = parse_inventory(export, "Example_Test-Inventory.txt")
        self.state["uploads"].append({"id": 1, "filename": parsed["filename"], "character_name": parsed["character"],
                                      "server_name": parsed["server"], "uploaded_at": "2026-01-01",
                                      "rows_json": json.dumps(parsed["rows"])})
        self.state["screenshots"][2] = [b"saved image"]
        self.state["icons"][2] = b"saved icon"
        data = dashboard()
        slots = {slot["label"]: slot for slot in data["paperdoll"]}
        for label, item_id, column, line in [
            ("Ear 1", 1, 1, 1), ("Ear 2", 2, 4, 1),
            ("Wrist 1", 3, 1, 5), ("Wrist 2", 4, 4, 5),
            ("Fingers 1", 5, 2, 7), ("Fingers 2", 6, 3, 7),
            ("Primary", 7, 1, 8), ("Range", 8, 3, 8),
        ]:
            with self.subTest(slot=label):
                slot = slots[label]
                self.assertEqual((slot["row"]["item_id"], slot["column"], slot["line"]), (item_id, column, line))
        self.assertEqual(slots["Head"]["row"]["item_id"], 0)
        self.assertIsNone(slots["Face"]["row"])
        self.assertEqual(data["bags"][0]["row"]["item_id"], 9)
        self.assertIsNone(data["bags"][1]["row"])

        page = self.client.get("/").get_data(as_text=True)
        self.assertRegex(page, re.compile(r'grid-column:4;grid-row:1.*?href="/uploads/1/items/2"', re.DOTALL))
        self.assertIn('aria-label="Ear 2: Second earring"', page)
        self.assertIn('data-item-screenshot="/items/2/screenshot"', page)
        self.assertIn('src="/items/2/icon"', page)
        self.assertIn('aria-label="Head: Empty"', page)
        self.assertIn('aria-label="Face: Not in export"', page)
        self.assertIn('aria-label="General 1: Bag"', page)
        self.assertIn("Extra bag", page)
        detail = self.client.get("/uploads/1/items/2").get_data(as_text=True)
        self.assertIn('src="/items/2/screenshot"', detail)
        self.assertNotIn("No saved screenshot for this item yet.", detail)
        no_image = self.client.get("/uploads/1/items/0").get_data(as_text=True)
        self.assertIn("No saved screenshot for this item yet.", no_image)
        self.assertIn("First aug", no_image)

    def test_inventory_icons_are_derived_from_saved_screenshots_without_overwriting(self):
        parsed = parse_inventory(EXPORT, "Example_Test-Inventory.txt")
        self.state["uploads"].append({"id": 1, "filename": parsed["filename"], "character_name": parsed["character"],
                                      "server_name": parsed["server"], "uploaded_at": "2026-01-01",
                                      "rows_json": json.dumps(parsed["rows"])})
        image = io.BytesIO()
        item_window().save(image, format="PNG")
        self.state["screenshots"][1] = [image.getvalue()]
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('src="/items/1/icon"', page)
        response = self.client.get("/items/1/icon")
        self.assertEqual(response.status_code, 200)
        icon = Image.open(io.BytesIO(response.data))
        self.assertEqual(icon.getpixel((0, 0))[3], 0)
        self.assertEqual(icon.getpixel((icon.width // 2, icon.height // 2)), (240, 20, 20, 255))
        self.assertEqual(self.state["icons"], {})
        self.state["icons"][1] = b"manually selected"
        self.assertEqual(self.client.get("/items/1/icon").data, b"manually selected")
        invalid = io.BytesIO()
        Image.new("RGB", (240, 180)).save(invalid, format="PNG")
        self.state["screenshots"][2] = [invalid.getvalue()]
        self.assertEqual(self.client.get("/items/2/icon").status_code, 404)

    def test_augment_previews_preserve_parent_identity_and_exclude_bag_contents(self):
        parsed = parse_inventory(EXPORT, "Example_Test-Inventory.txt")
        self.state["uploads"].append({"id": 1, "filename": parsed["filename"], "character_name": parsed["character"],
                                      "server_name": parsed["server"], "uploaded_at": "2026-01-01",
                                      "rows_json": json.dumps(parsed["rows"])})
        self.state["items"][11] = {"item_id": 11, "aug_types_json": "[7]",
                                   "stats_json": '{"hp": 100, "mana": 0}'}
        self.state["items"][12] = {"item_id": 12, "aug_types_json": "[8]",
                                   "stats_json": '{"heroic_str": "20", "heroic_int": 20}'}
        self.state["items"][13] = {"item_id": 13, "aug_types_json": "[7]",
                                   "stats_json": '{"hp": 200}'}
        self.state["items"][4] = {"item_id": 4, "aug_types_json": "[]",
                                  "stats_json": '{"socket_1_type": 7}'}
        self.state["icons"][11] = b"icon"
        data = dashboard()
        self.assertEqual([entry["row"]["item_id"] for entry in data["rows"][0]["preview_augments"]], [11])
        self.assertEqual([entry["row"]["item_id"] for entry in data["rows"][2]["preview_augments"]], [12])
        self.assertNotIn("preview_augments", data["rows"][4])
        self.assertEqual([entry["row"]["item_id"] for entry in data["rows"][5]["preview_augments"]], [13])
        page = self.client.get("/").get_data(as_text=True)
        first = page.split('<template id="augment-preview-0">')[1].split('</template>')[0]
        second = page.split('<template id="augment-preview-2">')[1].split('</template>')[0]
        self.assertIn("First aug", first)
        self.assertNotIn("Second aug", first)
        self.assertIn('src="/items/11/icon"', first)
        self.assertIn("HP 100", first)
        self.assertIn("Mana 0", first)
        self.assertIn("Second aug", second)
        self.assertIn("Heroic STR / INT +20", second)
        self.assertIn("HP/Mana incomplete", second)
        self.assertNotIn('<template id="augment-preview-4">', page)
        self.assertIn('<template id="augment-preview-5">', page)
        self.assertIn('data-augment-preview="0"', page)

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

    def test_lucy_link_only_for_imported_reference(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        self.assertNotIn(b'lucy.allakhazam.com', self.client.get("/uploads/1/items/0").data)
        self.state["lucy"][1] = {"item_id": 1, "name": "First earring"}
        response = self.client.get("/uploads/1/items/0")
        self.assertIn(b'https://lucy.allakhazam.com/item.html?id=1', response.data)
        self.assertIn(b'opens an external site', response.data)
        self.assertNotIn(b'lucy.allakhazam.com', self.client.get("/uploads/1/items/1").data)

    def test_allakhazam_search_uses_encoded_item_name(self):
        data = b"Location\tName\tID\tCount\tSlots\nEar\tSmith's Ring & Charm\t123\t1\t6\n"
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(data), "Example_Test-Inventory.txt")
        })
        response = self.client.get("/uploads/1/items/0")
        self.assertIn(b'https://everquest.allakhazam.com/db/search?q=Smith%27s+Ring+%26+Charm', response.data)
        self.assertIn(b'check the item ID in the results', response.data)
        self.assertNotIn(b'lucy.allakhazam.com', response.data)

    def test_import_lucy_command_batches_and_preserves_item_stats(self):
        source = "id,name,lucylink\n" + "".join(
            f'{i},Item {i},http://lucy.allakhazam.com/item.html?id={i}\n'
            for i in range(1, 1003)
        )
        self.state["items"][1] = {"item_id": 1, "stats_json": '{"ac":42}', "aug_types_json": "[7]"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            path.write_text(source, encoding="utf-8")
            result = app.test_cli_runner().invoke(args=["import-lucy", str(path)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Imported 1002 Lucy item references.", result.output)
        self.assertEqual(len(self.state["lucy"]), 1002)
        self.assertEqual(json.loads(self.state["items"][1]["stats_json"])["ac"], 42)
        self.assertEqual(self.state["commits"], 1)

    def test_import_lucy_invalid_does_not_commit(self):
        source = "id,name,lucylink\n1,A,http://example.com/item.html?id=1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "items.txt.gz")
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write(source)
            result = app.test_cli_runner().invoke(args=["import-lucy", path])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no changes committed", result.output)
        self.assertEqual(self.state["commits"], 0)

    def test_screenshot_review_and_confirmed_save(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        raw_text = ("First aug\nAugmentation type: 7 8\nAC: 42 HP: +100\n"
                    "You mustuse a solvent Class XXI Augmentation Distiller or higher.")
        with patch("app.recognize_screenshot", return_value=(raw_text, "png")):
            response = self.client.post("/uploads/1/items/1/screenshot", data={
                "csrf_token": self.token, "screenshot": (io.BytesIO(b"image"), "item.png")
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data:image/png;base64,', response.data)
        self.assertIn(b'7|8', response.data)
        self.assertNotIn(11, self.state["items"])
        match = re.search(r'<textarea name="stats_json"[^>]*>(.*?)</textarea>',
                          response.get_data(as_text=True), re.DOTALL)
        self.assertIsNotNone(match)
        reviewed_stats = html.unescape(match.group(1))
        self.assertEqual(json.loads(reviewed_stats)["distiller_class"], "XXI")
        response = self.client.post("/uploads/1/items/1/screenshot/save", data={
            "csrf_token": self.token, "confirmed": "yes", "types": "7|8",
            "stats_json": reviewed_stats, "raw_text": raw_text,
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Reviewed screenshot data saved", response.data)
        self.assertEqual(json.loads(self.state["items"][11]["aug_types_json"]), [7, 8])
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"])["ac"], 42)
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"])["distiller_class"], "XXI")
        self.assertIn(b"DISTILLER CLASS", response.data)
        self.assertIn(b"XXI", response.data)

    def test_screenshot_saving_requires_confirmation_and_preserves_existing(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        payload = {"csrf_token": self.token, "types": "7", "stats_json": '{"ac":42}', "raw_text": "AC: 42"}
        response = self.client.post("/uploads/1/items/1/screenshot/save", data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(11, self.state["items"])
        payload["confirmed"] = "yes"
        self.client.post("/uploads/1/items/1/screenshot/save", data=payload)
        payload["stats_json"] = '{"ac":10}'
        response = self.client.post("/uploads/1/items/1/screenshot/save", data=payload, follow_redirects=True)
        self.assertIn(b"did not overwrite", response.data)
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"])["ac"], 42)

    def test_screenshot_ocr_errors_are_visible(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        with patch("app.recognize_screenshot", side_effect=RuntimeError("Tesseract not installed")):
            response = self.client.post("/uploads/1/items/1/screenshot", data={
                "csrf_token": self.token, "screenshot": (io.BytesIO(b"x"), "item.png")
            }, follow_redirects=True)
        self.assertIn(b"Tesseract not installed", response.data)
        self.assertNotIn(11, self.state["items"])

    def test_multiple_screenshot_crops_are_reviewed_and_saved_separately(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        importer = self.client.get("/uploads/1/screenshots")
        self.assertEqual(importer.status_code, 200)
        self.assertIn(b"First aug", importer.data)
        image = io.BytesIO()
        Image.new("RGB", (20, 10), "red").save(image, format="PNG")
        png = image.getvalue()
        for index, name, item_id, ac in ((1, "First aug", 11, 42), (3, "Second aug", 12, 9)):
            text = f"{name}\nThis Augmentation fits in slot types: 7 (General: Group), 8 (General: Raid)\nAC: {ac}"
            with patch("app.recognize_screenshot", return_value=(text, "png")):
                recognized = self.client.post("/uploads/1/screenshots/recognize", data={
                    "csrf_token": self.token, "screenshot": (io.BytesIO(png), "crop.png")
                })
            self.assertEqual(recognized.status_code, 200)
            self.assertEqual(recognized.json["stats"], {"ac": ac})
            self.assertEqual(recognized.json["types"], [7, 8])
            saved = self.client.post("/uploads/1/screenshots/save", data={
                "csrf_token": self.token, "row_index": str(index), "confirmed": "yes", "save_stats": "yes",
                "stats_json": json.dumps(recognized.json["stats"]),
                "types": "|".join(map(str, recognized.json["types"])), "raw_text": text,
                "screenshot": (io.BytesIO(png), "crop.png"),
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(json.loads(self.state["items"][item_id]["stats_json"])["ac"], ac)
            self.assertEqual(json.loads(self.state["items"][item_id]["aug_types_json"]), [7, 8])
            response = self.client.get(f"/items/{item_id}/screenshot")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertEqual(Image.open(io.BytesIO(response.data)).size, (20, 10))
            self.assertIn(f"/items/{item_id}/screenshot".encode(), self.client.get(saved.json["item_url"]).data)
            self.assertIn(b"7 / 8", self.client.get(saved.json["item_url"]).data)
        self.assertEqual(self.client.get("/items/999/screenshot").status_code, 404)

    def test_equipment_socket_ocr_is_saved_and_compared_with_installed_augments(self):
        inventory = (
            b"Location\tName\tID\tCount\tSlots\n"
            b"Range\tGreen Pulse\t175729\t1\t3\n"
            b"Range-Slot1\tStone\t11\t1\t0\n"
            b"Range-Slot2\tCandelabra\t12\t1\t0\n"
            b"Range-Slot3\tCave Stone\t13\t1\t0\n"
        )
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(inventory), "Example_Test-Inventory.txt")
        })
        self.client.post("/item-data", data={
            "csrf_token": self.token,
            "items": (io.BytesIO(b"id,aug_types\n11,3\n12,7|8\n"), "items.csv"),
        })
        image = io.BytesIO()
        Image.new("RGB", (20, 10), "red").save(image, format="PNG")
        png = image.getvalue()
        text = ("Green Pulse\nStrength: 64 +89 Stamina: 88 +163 Intelligence: 81 +186\n"
                "Magic: 108 Fire: 93 Cold: 119 Disease: 119 Poison: 101 Corrupt: 2\n"
                "Attack: 151 HP Regen: 30 Mana Regen: 33 End Regen: 1 Spell Dmg: 246\n"
                "Slot 1, type 3 (General: Spell Effect)\n"
                "Slot2, type 5 (General: Multiple Slot)\n#3 Slot, type 8 (General: Raid)")
        with patch("app.recognize_screenshot", return_value=(text, "png")):
            recognized = self.client.post("/uploads/1/screenshots/recognize", data={
                "csrf_token": self.token, "screenshot": (io.BytesIO(png), "crop.png")
            })
        self.assertEqual(recognized.json["stats"], {
            "str": 64, "heroic_str": 89, "sta": 88, "heroic_sta": 163,
            "int": 81, "heroic_int": 186, "magic": 108, "fire": 93, "cold": 119,
            "disease": 119, "poison": 101, "corruption": 2, "attack": 151,
            "hp_regen": 30, "mana_regen": 33, "endurance_regen": 1, "spell_damage": 246,
            "socket_1_type": 3, "socket_2_type": 5, "socket_3_type": 8,
        })
        self.assertEqual(recognized.json["types"], [])
        saved = self.client.post("/uploads/1/screenshots/save", data={
            "csrf_token": self.token, "row_index": "0", "confirmed": "yes", "save_stats": "yes",
            "stats_json": json.dumps(recognized.json["stats"]), "types": "", "raw_text": text,
            "screenshot": (io.BytesIO(png), "crop.png"),
        })
        self.assertEqual(saved.status_code, 200)
        stored = json.loads(self.state["items"][175729]["stats_json"])
        self.assertEqual([stored[f"socket_{n}_type"] for n in (1, 2, 3)], [3, 5, 8])
        self.assertEqual((stored["str"], stored["heroic_str"], stored["magic"], stored["hp_regen"]),
                         (64, 89, 108, 30))
        self.assertEqual(json.loads(self.state["items"][175729]["aug_types_json"]), [])
        page = self.client.get(saved.json["item_url"]).get_data(as_text=True)
        self.assertIn("SOCKET 1 TYPE", page)
        self.assertIn("HEROIC STR", page)
        self.assertIn(">89<", page)
        self.assertIn("MAGIC", page)
        self.assertIn("Item socket type: 3", page)
        self.assertIn("Exact type match", page)
        self.assertIn("Item socket type: 5", page)
        self.assertIn("No exact type match; verify in game", page)
        self.assertIn("Item socket type: 8", page)
        self.assertIn("Augment types unknown", page)

    def test_screenshot_suggests_fuzzy_name_and_rejects_bad_distiller(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(image, format="PNG")
        png = image.getvalue()
        text = ("First auq\nThis Augmentation fits in slot types: 5\n"
                "You must use a solvent Class XIL Augmentation Distiller or higher.")
        with patch("app.recognize_screenshot", return_value=(text, "png")):
            response = self.client.post("/uploads/1/screenshots/recognize", data={
                "csrf_token": self.token, "screenshot": (io.BytesIO(png), "crop.png")
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["name_suggestions"][0]["id"], 11)
        self.assertEqual(response.json["stats"]["distiller_class"], "XIL")
        payload = {"csrf_token": self.token, "row_index": "1", "confirmed": "yes", "save_stats": "yes",
                   "stats_json": '{"distiller_class":"XIL"}', "types": "5", "raw_text": text,
                   "screenshot": (io.BytesIO(png), "crop.png")}
        saved = self.client.post("/uploads/1/screenshots/save", data=payload)
        self.assertEqual(saved.status_code, 400)
        self.assertIn("Roman numeral", saved.json["error"])
        self.assertNotIn(11, self.state["items"])

    def test_screenshot_save_requires_confirmation_and_preserves_catalog(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        self.state["items"][11] = {"item_id": 11, "stats_json": '{"ac":42}', "aug_types_json": "[7]"}
        image = io.BytesIO()
        Image.new("RGB", (5, 5), "blue").save(image, format="PNG")
        png = image.getvalue()

        def save(confirmed, save_stats, content=png, row_index="1"):
            return self.client.post("/uploads/1/screenshots/save", data={
                "csrf_token": self.token, "row_index": row_index, "confirmed": confirmed, "save_stats": save_stats,
                "stats_json": '{"ac":10}', "types": "8", "raw_text": "AC: 10",
                "screenshot": (io.BytesIO(content), "item.png"),
            })

        self.assertEqual(save("", "yes").status_code, 400)
        self.assertEqual(save("yes", "yes", b"bad").status_code, 400)
        self.assertEqual(save("yes", "yes", row_index="not-a-number").status_code, 400)
        self.assertEqual(save("yes", "yes").status_code, 409)
        self.assertEqual(self.state["screenshots"], {})
        self.assertEqual(save("yes", "").status_code, 200)
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"]), {"ac": 42})
        self.assertEqual(len(self.state["screenshots"][11]), 1)
        another = io.BytesIO()
        Image.new("RGB", (4, 3), "red").save(another, format="PNG")
        self.assertEqual(save("yes", "", another.getvalue()).status_code, 200)
        self.assertEqual(len(self.state["screenshots"][11]), 2)
        latest = self.client.get("/items/11/screenshot")
        self.assertEqual(Image.open(io.BytesIO(latest.data)).size, (4, 3))

    def test_icon_crop_is_saved_and_shown_with_item_everywhere(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        image = Image.new("RGB", (20, 20), "red")
        for x in range(3, 8):
            for y in range(4, 10):
                image.putpixel((x, y), (0, 0, 255))
        data = io.BytesIO()
        image.save(data, format="PNG")
        png = data.getvalue()
        response = self.client.post("/uploads/1/screenshots/save", data={
            "csrf_token": self.token, "row_index": "1", "confirmed": "yes", "save_stats": "yes",
            "stats_json": '{"ac":42}', "types": "7", "raw_text": "AC: 42",
            "icon_x": "3", "icon_y": "4", "icon_width": "5", "icon_height": "6",
            "screenshot": (io.BytesIO(png), "item.png"),
        })
        self.assertEqual(response.status_code, 200)
        icon = self.client.get("/items/11/icon")
        self.assertEqual(icon.status_code, 200)
        self.assertEqual(icon.mimetype, "image/png")
        self.assertEqual(icon.headers["Cache-Control"], "no-store")
        decoded = Image.open(io.BytesIO(icon.data))
        self.assertEqual(decoded.size, (5, 6))
        self.assertEqual(decoded.getpixel((0, 0)), (0, 0, 255))
        page = self.client.get("/").get_data(as_text=True)
        self.assertEqual(page.count('src="/items/11/icon"'), 4)
        self.assertIn('src="/items/11/icon"', self.client.get("/uploads/1/items/0").get_data(as_text=True))
        self.assertEqual(self.client.get("/items/12/icon").status_code, 404)

    def test_icon_validation_and_existing_saved_screenshot(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        self.state["items"][11] = {"item_id": 11, "stats_json": '{"ac":42}', "aug_types_json": "[7]"}
        pngs = []
        for color in ("red", "blue"):
            out = io.BytesIO()
            Image.new("RGB", (20, 20), color).save(out, format="PNG")
            pngs.append(out.getvalue())
        self.state["screenshots"][11] = pngs
        url = "/uploads/1/items/1/icon"
        self.assertIn(b'/items/11/screenshot/2', self.client.get(url).data)
        fields = {"csrf_token": self.token, "screenshot_id": "1", "confirmed": "yes",
                  "icon_x": "0", "icon_y": "0", "icon_width": "5", "icon_height": "5"}
        response = self.client.post(url, data=fields, follow_redirects=True)
        self.assertIn(b"Item icon saved", response.data)
        icon = Image.open(io.BytesIO(self.client.get("/items/11/icon").data))
        self.assertEqual(icon.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(json.loads(self.state["items"][11]["stats_json"]), {"ac": 42})
        for overrides in ({"confirmed": ""}, {"icon_x": "-1"}, {"icon_width": "21"},
                          {"icon_width": ""}, {"icon_height": "513"}):
            invalid = dict(fields, **overrides)
            result = self.client.post(url, data=invalid, follow_redirects=True)
            self.assertIn(b'notice error', result.data)
            self.assertEqual(self.client.get("/items/11/icon").data, self.state["icons"][11])
        self.assertEqual(self.client.get("/uploads/1/items/3/icon").status_code, 404)

    def test_invalid_icon_is_rejected_before_screenshot_or_stats_save(self):
        self.client.post("/upload", data={
            "csrf_token": self.token, "inventory": (io.BytesIO(EXPORT), "Example_Test-Inventory.txt")
        })
        image = io.BytesIO()
        Image.new("RGB", (10, 10)).save(image, format="PNG")
        response = self.client.post("/uploads/1/screenshots/save", data={
            "csrf_token": self.token, "row_index": "1", "confirmed": "yes", "save_stats": "yes",
            "stats_json": '{"ac":42}', "types": "", "raw_text": "AC: 42",
            "icon_x": "9", "icon_y": "0", "icon_width": "3", "icon_height": "3",
            "screenshot": (io.BytesIO(image.getvalue()), "item.png"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Icon rectangle", response.json["error"])
        self.assertEqual(self.state["screenshots"], {})
        self.assertNotIn(11, self.state["items"])

    def test_screenshot_api_returns_json_for_oversized_upload(self):
        previous = app.config["MAX_CONTENT_LENGTH"]
        app.config["MAX_CONTENT_LENGTH"] = 1024
        self.addCleanup(app.config.__setitem__, "MAX_CONTENT_LENGTH", previous)
        response = self.client.post("/uploads/1/screenshots/recognize", data={
            "csrf_token": self.token, "screenshot": (io.BytesIO(b"x" * 2048), "crop.png")
        })
        self.assertEqual(response.status_code, 413)
        self.assertIn("10 MB", response.json["error"])


if __name__ == "__main__":
    unittest.main()
