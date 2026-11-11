import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import db
import discord_auth


ROOT = Path(__file__).resolve().parent.parent


class ConfigurationTests(unittest.TestCase):
    def test_example_lists_every_setting_and_can_be_parsed(self):
        values = config.load_config(ROOT / "config.example.ini")
        self.assertEqual(set(values), config.SETTING_NAMES)

    def test_environment_overrides_file_and_defaults(self):
        with patch.object(config, "FILE_SETTINGS", {"EQINV_DB_HOST": "file-host"}), \
             patch.dict(os.environ, {"EQINV_DB_HOST": "env-host"}, clear=True):
            self.assertEqual(config.get_setting("EQINV_DB_HOST"), "env-host")
            self.assertEqual(config.get_setting("EQINV_DB_PORT", "3306"), "3306")
        with patch.object(config, "FILE_SETTINGS", {"EQINV_DB_HOST": "file-host"}), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.get_setting("EQINV_DB_HOST"), "file-host")

    def test_missing_and_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            self.assertEqual(config.load_config(path), {})
            for text in ("not an ini", "[eqinv]\nUNKNOWN = value", "[wrong]\nvalue = 1",
                         "[eqinv]\nEQINV_DB_HOST = one\nEQINV_DB_HOST = two"):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    config.load_config(path)

    def test_ini_values_feed_database_and_discord(self):
        values = {
            "EQINV_DB_PASSWORD": "literal%password",
            "EQINV_DB_PORT": "3307",
            "EQINV_DISCORD_CLIENT_ID": "111",
            "EQINV_DISCORD_CLIENT_SECRET": "client-secret",
            "EQINV_DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
            "EQINV_DISCORD_GUILD_ID": "222",
            "EQINV_DISCORD_ROLE_ID": "333",
            "EQINV_DISCORD_BOT_TOKEN": "bot-secret",
            "EQINV_SECRET_KEY": "x" * 40,
        }
        with patch.object(config, "FILE_SETTINGS", values), patch.dict(os.environ, {}, clear=True), \
             patch("db.pymysql.connect") as connect:
            db.connect()
            self.assertEqual(connect.call_args.kwargs["password"], "literal%password")
            self.assertEqual(connect.call_args.kwargs["port"], 3307)
            self.assertEqual(discord_auth.settings()["EQINV_DISCORD_CLIENT_ID"], "111")

    def test_startup_uses_file_secret_and_secure_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in ROOT.glob("*.py"):
                shutil.copyfile(source, root / source.name)
            path = root / "config.ini"
            path.write_text("[eqinv]\nEQINV_SECRET_KEY = " + "x" * 40 +
                            "\nEQINV_DISCORD_REDIRECT_URI = https://example.test/auth/discord/callback\n"
                            "EQINV_DB_PASSWORD = literal%password\n",
                            encoding="utf-8")
            code = (
                "import app, db; "
                "from unittest.mock import patch; "
                "assert app.app.secret_key == 'x' * 40; "
                "assert app.app.config['SESSION_COOKIE_SECURE'] is True; "
                "mock = patch('db.pymysql.connect').start(); "
                "db.connect(); "
                "assert mock.call_args.kwargs['password'] == 'literal%password'"
            )
            environment = {key: value for key, value in os.environ.items() if not key.startswith("EQINV_")}
            result = subprocess.run([sys.executable, "-c", code], cwd=root,
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
