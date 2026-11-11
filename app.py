import csv
import base64
import gzip
import io
import json
import logging
import os
import secrets
from urllib.parse import urlencode

import click
import pymysql
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from db import catalog_items, connect, initialize
from augment_preview import augment_summary, numeric_stat
from augment_list import NON_AUGMENT_ITEM_IDS, STAT_KEYS, collect_augments, filter_sort_augments
from base_stats import calculate_base
from icon_detection import automatic_icon
from inventory import EQUIPMENT, SLOT, parse_inventory, parse_item_data, parse_lucy_items
from item_matching import item_name_text, suggest_item_names
from screenshot_ocr import extract_candidates, load_screenshot, recognize_screenshot, validate_review
from screenshot_updates import confirmation_token, describe_changes, stat_count, update_decision
from socket_types import socket_type

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024,
                  SECRET_KEY=os.environ.get("EQINV_SECRET_KEY", os.urandom(32)))
logging.basicConfig(level=logging.INFO)

PAPERDOLL_LAYOUT = (
    ("Ear", 1, 1, 1), ("Head", 1, 2, 1), ("Face", 1, 3, 1), ("Ear", 2, 4, 1),
    ("Chest", 1, 1, 2), ("Neck", 1, 4, 2),
    ("Arms", 1, 1, 3), ("Back", 1, 4, 3),
    ("Waist", 1, 1, 4), ("Shoulders", 1, 4, 4),
    ("Wrist", 1, 1, 5), ("Wrist", 2, 4, 5),
    ("Legs", 1, 1, 6), ("Hands", 1, 2, 6), ("Charm", 1, 3, 6), ("Feet", 1, 4, 6),
    ("Fingers", 1, 2, 7), ("Fingers", 2, 3, 7), ("Power Source", 1, 4, 7),
    ("Primary", 1, 1, 8), ("Secondary", 1, 2, 8), ("Range", 1, 3, 8), ("Ammo", 1, 4, 8),
)


@app.context_processor
def csrf_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


@app.before_request
def protect_forms():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, "Invalid form token. Reload the page and try again.")


@app.cli.command("init-db")
def init_db():
    """Create the application tables in the configured database."""
    with connect() as connection:
        initialize(connection)
    click.echo("Database tables initialized.")


@app.cli.command("import-lucy")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=str))
def import_lucy(path):
    """Import Lucy's item ID/name list (CSV or .gz)."""
    try:
        opener = gzip.open if path.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as stream, connect() as connection:
            with connection.cursor() as cursor:
                batch = []
                count = 0
                for item in parse_lucy_items(stream):
                    batch.append(item)
                    if len(batch) == 1000:
                        insert_lucy_batch(cursor, batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    insert_lucy_batch(cursor, batch)
                    count += len(batch)
            connection.commit()
        click.echo(f"Imported {count} Lucy item references.")
    except (OSError, EOFError, UnicodeError, ValueError, csv.Error, pymysql.MySQLError) as exc:
        raise click.ClickException(f"Lucy import failed; no changes committed: {exc}") from exc


def insert_lucy_batch(cursor, batch):
    cursor.executemany(
        "INSERT INTO lucy_items (item_id, name) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE name=VALUES(name)", batch,
    )


def save_upload(upload):
    parsed = parse_inventory(upload.read(), upload.filename)
    if len(parsed["filename"]) > 255:
        raise ValueError("Filename is too long.")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO uploads (filename, character_name, server_name, raw_text, rows_json) "
                "VALUES (%s, %s, %s, %s, %s)",
                (parsed["filename"], parsed["character"], parsed["server"], parsed["raw"],
                 json.dumps(parsed["rows"], ensure_ascii=False)),
            )
            catalog_items(cursor, parsed["rows"])
        connection.commit()


def save_items(upload):
    items = parse_item_data(upload.read())
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO item_data (item_id, aug_types_json, stats_json) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE aug_types_json=VALUES(aug_types_json), stats_json=VALUES(stats_json)",
                items,
            )
        connection.commit()
    return len(items)


