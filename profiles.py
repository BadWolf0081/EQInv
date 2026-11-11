import hashlib
import json

from db import catalog_items, connect
from inventory import parse_inventory


LIMIT = 10


def identity_key(character, server):
    if not character or not server or not character.strip() or not server.strip():
        raise ValueError("Use a Character_Server-Inventory.txt filename to identify the character and server.")
    if len(character) > 255 or len(server) > 255:
        raise ValueError("Character or server name is too long.")
    identity = json.dumps([character.strip().casefold(), server.strip().casefold()], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def lock_account(cursor, user_id):
    cursor.execute("INSERT INTO discord_accounts (discord_id) VALUES (%s) ON DUPLICATE KEY UPDATE discord_id=VALUES(discord_id)", (user_id,))
    cursor.execute("SELECT discord_id FROM discord_accounts WHERE discord_id = %s FOR UPDATE", (user_id,))
    cursor.fetchone()


def save_profile(upload, user_id):
    parsed = parse_inventory(upload.read(), upload.filename)
    if len(parsed["filename"]) > 255:
        raise ValueError("Filename is too long.")
    key = identity_key(parsed["character"], parsed["server"])
    with connect() as connection:
        with connection.cursor() as cursor:
            lock_account(cursor, user_id)
            cursor.execute("SELECT identity_hash FROM character_profiles WHERE discord_id = %s AND identity_hash = %s",
                           (user_id, key))
            exists = cursor.fetchone() is not None
            cursor.execute("SELECT COUNT(*) AS count FROM character_profiles WHERE discord_id = %s", (user_id,))
            if not exists and cursor.fetchone()["count"] >= LIMIT:
                raise ValueError("You already have 10 character profiles. Update an existing character instead.")
            cursor.execute(
                "INSERT INTO uploads (filename, character_name, server_name, raw_text, rows_json) VALUES (%s, %s, %s, %s, %s)",
                (parsed["filename"], parsed["character"], parsed["server"], parsed["raw"],
                 json.dumps(parsed["rows"], ensure_ascii=False)))
            upload_id = cursor.lastrowid
            cursor.execute("INSERT INTO upload_owners (upload_id, discord_id) VALUES (%s, %s)", (upload_id, user_id))
            cursor.execute(
                "INSERT INTO character_profiles (discord_id, identity_hash, character_name, server_name, upload_id) "
                "VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
                "character_name=VALUES(character_name), server_name=VALUES(server_name), upload_id=VALUES(upload_id)",
                (user_id, key, parsed["character"], parsed["server"], upload_id))
            catalog_items(cursor, parsed["rows"])
        connection.commit()
    return upload_id


def list_profiles(user_id):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT character_name, server_name, upload_id FROM character_profiles "
                           "WHERE discord_id = %s ORDER BY character_name, server_name", (user_id,))
            return cursor.fetchall()


def owns_upload(user_id, upload_id):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT upload_id FROM upload_owners WHERE discord_id = %s AND upload_id = %s",
                           (user_id, upload_id))
            return cursor.fetchone() is not None


def claim_legacy(user_id):
    with connect() as connection:
        with connection.cursor() as cursor:
            lock_account(cursor, user_id)
            cursor.execute("SELECT identity_hash FROM character_profiles WHERE discord_id = %s", (user_id,))
            existing = {row["identity_hash"] for row in cursor.fetchall()}
            cursor.execute("SELECT u.id, u.character_name, u.server_name FROM uploads u "
                           "LEFT JOIN upload_owners o ON o.upload_id = u.id WHERE o.upload_id IS NULL "
                           "ORDER BY u.id FOR UPDATE")
            uploads = cursor.fetchall()
            latest = {}
            for row in uploads:
                key = identity_key(row["character_name"], row["server_name"])
                latest[key] = row
            if existing.intersection(latest):
                raise ValueError("Existing profiles conflict with legacy uploads; no data was claimed.")
            if len(existing) + len(latest) > LIMIT:
                raise ValueError("Claim would exceed 10 profiles; no data was claimed.")
            for row in uploads:
                cursor.execute("INSERT INTO upload_owners (upload_id, discord_id) VALUES (%s, %s)", (row["id"], user_id))
            for key, row in latest.items():
                cursor.execute("INSERT INTO character_profiles "
                               "(discord_id, identity_hash, character_name, server_name, upload_id) "
                               "VALUES (%s, %s, %s, %s, %s)",
                               (user_id, key, row["character_name"], row["server_name"], row["id"]))
        connection.commit()
    return len(uploads), len(latest)
