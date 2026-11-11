import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from config import get_setting


API = "https://discord.com/api/v10"
REQUIRED = ("EQINV_DISCORD_CLIENT_ID", "EQINV_DISCORD_CLIENT_SECRET",
            "EQINV_DISCORD_REDIRECT_URI", "EQINV_DISCORD_GUILD_ID",
            "EQINV_DISCORD_ROLE_ID", "EQINV_DISCORD_BOT_TOKEN", "EQINV_SECRET_KEY")


class DiscordError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def settings():
    config = {name: get_setting(name) for name in REQUIRED}
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise DiscordError("Discord login is not configured. Missing: " + ", ".join(missing))
    if len(config["EQINV_SECRET_KEY"]) < 32:
        raise DiscordError("EQINV_SECRET_KEY must contain at least 32 characters.")
    for key in ("EQINV_DISCORD_CLIENT_ID", "EQINV_DISCORD_GUILD_ID", "EQINV_DISCORD_ROLE_ID"):
        if not config[key].isascii() or not config[key].isdigit() or len(config[key]) > 20:
            raise DiscordError(f"{key} must be a Discord numeric ID.")
    try:
        uri = urlsplit(config["EQINV_DISCORD_REDIRECT_URI"])
        port = uri.port
    except ValueError as exc:
        raise DiscordError("Discord redirect URI must be an absolute callback URL.") from exc
    if not uri.hostname or uri.fragment or uri.query or uri.username or uri.password:
        raise DiscordError("Discord redirect URI must be an absolute callback URL.")
    if port == 0:
        raise DiscordError("Discord redirect URI must have a valid port.")
    if uri.scheme != "https" and not (uri.scheme == "http" and uri.hostname in ("localhost", "127.0.0.1", "::1")):
        raise DiscordError("Discord redirect URI must use HTTPS except on localhost.")
    return config


def api_json(url, headers=None, form=None):
    request = Request(url, headers=headers or {}, data=urlencode(form).encode() if form is not None else None)
    if form is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise DiscordError("Discord returned an oversized response.")
        return json.loads(data)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise DiscordError(f"Discord API request failed (HTTP {exc.code}).") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscordError("Unable to reach Discord or read its response.") from exc


def authorize_url(config, state):
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "client_id": config["EQINV_DISCORD_CLIENT_ID"], "redirect_uri": config["EQINV_DISCORD_REDIRECT_URI"],
        "response_type": "code", "scope": "identify", "state": state,
    })


def identify(config, code):
    token = api_json(API + "/oauth2/token", form={
        "client_id": config["EQINV_DISCORD_CLIENT_ID"],
        "client_secret": config["EQINV_DISCORD_CLIENT_SECRET"],
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": config["EQINV_DISCORD_REDIRECT_URI"],
    })
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str):
        raise DiscordError("Discord did not return an access token.")
    user = api_json(API + "/users/@me", headers={"Authorization": "Bearer " + token["access_token"]})
    if (not isinstance(user, dict) or not isinstance(user.get("id"), str)
            or not user["id"].isascii() or not user["id"].isdigit() or len(user["id"]) > 20):
        raise DiscordError("Discord did not return a valid user ID.")
    return user["id"]


def is_authorized(config, user_id):
    member = api_json(f"{API}/guilds/{config['EQINV_DISCORD_GUILD_ID']}/members/{user_id}",
                      headers={"Authorization": "Bot " + config["EQINV_DISCORD_BOT_TOKEN"]})
    if member is None:
        return False
    if not isinstance(member, dict) or not isinstance(member.get("roles"), list):
        raise DiscordError("Discord returned an invalid guild member response.")
    return config["EQINV_DISCORD_ROLE_ID"] in member["roles"]