def dashboard(upload_id=None):
    with connect() as connection:
        with connection.cursor() as cursor:
            query = "SELECT id, filename, character_name, server_name, uploaded_at, rows_json FROM uploads "
            if upload_id is None:
                cursor.execute(query + "ORDER BY id DESC LIMIT 1")
            else:
                cursor.execute(query + "WHERE id = %s", (upload_id,))
            upload = cursor.fetchone()
            if not upload:
                return None
            rows = json.loads(upload.pop("rows_json"))
            ids = sorted({row["item_id"] for row in rows if row["item_id"]})
            catalog = {}
            icons = set()
            screenshots = set()
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(f"SELECT item_id, aug_types_json, stats_json FROM item_data WHERE item_id IN ({placeholders})", ids)
                for item in cursor.fetchall():
                    catalog[item["item_id"]] = {
                        "types": json.loads(item["aug_types_json"]),
                        "stats": json.loads(item["stats_json"]),
                    }
                cursor.execute(f"SELECT item_id FROM item_icons WHERE item_id IN ({placeholders})", ids)
                icons = {item["item_id"] for item in cursor.fetchall()}
                cursor.execute(f"SELECT DISTINCT item_id FROM item_screenshots WHERE item_id IN ({placeholders})", ids)
                screenshots = {item["item_id"] for item in cursor.fetchall()}
    equipment = []
    counts = {}
    for index, row in enumerate(rows):
        row["index"] = index
        row["catalog"] = catalog.get(row["item_id"])
        row["has_icon"] = row["item_id"] in icons
        row["has_screenshot"] = row["item_id"] in screenshots
        if row["section"] != "inventory":
            continue
        if row["parent"] is None and row["location"] in EQUIPMENT:
            counts[row["location"]] = counts.get(row["location"], 0) + 1
            equipment.append({"index": index, "row": row, "augments": [], "number": counts[row["location"]]})
        elif equipment and row["parent"] == equipment[-1]["index"]:
            equipment[-1]["augments"].append(row)
    for gear in equipment:
        gear["row"]["preview_augments"] = [
            {"row": aug, "summary": augment_summary(
                aug["catalog"], socket_type(gear["row"]["catalog"]["stats"], int(SLOT.fullmatch(aug["location"]).group(2)))
                if gear["row"]["catalog"] and SLOT.fullmatch(aug["location"]) else None)}
            for aug in gear["augments"] if aug["item_id"]
        ]
        gear["row"]["preview_has_slots"] = bool(gear["augments"])
        gear["row"]["ornamented"] = any(
            entry["summary"]["slot_type"] == 22 for entry in gear["row"]["preview_augments"])
    for child in rows:
        if child["parent"] is None or not child["item_id"]:
            continue
        parent = rows[child["parent"]]
        if "preview_augments" in parent and parent["parent"] is None and parent["location"] in EQUIPMENT:
            continue
        match = SLOT.fullmatch(child["location"])
        if (parent["item_id"] and parent["catalog"] and match
                and socket_type(parent["catalog"]["stats"], int(match.group(2))) is not None):
            parent.setdefault("preview_augments", []).append(
                {"row": child, "summary": augment_summary(child["catalog"],
                 socket_type(parent["catalog"]["stats"], int(match.group(2))))})
            parent["preview_has_slots"] = True
            if socket_type(parent["catalog"]["stats"], int(match.group(2))) == 22:
                parent["ornamented"] = True
    augments = []
    unknown_types = 0
    for gear in equipment:
        for aug in gear["augments"]:
            if not aug["item_id"]:
                continue
            item = aug["catalog"]
            if not item or not item["types"]:
                unknown_types += 1
            elif 7 in item["types"] or 8 in item["types"]:
                augments.append({"gear": gear, "aug": aug})
    augments.sort(key=lambda entry: (
        not isinstance(entry["aug"]["catalog"]["stats"].get("ac"), int),
        entry["aug"]["catalog"]["stats"].get("ac") if isinstance(entry["aug"]["catalog"]["stats"].get("ac"), int) else 0,
        entry["aug"]["name"].casefold(),
    ))
    gear_by_slot = {(gear["row"]["location"], gear["number"]): gear["row"] for gear in equipment}
    paperdoll = [
        {"label": f"{name} {number}" if name in ("Ear", "Wrist", "Fingers") else name,
         "row": gear_by_slot.get((name, number)), "column": column, "line": line}
        for name, number, column, line in PAPERDOLL_LAYOUT
    ]
    general_labels = {f"General {number}" for number in range(1, 11)}
    general = {row["location"]: row for row in rows
               if row["section"] == "inventory" and row["parent"] is None
               and row["location"] in general_labels}
    bags = [{"label": f"General {number}", "row": general.get(f"General {number}")}
            for number in range(1, 11)]
    return {"upload": upload, "equipment": equipment, "augments": augments,
            "unknown_types": unknown_types, "rows": rows, "paperdoll": paperdoll, "bags": bags}


