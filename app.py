import csv
import base64
import gzip
import json
import logging
import os
import secrets
from urllib.parse import urlencode

import click
import pymysql
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from db import catalog_items, connect, initialize
from inventory import EQUIPMENT, parse_inventory, parse_item_data, parse_lucy_items
from screenshot_ocr import extract_candidates, recognize_screenshot, validate_review

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024,
                  SECRET_KEY=os.environ.get("EQINV_SECRET_KEY", os.urandom(32)))
logging.basicConfig(level=logging.INFO)


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
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(f"SELECT item_id, aug_types_json, stats_json FROM item_data WHERE item_id IN ({placeholders})", ids)
                for item in cursor.fetchall():
                    catalog[item["item_id"]] = {
                        "types": json.loads(item["aug_types_json"]),
                        "stats": json.loads(item["stats_json"]),
                    }
    equipment = []
    counts = {}
    for index, row in enumerate(rows):
        row["index"] = index
        row["catalog"] = catalog.get(row["item_id"])
        if row["section"] != "inventory":
            continue
        if row["parent"] is None and row["location"] in EQUIPMENT:
            counts[row["location"]] = counts.get(row["location"], 0) + 1
            equipment.append({"index": index, "row": row, "augments": [], "number": counts[row["location"]]})
        elif equipment and row["parent"] == equipment[-1]["index"]:
            equipment[-1]["augments"].append(row)
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
    return {"upload": upload, "equipment": equipment, "augments": augments,
            "unknown_types": unknown_types, "rows": rows}


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
    try:
        data = dashboard(upload_id)
        if data is None or row_index >= len(data["rows"]) or not data["rows"][row_index]["item_id"]:
            abort(404)
        row = data["rows"][row_index]
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT item_id, name FROM lucy_items WHERE item_id = %s", (row["item_id"],))
                lucy = cursor.fetchone()
    except (pymysql.MySQLError, OSError, ValueError):
        app.logger.exception("Unable to load item details")
        return render_template("index.html", data=None, db_error=True), 503
    children = [child for child in data["rows"] if child["parent"] == row_index]
    parent = data["rows"][row["parent"]] if row["parent"] is not None else None
    allakhazam_search = "https://everquest.allakhazam.com/db/search?" + urlencode({"q": row["name"]})
    return render_template("item.html", data=data, row=row, children=children, parent=parent,
                           lucy=lucy, allakhazam_search=allakhazam_search)


def screenshot_item(upload_id, row_index):
    data = dashboard(upload_id)
    if data is None or row_index >= len(data["rows"]) or not data["rows"][row_index]["item_id"]:
        abort(404)
    return data["rows"][row_index]


@app.route("/uploads/<int:upload_id>/items/<int:row_index>/screenshot", methods=["POST"])
def screenshot_review(upload_id, row_index):
    try:
        row = screenshot_item(upload_id, row_index)
        if row["catalog"]:
            flash("This item already has catalog data; screenshot import will not overwrite it.", "error")
            return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))
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
                cursor.execute(
                    "INSERT INTO item_data (item_id, aug_types_json, stats_json) VALUES (%s, %s, %s)",
                    (row["item_id"], json.dumps(types), json.dumps(stats, ensure_ascii=False)),
                )
            connection.commit()
        flash("Reviewed screenshot data saved.", "success")
        return redirect(url_for("item_detail", upload_id=upload_id, row_index=row_index))
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            flash("This item already has catalog data; screenshot import did not overwrite it.", "error")
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
    flash("Upload exceeds the 10 MB limit.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
