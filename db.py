import json
import os

import pymysql
from pymysql.cursors import DictCursor


def catalog_items(cursor, rows):
    items = {}
    for row in rows:
        item_id = row["item_id"]
        if item_id:
            items.setdefault(item_id, row["name"])
    if items:
        cursor.executemany(
            "INSERT INTO items (item_id, name) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE item_id=VALUES(item_id)",
            list(items.items()),
        )


def connect():
    return pymysql.connect(
        host=os.environ.get("EQINV_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("EQINV_DB_PORT", "3306")),
        user=os.environ.get("EQINV_DB_USER", "eqinv"),
        password=os.environ.get("EQINV_DB_PASSWORD", ""),
        database=os.environ.get("EQINV_DB_NAME", "eqinv"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=5,
        init_command="SET time_zone = '+00:00'",
    )


def initialize(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                character_name VARCHAR(255),
                server_name VARCHAR(255),
                uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                raw_text LONGTEXT NOT NULL,
                rows_json LONGTEXT NOT NULL
            ) CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_data (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                aug_types_json TEXT NOT NULL,
                stats_json LONGTEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                name LONGTEXT NOT NULL,
                first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4
        """)

        # Backfill previously saved uploads in order, preserving the first name seen.
        last_id = 0
        while True:
            cursor.execute(
                "SELECT id, rows_json FROM uploads WHERE id > %s ORDER BY id LIMIT 50",
                (last_id,),
            )
            uploads = cursor.fetchall()
            if not uploads:
                break
            for upload in uploads:
                catalog_items(cursor, json.loads(upload["rows_json"]))
            last_id = uploads[-1]["id"]
    connection.commit()