@app.route("/uploads/<int:upload_id>/augments")
def augment_list(upload_id):
    try:
        data = dashboard(upload_id)
        if data is None:
            abort(404)
        entries = collect_augments(data["rows"])
        excluded = [row for row in data["rows"]
                    if row["item_id"] in NON_AUGMENT_ITEM_IDS and row["catalog"]
                    and row["catalog"]["types"]]
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load augments")
        return "Unable to load augments. Check the server logs.", 503
    try:
        stats = sorted(set(STAT_KEYS) | {
            key for entry in entries for key, value in entry["stats"].items()
            if key not in ("ocr_text", "weight", "tribute", "required_level", "recommended_level")
            and not key.startswith("socket_") and numeric_stat(value) is not None
        })
        stat = request.args.get("stat", "hp")
        direction = request.args.get("direction", "asc")
        kind = request.args.get("kind", "")
        search = request.args.get("q", "").strip()
        type_text = request.args.get("type", "").strip()
        minimum_text = request.args.get("min", "").strip()
        if stat not in ("name", *stats) or direction not in ("asc", "desc") or kind not in ("", "equipped", "installed", "loose"):
            raise ValueError("Invalid sort or location filter.")
        if type_text and (not type_text.isascii() or not type_text.isdigit() or not 1 <= int(type_text) <= 255):
            raise ValueError("Augment type must be a number from 1 to 255.")
        if minimum_text and (stat == "name" or numeric_stat(minimum_text) is None):
            raise ValueError("Minimum requires a numeric stat and a whole number.")
        aug_type = int(type_text) if type_text else None
        minimum = numeric_stat(minimum_text) if minimum_text else None
        results = filter_sort_augments(entries, search, kind, aug_type, stat, direction, minimum)
        for entry in results:
            entry["sort_value"] = numeric_stat(entry["stats"].get(stat)) if stat != "name" else None
        return render_template("augments.html", data=data, entries=results, total=len(entries), excluded=excluded,
                               stats=stats, stat=stat, direction=direction, kind=kind,
                               search=search, type_text=type_text, minimum_text=minimum_text)
    except ValueError as exc:
        return f"Invalid augment filter: {exc}", 400


@app.route("/", methods=["GET"])
def index():
    try:
        data = dashboard()
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load inventory")
        return render_template("index.html", data=None, db_error=True), 503
    return render_template("index.html", data=data, db_error=False)


