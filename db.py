import json
import pymysql
from pymysql.cursors import DictCursor

from config import get_setting


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
        host=get_setting("EQINV_DB_HOST", "127.0.0.1"),
        port=int(get_setting("EQINV_DB_PORT", "3306")),
        user=get_setting("EQINV_DB_USER", "eqinv"),
        password=get_setting("EQINV_DB_PASSWORD"),
        database=get_setting("EQINV_DB_NAME", "eqinv"),
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
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_accounts (
                discord_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
            ) ENGINE=InnoDB
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS upload_owners (
                upload_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                discord_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                INDEX (discord_id, upload_id)
            ) ENGINE=InnoDB
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS character_profiles (
                discord_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                identity_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                character_name VARCHAR(255) NOT NULL,
                server_name VARCHAR(255) NOT NULL,
                upload_id BIGINT UNSIGNED NOT NULL,
                PRIMARY KEY (discord_id, identity_hash),
                UNIQUE KEY (upload_id)
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_data (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                aug_types_json TEXT NOT NULL,
                stats_json LONGTEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                name LONGTEXT NOT NULL,
                first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lucy_items (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                name LONGTEXT NOT NULL
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_screenshots (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                item_id INT UNSIGNED NOT NULL,
                image_data LONGBLOB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX (item_id, id)
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_icons (
                item_id INT UNSIGNED NOT NULL PRIMARY KEY,
                image_data MEDIUMBLOB NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_stat_observations (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                upload_id BIGINT UNSIGNED NOT NULL,
                row_index INT UNSIGNED NOT NULL,
                item_id INT UNSIGNED NOT NULL,
                screenshot_id BIGINT UNSIGNED NOT NULL,
                stats_json LONGTEXT NOT NULL,
                augments_json LONGTEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX (upload_id, row_index, id)
            ) ENGINE=InnoDB CHARACTER SET utf8mb4
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
