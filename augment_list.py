from augment_preview import numeric_stat
from base_stats import ADDITIVE_STATS
from inventory import EQUIPMENT, SLOT
from socket_types import socket_type


STAT_KEYS = ADDITIVE_STATS + ("purity",)
NON_AUGMENT_ITEM_IDS = frozenset({52023})


def collect_augments(rows):
    results = []
    for row in rows:
        if not row["item_id"] or row["item_id"] in NON_AUGMENT_ITEM_IDS:
            continue
        parent = rows[row["parent"]] if row["parent"] is not None else None
        match = SLOT.fullmatch(row["location"])
        equipped = bool(parent and parent["item_id"] and parent["parent"] is None and parent["section"] == "inventory"
                        and parent["location"] in EQUIPMENT)
        installed_type = (socket_type(parent["catalog"]["stats"], int(match.group(2)))
                          if parent and parent["item_id"] and parent["catalog"] and match else None)
        types = row["catalog"]["types"] if row["catalog"] else []
        if not (equipped or installed_type is not None or types):
            continue
        location_kind = "equipped" if equipped else "installed" if installed_type is not None else "loose"
        stats = row["catalog"]["stats"] if row["catalog"] else {}
        results.append({"row": row, "parent": parent, "kind": location_kind,
                        "socket_type": installed_type, "types": types, "stats": stats})
    return results


def filter_sort_augments(entries, search, kind, aug_type, stat, direction, minimum):
    def matches(entry):
        row = entry["row"]
        fields = [row["name"], row["location"], str(row["item_id"]),
                  entry["parent"]["name"] if entry["parent"] else ""]
        fields.extend(f"{key} {value}" for key, value in entry["stats"].items() if key != "ocr_text")
        haystack = " ".join(fields).casefold()
        if search.casefold() not in haystack or (kind and entry["kind"] != kind):
            return False
        if aug_type is not None and aug_type not in entry["types"] and aug_type != entry["socket_type"]:
            return False
        value = numeric_stat(entry["stats"].get(stat)) if stat != "name" else None
        return minimum is None or (value is not None and value >= minimum)

    filtered = [entry for entry in entries if matches(entry)]
    filtered.sort(key=lambda entry: (entry["row"]["name"].casefold(), entry["row"]["index"]))
    if stat == "name":
        if direction == "desc":
            filtered.reverse()
        return filtered
    known = [entry for entry in filtered if numeric_stat(entry["stats"].get(stat)) is not None]
    unknown = [entry for entry in filtered if numeric_stat(entry["stats"].get(stat)) is None]
    known.sort(key=lambda entry: numeric_stat(entry["stats"].get(stat)), reverse=direction == "desc")
    return known + unknown