@app.route("/uploads/<int:upload_id>/items/<int:row_index>")
def item_detail(upload_id, row_index):
    stat_view = request.args.get("stats", "catalog")
    if stat_view not in ("catalog", "base"):
        return "Invalid item stats view.", 400
    try:
        data = dashboard(upload_id)
        if data is None or row_index >= len(data["rows"]) or not data["rows"][row_index]["item_id"]:
            abort(404)
        row = data["rows"][row_index]
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT item_id, name FROM lucy_items WHERE item_id = %s", (row["item_id"],))
                lucy = cursor.fetchone()
                cursor.execute("SELECT id FROM item_screenshots WHERE item_id = %s ORDER BY id DESC LIMIT 1",
                               (row["item_id"],))
                screenshot = cursor.fetchone()
                cursor.execute("SELECT screenshot_id, stats_json, augments_json FROM item_stat_observations "
                               "WHERE upload_id = %s AND row_index = %s AND item_id = %s ORDER BY id DESC LIMIT 1",
                               (upload_id, row_index, row["item_id"]))
                observation = cursor.fetchone()
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load item details")
        return render_template("index.html", data=None, db_error=True), 503
    children = [child for child in data["rows"] if child["parent"] == row_index]
    parent_stats = row["catalog"]["stats"] if row["catalog"] else {}
    for child in children:
        match = SLOT.fullmatch(child["location"])
        child["socket_type"] = socket_type(parent_stats, int(match.group(2))) if match else None
        child["socket_match"] = None
        if child["socket_type"] is not None and child["catalog"] and child["catalog"]["types"]:
            child["socket_match"] = child["socket_type"] in child["catalog"]["types"]
    parent = data["rows"][row["parent"]] if row["parent"] is not None else None
    base = None
    if observation:
        augments = json.loads(observation["augments_json"])
        blocked = any(aug["socket_type"] in (None, 13, 14) for aug in augments)
        catalogs = {child["item_id"]: child["catalog"] for child in children if child["item_id"]}
        base = {
            "blocked": blocked,
            "values": {} if blocked else calculate_base(
                json.loads(observation["stats_json"]),
                [catalogs.get(aug["item_id"])["stats"] if catalogs.get(aug["item_id"]) else None
                 for aug in augments]),
            "screenshot_id": observation["screenshot_id"],
        }
    allakhazam_search = "https://everquest.allakhazam.com/db/search?" + urlencode({"q": row["name"]})
    return render_template("item.html", data=data, row=row, children=children, parent=parent,
                           lucy=lucy, screenshot=screenshot, allakhazam_search=allakhazam_search, base=base,
                           stat_view=stat_view,
                           non_augment_mismatch=(row["item_id"] in NON_AUGMENT_ITEM_IDS
                                                 and row["catalog"] and row["catalog"]["types"]))


@app.route("/items/<int:item_id>/screenshot")
@app.route("/items/<int:item_id>/screenshot/<int:screenshot_id>")
def item_screenshot(item_id, screenshot_id=None):
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                if screenshot_id is None:
                    cursor.execute("SELECT image_data FROM item_screenshots WHERE item_id = %s ORDER BY id DESC LIMIT 1",
                                   (item_id,))
                else:
                    cursor.execute("SELECT image_data FROM item_screenshots WHERE item_id = %s AND id = %s",
                                   (item_id, screenshot_id))
                image = cursor.fetchone()
        if not image:
            abort(404)
        response = Response(image["image_data"], mimetype="image/png")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Unable to load item screenshot")
        return "Unable to load item screenshot. Check the server logs.", 503


@app.route("/items/<int:item_id>/icon")
def item_icon(item_id):
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT image_data FROM item_icons WHERE item_id = %s", (item_id,))
                image = cursor.fetchone()
                if not image:
                    cursor.execute("SELECT image_data FROM item_screenshots WHERE item_id = %s ORDER BY id DESC LIMIT 1",
                                   (item_id,))
                    screenshot = cursor.fetchone()
                    if screenshot:
                        source, _ = load_screenshot(screenshot["image_data"])
                        icon = automatic_icon(source)
                        if icon is not None:
                            image = {"image_data": icon}
        if not image:
            abort(404)
        response = Response(image["image_data"], mimetype="image/png")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load item icon")
        return "Unable to load item icon. Check the server logs.", 503


def crop_icon(image, values):
    coordinates = [values.get(name, "") for name in ("icon_x", "icon_y", "icon_width", "icon_height")]
    if not any(coordinates):
        return None
    if any(not value.isascii() or not value.isdigit() or len(value) > 8 for value in coordinates):
        raise ValueError("Select a valid icon rectangle within the item screenshot.")
    x, y, width, height = map(int, coordinates)
    if (width < 1 or height < 1 or width > 512 or height > 512
            or x + width > image.width or y + height > image.height):
        raise ValueError("Icon rectangle must fit the screenshot and be no larger than 512 by 512 pixels.")
    output = io.BytesIO()
    image.crop((x, y, x + width, y + height)).save(output, format="PNG")
    return output.getvalue()


def store_icon(cursor, item_id, icon):
    cursor.execute(
        "INSERT INTO item_icons (item_id, image_data) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE image_data=VALUES(image_data)",
        (item_id, icon),
    )


