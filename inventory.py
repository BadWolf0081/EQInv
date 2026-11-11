import csv
import io
import json
import re
from pathlib import PurePath
from urllib.parse import parse_qs, urlsplit

from distiller import valid_distiller_class
from socket_types import socket_number

EQUIPMENT = {
    "Charm", "Ear", "Head", "Face", "Neck", "Shoulders", "Arms", "Back",
    "Wrist", "Range", "Hands", "Primary", "Secondary", "Fingers", "Chest",
    "Legs", "Feet", "Waist", "Power Source", "Ammo",
}
SLOT = re.compile(r"^(.*)-Slot([1-9][0-9]*)$")
NUMBER = re.compile(r"^[0-9]+$")


def parse_lucy_items(stream):
    reader = csv.DictReader(stream)
    if reader.fieldnames != ["id", "name", "lucylink"]:
        raise ValueError("Expected Lucy item list header: id,name,lucylink.")
    count = 0
    for row in reader:
        line = reader.line_num
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Incorrect number of columns on line {line}.")
        item_id, name, link = row["id"].strip(), row["name"].strip(), row["lucylink"].strip()
        if not NUMBER.fullmatch(item_id) or not 0 < int(item_id) <= 4294967295 or not name:
            raise ValueError(f"Invalid item ID or name on line {line}.")
        url = urlsplit(link)
        if (url.scheme not in ("http", "https") or url.netloc != "lucy.allakhazam.com"
                or url.path != "/item.html" or url.fragment
                or parse_qs(url.query, keep_blank_values=True) != {"id": [item_id]}):
            raise ValueError(f"Invalid Lucy item link on line {line}.")
        count += 1
        yield int(item_id), name
    if not count:
        raise ValueError("Lucy item list contains no items.")


def decode_upload(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def parse_inventory(data, filename):
    text = decode_upload(data)
    lines = text.splitlines()
    if not lines or lines[0].strip().lower().split("\t") != [
        "location", "name", "id", "count", "slots"
    ]:
        raise ValueError("Expected the EverQuest inventory header: Location, Name, ID, Count, Slots (tab-separated).")
    rows = []
    current = {}
    section = "inventory"
    for line_number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        columns = line.split("\t")
        if columns[0].strip().lower() == "keyring" and len(columns) >= 3 and columns[1:3] == ["Name", "ID"]:
            section = "keyring"
            continue
        if section == "keyring":
            if (len(columns) < 3 or not columns[0] or not columns[1]
                    or not NUMBER.fullmatch(columns[2].strip())
                    or int(columns[2]) > 4294967295):
                raise ValueError(f"Invalid keyring row on line {line_number}.")
            rows.append({"location": columns[0], "name": columns[1], "item_id": int(columns[2]),
                         "count": 1, "slots": None, "parent": None, "section": "keyring",
                         "extra": columns[3:]})
            continue
        if len(columns) != 5 or not columns[0] or not columns[1] or any(
            not NUMBER.fullmatch(value.strip()) for value in columns[2:]
        ):
            raise ValueError(f"Invalid inventory row on line {line_number}; expected five tab-separated columns.")
        location, name = columns[:2]
        item_id, count, slots = map(int, columns[2:])
        if max(item_id, count, slots) > 4294967295:
            raise ValueError(f"Number out of range on line {line_number}.")
        match = SLOT.fullmatch(location)
        parent = None
        if match:
            parent_location = match.group(1)
            if parent_location not in current:
                raise ValueError(f"Missing parent for {location} on line {line_number}.")
            parent = current[parent_location]
        else:
            # Repeated equipment labels (Ear, Wrist, Fingers) start a new branch.
            current = {}
        for path in list(current):
            if path.startswith(location + "-Slot"):
                del current[path]
        row = {"location": location, "name": name, "item_id": item_id, "count": count,
               "slots": slots, "parent": parent, "section": "inventory"}
        rows.append(row)
        current[location] = len(rows) - 1
    if not any(row["section"] == "inventory" for row in rows):
        raise ValueError("The inventory export contains no inventory rows.")
    basename = PurePath(filename.replace("\\", "/")).name
    match = re.fullmatch(r"(.+?)_(.+?)-Inventory\.txt", basename, re.IGNORECASE)
    return {"character": match.group(1) if match else None, "server": match.group(2) if match else None,
            "filename": basename, "rows": rows, "raw": text}


def parse_item_data(data):
    text = decode_upload(data)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        raise ValueError("Item data CSV is empty.")
    fields = [field.strip().lower() for field in reader.fieldnames]
    if len(set(fields)) != len(fields) or any(not field for field in fields):
        raise ValueError("Item data CSV headers must be nonempty and unique.")
    reader.fieldnames = fields
    if "id" not in fields or "aug_types" not in fields:
        raise ValueError("Item data CSV must include id and aug_types columns.")
    result = []
    seen = set()
    for line, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Incorrect number of columns on CSV line {line}.")
        row = {key: value.strip() for key, value in row.items()}
        if not NUMBER.fullmatch(row["id"]) or not 0 < int(row["id"]) <= 4294967295:
            raise ValueError(f"Invalid item ID on CSV line {line}.")
        item_id = int(row.pop("id"))
        if item_id in seen:
            raise ValueError(f"Duplicate item ID {item_id} on CSV line {line}.")
        seen.add(item_id)
        raw_types = row.pop("aug_types")
        if "distiller_class" in row and not valid_distiller_class(row["distiller_class"]):
            raise ValueError(f"Invalid distiller_class on CSV line {line}; use I to XXX or Perfected only.")
        types = []
        if raw_types:
            for value in raw_types.split("|"):
                if not NUMBER.fullmatch(value.strip()) or not 1 <= int(value.strip()) <= 255:
                    raise ValueError(f"Invalid augment type on CSV line {line}; use numbers separated by |.")
                types.append(int(value.strip()))
        # Empty stat values mean unknown, not zero. Preserve every supplied field.
        for key in ("ac", "hp", "mana", "endurance"):
            if key in row and row[key]:
                try:
                    row[key] = int(row[key])
                except ValueError as exc:
                    raise ValueError(f"Invalid {key} on CSV line {line}; use a whole number.") from exc
        for key, value in row.items():
            if socket_number(key) is not None and value:
                if not NUMBER.fullmatch(value) or not 1 <= int(value) <= 255:
                    raise ValueError(f"Invalid {key} on CSV line {line}; use a number from 1 to 255.")
                row[key] = int(value)
        result.append((item_id, json.dumps(sorted(set(types))), json.dumps(row, ensure_ascii=False)))
    if not result:
        raise ValueError("Item data CSV contains no items.")
    return result
