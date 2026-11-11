import json
import unittest

from inventory import parse_inventory, parse_item_data, parse_lucy_items
import io


EXPORT = (
    "Location\tName\tID\tCount\tSlots\n"
    "Ear\tFirst earring\t1\t1\t6\n"
    "Ear-Slot1\tFirst aug\t11\t1\t6\n"
    "Ear\tSecond earring\t2\t1\t6\n"
    "Ear-Slot1\tSecond aug\t12\t1\t6\n"
    "General 1\tBag\t3\t1\t2\n"
    "General 1-Slot1\tNested item\t4\t1\t6\n"
    "General 1-Slot1-Slot1\tNested aug\t13\t1\t6\n"
    "\nKeyRing\tName\tID\t\n"
    "Mount\tA mount\t42\tSTAT\n"
).encode()


class InventoryTests(unittest.TestCase):
    def test_lucy_reference_list(self):
        text = 'id,name,lucylink\n123,"Sword, fine",http://lucy.allakhazam.com/item.html?id=123\n'
        self.assertEqual(list(parse_lucy_items(io.StringIO(text))), [(123, "Sword, fine")])

    def test_rejects_bad_lucy_lists(self):
        for text in ['id,name\n1,A\n',
                     'id,name,lucylink\n1,A,https://evil.example/item.html?id=1\n',
                     'id,name,lucylink\n1,A,http://lucy.allakhazam.com/item.html?id=2\n',
                     'id,name,lucylink\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                list(parse_lucy_items(io.StringIO(text)))
    def test_duplicate_slots_and_nested_items(self):
        data = parse_inventory(EXPORT, "Example_Test-Inventory.txt")
        self.assertEqual((data["character"], data["server"]), ("Example", "Test"))
        rows = data["rows"]
        self.assertEqual([row["parent"] for row in rows], [None, 0, None, 2, None, 4, 5, None])
        self.assertEqual(rows[-1]["extra"], ["STAT"])
        self.assertEqual(rows[-1]["section"], "keyring")

    def test_bad_inventory_fails_explicitly(self):
        for data in [b"not an inventory", b"Location\tName\tID\tCount\tSlots\nEar-Slot1\tA\t1\t1\t6\n",
                     b"Location\tName\tID\tCount\tSlots\nEar\tA\t1\tbad\t6\n",
                     b"Location\tName\tID\tCount\tSlots\nEar\tA\t1\t1\t6\nKeyRing\tName\tID\nMount\tA\t4294967296\n"]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_inventory(data, "x.txt")

    def test_item_data_types_and_extra_stats(self):
        rows = parse_item_data(b"id,aug_types,ac,hp,heroic_int\n11,7|8,42,100,12\n12,7,,0,\n")
        self.assertEqual(json.loads(rows[0][1]), [7, 8])
        self.assertEqual(json.loads(rows[0][2]), {"ac": 42, "hp": 100, "heroic_int": "12"})
        self.assertEqual(json.loads(rows[1][2])["ac"], "")
        self.assertEqual(json.loads(rows[1][2])["hp"], 0)

    def test_bad_item_data_fails_before_saving(self):
        for data in [b"id,ac\n1,42", b"id,aug_types,ac\n1,7,nope",
                     b"id,aug_types\n1,7\n1,8", b"id,aug_types\n1,7,extra"]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_item_data(data)


if __name__ == "__main__":
    unittest.main()
