import hashlib
import json


NON_STATS = {"ocr_text", "equip_slots", "item_flags", "size", "distiller_class",
             "weight", "source", "required_level", "recommended_level", "tribute"}


def populated(value):
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def stat_count(stats):
    return sum(1 for key, value in stats.items()
               if key not in NON_STATS and not key.startswith("socket_")
               and populated(value))


def update_decision(existing_stats, existing_types, new_stats, new_types):
    old_count, new_count = stat_count(existing_stats), stat_count(new_stats)
    if new_count > old_count:
        return "replace", new_stats, new_types
    if new_count == old_count:
        return "confirm_replace", new_stats, new_types
    merged = dict(existing_stats)
    for key, value in new_stats.items():
        if populated(value):
            merged[key] = value
    types = new_types if new_types else existing_types
    conflicts = any(key != "ocr_text" and key in existing_stats
                    and populated(existing_stats[key])
                    and populated(value) and existing_stats[key] != value
                    for key, value in new_stats.items())
    conflicts = conflicts or bool(new_types and existing_types and new_types != existing_types)
    return ("confirm_merge" if conflicts else "merge"), merged, types


def confirmation_token(existing_stats, existing_types, new_stats, new_types):
    payload = json.dumps([existing_stats, existing_types, new_stats, new_types],
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def describe_changes(old_stats, old_types, new_stats, new_types):
    changes = []
    for key in sorted((set(old_stats) | set(new_stats)) - {"ocr_text"}):
        if old_stats.get(key) != new_stats.get(key):
            changes.append({"field": key, "old": old_stats.get(key), "new": new_stats.get(key)})
    if old_types != new_types:
        changes.append({"field": "aug_types", "old": old_types, "new": new_types})
    return changes
