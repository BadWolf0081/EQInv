import json
import logging
import os
import secrets

import click
import pymysql
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from db import catalog_items, connect, initialize
from inventory import EQUIPMENT, parse_inventory, parse_item_data

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


def dashboard():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, filename, character_name, server_name, uploaded_at, rows_json "
                           "FROM uploads ORDER BY id DESC LIMIT 1")
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