def update_screenshot_catalog(cursor, item_id, stats, types, confirmation):
    cursor.execute("SELECT item_id, aug_types_json, stats_json FROM item_data WHERE item_id = %s FOR UPDATE",
                   (item_id,))
    existing = cursor.fetchone()
    if not existing:
        cursor.execute("INSERT INTO item_data (item_id, aug_types_json, stats_json) VALUES (%s, %s, %s)",
                       (item_id, json.dumps(types), json.dumps(stats, ensure_ascii=False)))
        return None
    old_stats = json.loads(existing["stats_json"])
    old_types = json.loads(existing["aug_types_json"])
    decision, updated_stats, updated_types = update_decision(old_stats, old_types, stats, types)
    token = confirmation_token(old_stats, old_types, stats, types)
    token_matches = confirmation.isascii() and len(confirmation) == len(token) and secrets.compare_digest(token, confirmation)
    if (decision.startswith("confirm_") or confirmation) and not token_matches:
        prompt_decision = decision if decision.startswith("confirm_") else "confirm_" + decision
        return {"token": token, "decision": prompt_decision, "old_count": stat_count(old_stats),
                "new_count": stat_count(stats),
                "changes": describe_changes(old_stats, old_types, updated_stats, updated_types)}
    cursor.execute("UPDATE item_data SET aug_types_json = %s, stats_json = %s WHERE item_id = %s",
                   (json.dumps(updated_types), json.dumps(updated_stats, ensure_ascii=False), item_id))
    return None


@app.route("/uploads/<int:upload_id>/items/<int:row_index>/icon", methods=["GET", "POST"])
def select_icon(upload_id, row_index):
    try:
        row = screenshot_item(upload_id, row_index)
        with connect() as connection:
            with connection.cursor() as cursor:
                screenshot_id = request.form.get("screenshot_id", "")
                if request.method == "POST":
                    if not screenshot_id.isascii() or not screenshot_id.isdigit() or len(screenshot_id) > 20:
                        raise ValueError("Invalid screenshot reference. Reload and select the icon again.")
                    cursor.execute("SELECT id, image_data FROM item_screenshots WHERE item_id = %s AND id = %s",
                                   (row["item_id"], int(screenshot_id)))
                else:
                    cursor.execute("SELECT id, image_data FROM item_screenshots WHERE item_id = %s ORDER BY id DESC LIMIT 1",
                                   (row["item_id"],))
                screenshot = cursor.fetchone()
                if not screenshot:
                    abort(404)
                if request.method == "POST":
                    if request.form.get("confirmed") != "yes":
                        raise ValueError("Confirm that the selected icon belongs to this item.")
                    image, _ = load_screenshot(screenshot["image_data"])
                    icon = crop_icon(image, request.form)
                    if icon is None:
                        raise ValueError("Select an icon to save.")
                    store_icon(cursor, row["item_id"], icon)
                    connection.commit()
                    flash("Item icon saved.", "success")
                    return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))
        return render_template("select_icon.html", row=row, upload_id=upload_id, row_index=row_index,
                               screenshot_id=screenshot["id"], error=None)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("select_icon", upload_id=upload_id, row_index=row_index))
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Unable to select item icon")
        return "Unable to save or load item icon. Check the server logs.", 503


@app.route("/uploads/<int:upload_id>/screenshots")
def screenshots(upload_id):
    try:
        data = dashboard(upload_id)
        if data is None:
            abort(404)
        items = []
        for row in data["rows"]:
            if row["item_id"]:
                is_equipment = row["section"] == "inventory" and row["parent"] is None and row["location"] in EQUIPMENT
                children = [child for child in data["rows"] if child["parent"] == row["index"]]
                items.append({"index": row["index"], "id": row["item_id"], "name": row["name"],
                              "location": row["location"], "is_equipment": is_equipment,
                              "children": [{"location": child["location"], "name": child["name"],
                                            "item_id": child["item_id"]} for child in children]})
        return render_template("screenshots.html", upload_id=upload_id, items=items)
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load screenshot importer")
        return "Unable to load inventory. Check the server logs.", 503


