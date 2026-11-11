import unittest
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import discord_auth
from app import app


CONFIG = {
    "EQINV_SECRET_KEY": "x" * 40, "EQINV_DISCORD_CLIENT_ID": "111",
    "EQINV_DISCORD_CLIENT_SECRET": "client-secret", "EQINV_DISCORD_REDIRECT_URI": "https://example.test/auth/discord/callback",
    "EQINV_DISCORD_GUILD_ID": "222", "EQINV_DISCORD_ROLE_ID": "333",
    "EQINV_DISCORD_BOT_TOKEN": "bot-secret",
}


class DiscordAuthTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY=CONFIG["EQINV_SECRET_KEY"])
        self.settings = patch("app.discord_auth.settings", return_value=CONFIG)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = app.test_client()

    def test_login_state_callback_and_role_revocation(self):
        response = self.client.get("/")
        self.assertIn(b"Log in with Discord", response.data)
        self.assertEqual(self.client.get("/uploads/123/augments").status_code, 302)
        response = self.client.get("/auth/discord")
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query["scope"], ["identify"])
        state = query["state"][0]
        self.assertEqual(self.client.get("/auth/discord/callback?state=bad&code=x").status_code, 400)
        self.assertEqual(self.client.get("/auth/discord/callback?state=" + state + "&code=x").status_code, 400)
        state = parse_qs(urlsplit(self.client.get("/auth/discord").location).query)["state"][0]
        with patch("app.discord_auth.identify", return_value="123"), patch("app.discord_auth.is_authorized", return_value=True):
            self.assertEqual(self.client.get("/auth/discord/callback?state=" + state + "&code=x").status_code, 302)
        with self.client.session_transaction() as session:
            session["role_checked_at"] = 0
        with patch("app.discord_auth.is_authorized", return_value=False):
            self.assertEqual(self.client.get("/items/11/icon").status_code, 403)
        with self.client.session_transaction() as session:
            self.assertNotIn("discord_id", session)

    def test_private_upload_routes_deny_other_users(self):
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
            session["csrf_token"] = "token"
        with patch("app.discord_auth.is_authorized", return_value=True), \
             patch("app.profiles.owns_upload", return_value=False) as owns:
            for path in ("/uploads/42/augments", "/uploads/42/items/1",
                         "/uploads/42/items/1/icon", "/uploads/42/screenshots"):
                self.assertEqual(self.client.get(path).status_code, 404)
            for path in ("/uploads/42/items/1/icon", "/uploads/42/screenshots/recognize",
                         "/uploads/42/screenshots/save", "/uploads/42/items/1/screenshot",
                         "/uploads/42/items/1/screenshot/save"):
                self.assertEqual(self.client.post(path, data={"csrf_token": "token"}).status_code, 404)
            owns.assert_called_with("123", 42)

    def test_logout_requires_csrf_and_clears_session(self):
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
            session["csrf_token"] = "token"
        with patch("app.discord_auth.is_authorized", return_value=True):
            self.assertEqual(self.client.post("/logout").status_code, 400)
            self.assertEqual(self.client.post("/logout", data={"csrf_token": "token"}).status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("discord_id", session)

    def test_shared_items_require_login_but_not_upload_ownership(self):
        self.assertEqual(self.client.get("/items/11/icon").status_code, 302)
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
        with patch("app.discord_auth.is_authorized", return_value=True), \
             patch("app.profiles.owns_upload") as owns, \
             patch("app.connect", side_effect=OSError("test database unavailable")):
            self.assertEqual(self.client.get("/items/11/icon").status_code, 503)
            owns.assert_not_called()

    def test_configuration_rejects_bad_values(self):
        self.settings.stop()
        with patch.dict("os.environ", CONFIG, clear=True):
            self.assertEqual(discord_auth.settings()["EQINV_DISCORD_ROLE_ID"], "333")
        for key, value in (("EQINV_SECRET_KEY", "short"), ("EQINV_DISCORD_ROLE_ID", "x"),
                           ("EQINV_DISCORD_CLIENT_ID", "1" * 21),
                           ("EQINV_DISCORD_REDIRECT_URI", "http://example.test/callback"),
                           ("EQINV_DISCORD_REDIRECT_URI", "https://[bad")):
            invalid = dict(CONFIG, **{key: value})
            with patch.dict("os.environ", invalid, clear=True):
                with self.assertRaises(discord_auth.DiscordError):
                    discord_auth.settings()

    def test_insecure_lan_callback_requires_explicit_opt_in_and_private_ip(self):
        self.settings.stop()
        with patch("config.FILE_SETTINGS", {}):
            for url, flag, allowed in (
                ("http://10.10.11.3:5000/auth/discord/callback", "true", True),
                ("http://192.168.1.3:5000/auth/discord/callback", "true", True),
                ("http://172.16.0.5:5000/auth/discord/callback", "true", True),
                ("http://10.10.11.3:5000/auth/discord/callback", "false", False),
                ("http://10.10.11.3:5000/auth/discord/callback", "yes", False),
                ("http://8.8.8.8:5000/auth/discord/callback", "true", False),
                ("http://example.test:5000/auth/discord/callback", "true", False),
                ("ftp://10.10.11.3/callback", "true", False),
            ):
                with self.subTest(url=url, flag=flag), patch.dict(
                    "os.environ", dict(CONFIG, EQINV_DISCORD_REDIRECT_URI=url,
                                       EQINV_ALLOW_INSECURE_LAN_HTTP=flag), clear=True
                ):
                    if allowed:
                        self.assertEqual(discord_auth.settings()["EQINV_DISCORD_REDIRECT_URI"], url)
                    else:
                        with self.assertRaises(discord_auth.DiscordError):
                            discord_auth.settings()

    def test_lan_login_uses_the_configured_callback(self):
        self.settings.stop()
        callback = "http://10.10.11.3:5000/auth/discord/callback"
        environment = dict(CONFIG, EQINV_DISCORD_REDIRECT_URI=callback,
                           EQINV_ALLOW_INSECURE_LAN_HTTP="true")
        with patch("config.FILE_SETTINGS", {}), patch.dict("os.environ", environment, clear=True):
            self.assertEqual(self.client.get("/", base_url="http://10.10.11.3:5000").status_code, 200)
            response = self.client.get("/auth/discord", base_url="http://10.10.11.3:5000")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(parse_qs(urlsplit(response.location).query)["redirect_uri"], [callback])

    def test_missing_role_and_discord_failure_deny_access(self):
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
        with patch("app.discord_auth.is_authorized", side_effect=discord_auth.DiscordError("failure")):
            self.assertEqual(self.client.get("/").status_code, 503)
        with patch("app.discord_auth.is_authorized", return_value=False):
            self.assertEqual(self.client.get("/").status_code, 403)

    def test_role_recheck_is_bounded(self):
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
            session["role_checked_at"] = time.time()
        with patch("app.discord_auth.is_authorized", return_value=False) as authorized, \
             patch("app.profiles.list_profiles", return_value=[]):
            self.assertEqual(self.client.get("/").status_code, 200)
            authorized.assert_not_called()
        with self.client.session_transaction() as session:
            session["role_checked_at"] = time.time() - 31
        with patch("app.discord_auth.is_authorized", return_value=False):
            self.assertEqual(self.client.get("/").status_code, 403)

    def test_profile_selector_cannot_open_another_users_id(self):
        with self.client.session_transaction() as session:
            session["discord_id"] = "123"
        with patch("app.discord_auth.is_authorized", return_value=True), \
             patch("app.profiles.list_profiles", return_value=[{"upload_id": 1}]):
            self.assertEqual(self.client.get("/?profile=2").status_code, 404)

    def test_bot_role_check_and_rejected_member(self):
        with patch("discord_auth.api_json", return_value={"roles": ["333"]}) as api:
            self.assertTrue(discord_auth.is_authorized(CONFIG, "123"))
            self.assertIn("/guilds/222/members/123", api.call_args.args[0])
        with patch("discord_auth.api_json", return_value={"roles": []}):
            self.assertFalse(discord_auth.is_authorized(CONFIG, "123"))
        with patch("discord_auth.api_json", return_value=None):
            self.assertFalse(discord_auth.is_authorized(CONFIG, "123"))
        with patch("discord_auth.api_json", return_value={}):
            with self.assertRaises(discord_auth.DiscordError):
                discord_auth.is_authorized(CONFIG, "123")

    def test_api_errors_identify_the_failing_stage_without_credentials(self):
        error = discord_auth.DiscordError("Discord API request failed (HTTP 403).")
        for responses, operation, label in (
            ([error], lambda: discord_auth.identify(CONFIG, "private-code"), "OAuth token exchange"),
            ([{"access_token": "private-token"}, error],
             lambda: discord_auth.identify(CONFIG, "private-code"), "Discord user lookup"),
            ([error], lambda: discord_auth.is_authorized(CONFIG, "123"), "Discord server member lookup"),
        ):
            with self.subTest(stage=label), patch("discord_auth.api_json", side_effect=responses):
                with self.assertRaises(discord_auth.DiscordError) as raised:
                    operation()
                message = str(raised.exception)
                self.assertIn(label, message)
                self.assertIn("HTTP 403", message)
                for secret in ("private-code", "private-token", "bot-secret", "client-secret"):
                    self.assertNotIn(secret, message)


if __name__ == "__main__":
    unittest.main()