@app.route("/uploads/<int:upload_id>/screenshots/recognize", methods=["POST"])
def screenshots_recognize(upload_id):
    try:
        data = dashboard(upload_id)
        if data is None:
            abort(404)
        image = request.files.get("screenshot")
        if not image or not image.filename:
            raise ValueError("Choose an item window to recognize.")
        text, _ = recognize_screenshot(image.read())
        stats, types = extract_candidates(text)
        items = {}
        for row in data["rows"]:
            if row["item_id"] and row["item_id"] not in items:
                items[row["item_id"]] = {"index": row["index"], "id": row["item_id"], "name": row["name"]}
        return jsonify(raw_text=text, name_match_text=item_name_text(text), stats=stats, types=types,
                       name_suggestions=suggest_item_names(text, items.values()))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        app.logger.error("Screenshot OCR failed: %s", exc)
        return jsonify(error=str(exc)), 500
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Screenshot recognition failed")
        return jsonify(error="Unable to process screenshot. Check the server logs."), 503


@app.route("/uploads/<int:upload_id>/screenshots/save", methods=["POST"])
def screenshots_save(upload_id):
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError("Confirm the item, crop, and recognized values before saving.")
        index_text = request.form.get("row_index", "")
        if not index_text.isascii() or not index_text.isdigit():
            raise ValueError("Select an item from the inventory.")
        data = dashboard(upload_id)
        index = int(index_text)
        if data is None or index >= len(data["rows"]) or not data["rows"][index]["item_id"]:
            abort(404)
        row = data["rows"][index]
        image_file = request.files.get("screenshot")
        if not image_file or not image_file.filename:
            raise ValueError("Choose an item window to save.")
        image, _ = load_screenshot(image_file.read())
        icon = crop_icon(image, request.form)
        output = io.BytesIO()
        image.save(output, format="PNG")
        save_stats = request.form.get("save_stats") == "yes"
        verify_observation = request.form.get("verify_observation") == "yes"
        if verify_observation and not (row["section"] == "inventory" and row["parent"] is None
                                       and row["location"] in EQUIPMENT):
            raise ValueError("Verified item observations are only supported for equipped items.")
        if save_stats or verify_observation:
            stats, types = validate_review(request.form.get("stats_json", ""),
                                           request.form.get("types", ""),
                                           request.form.get("raw_text", ""))
        if verify_observation:
            augments = []
            for child in data["rows"]:
                if child["parent"] == index and child["item_id"]:
                    match = SLOT.fullmatch(child["location"])
                    if not match:
                        raise ValueError("Unable to identify an installed augment socket.")
                    augments.append({"item_id": child["item_id"], "name": child["name"],
                                     "socket": int(match.group(2)),
                                     "socket_type": socket_type(stats, int(match.group(2)))})
        with connect() as connection:
            with connection.cursor() as cursor:
                if save_stats:
                    conflict = update_screenshot_catalog(cursor, row["item_id"], stats, types,
                                                         request.form.get("overwrite_token", ""))
                    if conflict:
                        return jsonify(error="Existing item stats require confirmation before updating.",
                                       conflict=conflict), 409
                cursor.execute("INSERT INTO item_screenshots (item_id, image_data) VALUES (%s, %s)",
                               (row["item_id"], output.getvalue()))
                if verify_observation:
                    cursor.execute(
                        "INSERT INTO item_stat_observations "
                        "(upload_id, row_index, item_id, screenshot_id, stats_json, augments_json) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (upload_id, index, row["item_id"], cursor.lastrowid,
                         json.dumps(stats, ensure_ascii=False), json.dumps(augments, ensure_ascii=False)))
                if icon is not None:
                    store_icon(cursor, row["item_id"], icon)
            connection.commit()
        return jsonify(message="Item screenshot saved.", item_url=url_for(
            "item_detail", upload_id=upload_id, row_index=row["index"]))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            return jsonify(error="Item data changed during the save. Retry to compare the latest values."), 409
        app.logger.exception("Unable to save item screenshot")
        return jsonify(error="Unable to save screenshot. Check the server logs."), 503
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Unable to save item screenshot")
        return jsonify(error="Unable to save screenshot. Check the server logs."), 503


def screenshot_item(upload_id, row_index):
    data = dashboard(upload_id)
    if data is None or row_index >= len(data["rows"]) or not data["rows"][row_index]["item_id"]:
        abort(404)
    return data["rows"][row_index]


@app.route("/uploads/<int:upload_id>/items/<int:row_index>/screenshot", methods=["POST"])
def screenshot_review(upload_id, row_index):
    try:
        row = screenshot_item(upload_id, row_index)
        image = request.files.get("screenshot")
        if not image or not image.filename:
            raise ValueError("Choose a PNG or JPEG screenshot.")
        image_data = image.read()
        text, image_format = recognize_screenshot(image_data)
        stats, types = extract_candidates(text)
        preview = f"data:image/{image_format};base64," + base64.b64encode(image_data).decode("ascii")
        return render_template("screenshot_review.html", row=row, upload_id=upload_id, row_index=row_index,
                               image=preview, raw_text=text, stats_json=json.dumps(stats, indent=2),
                               types_text="|".join(map(str, types)), error=None)
    except ValueError as exc:
        flash(str(exc), "error")
    except RuntimeError as exc:
        app.logger.error("Screenshot OCR failed: %s", exc)
        flash(str(exc), "error")
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Screenshot review failed")
        flash("Database error: screenshot was not processed. Check the server logs.", "error")
    return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))


@app.route("/uploads/<int:upload_id>/items/<int:row_index>/screenshot/save", methods=["POST"])
def screenshot_save(upload_id, row_index):
    raw_text = request.form.get("raw_text", "")
    stats_json = request.form.get("stats_json", "")
    types_text = request.form.get("types", "")
    try:
        row = screenshot_item(upload_id, row_index)
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load item for screenshot review")
        flash("Could not load the item; screenshot data was not saved. Check the server logs.", "error")
        return redirect(url_for("index"))
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError("Confirm that the screenshot and recognized values match this item.")
        stats, types = validate_review(stats_json, types_text, raw_text)
        with connect() as connection:
            with connection.cursor() as cursor:
                conflict = update_screenshot_catalog(cursor, row["item_id"], stats, types,
                                                     request.form.get("overwrite_token", ""))
                if conflict:
                    return render_template("screenshot_review.html", row=row, upload_id=upload_id,
                                           row_index=row_index, image=None, raw_text=raw_text,
                                           stats_json=stats_json, types_text=types_text, error=None,
                                           conflict=conflict), 409
            connection.commit()
        flash("Reviewed screenshot data saved.", "success")
        return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            flash("Item data changed during the save. Retry to compare the latest values.", "error")
        else:
            app.logger.exception("Unable to save reviewed screenshot")
            flash("Database error: screenshot data was not saved. Check the server logs.", "error")
        return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))
    except ValueError as exc:
        return render_template("screenshot_review.html", row=row, upload_id=upload_id, row_index=row_index,
                               image=None, raw_text=raw_text, stats_json=stats_json,
                               types_text=types_text, error=str(exc)), 400
    except (pymysql.MySQLError, OSError):
        app.logger.exception("Unable to save reviewed screenshot")
        flash("Database error: screenshot data was not saved. Check the server logs.", "error")
        return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))


@app.route("/upload", methods=["POST"])
def upload_inventory():
    upload = request.files.get("inventory")
    if not upload or not upload.filename:
        flash("Choose an inventory text file first.", "error")
    else:
        try:
            save_upload(upload)
            flash("Inventory imported successfully.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        except (pymysql.MySQLError, OSError):
            app.logger.exception("Inventory upload failed")
            flash("Database error: inventory was not saved. Check the server logs and database configuration.", "error")
    return redirect(url_for("index"))


@app.route("/item-data", methods=["POST"])
def upload_item_data():
    upload = request.files.get("items")
    if not upload or not upload.filename:
        flash("Choose an item-data CSV first.", "error")
    else:
        try:
            count = save_items(upload)
            flash(f"Imported item data for {count} items.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        except (pymysql.MySQLError, OSError):
            app.logger.exception("Item-data import failed")
            flash("Database error: item data was not saved. Check the server logs.", "error")
    return redirect(url_for("index"))


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    if request.endpoint in ("screenshots_recognize", "screenshots_save"):
        return jsonify(error="Upload exceeds the 10 MB limit; select a smaller crop."), 413
    flash("Upload exceeds the 10 MB limit.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
