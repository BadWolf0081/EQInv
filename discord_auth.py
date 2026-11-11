import json
import ipaddress
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from config import get_setting


API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/, 1.0) EQInv/1.0"
REQUIRED = ("EQINV_DISCORD_CLIENT_ID", "EQINV_DISCORD_CLIENT_SECRET",
            "EQINV_DISCORD_REDIRECT_URI", "EQINV_DISCORD_GUILD_ID",
            "EQINV_DISCORD_ROLE_ID", "EQINV_DISCORD_BOT_TOKEN", "EQINV_SECRET_KEY")
PRIVATE_LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in
                             ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


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
    insecure_lan = get_setting("EQINV_ALLOW_INSECURE_LAN_HTTP", "false").strip().lower()
    if insecure_lan not in ("true", "false"):
        raise DiscordError("EQINV_ALLOW_INSECURE_LAN_HTTP must be true or false.")
    private_ip = False
    try:
        address = ipaddress.ip_address(uri.hostname)
        private_ip = isinstance(address, ipaddress.IPv4Address) and any(
            address in network for network in PRIVATE_LAN_NETWORKS)
    except ValueError:
        pass
    local_http = uri.scheme == "http" and uri.hostname in ("localhost", "127.0.0.1", "::1")
    lan_http = uri.scheme == "http" and insecure_lan == "true" and private_ip
    if uri.scheme != "https" and not (local_http or lan_http):
        raise DiscordError("Discord redirect URI must use HTTPS except on localhost or an explicitly enabled private LAN IP.")
    return config


def api_json(url, headers=None, form=None):
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers, data=urlencode(form).encode() if form is not None else None)
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
    try:
        token = api_json(API + "/oauth2/token", form={
            "client_id": config["EQINV_DISCORD_CLIENT_ID"],
            "client_secret": config["EQINV_DISCORD_CLIENT_SECRET"],
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": config["EQINV_DISCORD_REDIRECT_URI"],
        })
    except DiscordError as exc:
        raise DiscordError(f"OAuth token exchange: {exc}") from exc
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str):
        raise DiscordError("OAuth token exchange: Discord did not return an access token.")
    try:
        user = api_json(API + "/users/@me", headers={"Authorization": "Bearer " + token["access_token"]})
    except DiscordError as exc:
        raise DiscordError(f"Discord user lookup: {exc}") from exc
    if (not isinstance(user, dict) or not isinstance(user.get("id"), str)
            or not user["id"].isascii() or not user["id"].isdigit() or len(user["id"]) > 20):
        raise DiscordError("Discord did not return a valid user ID.")
    return user["id"]


def is_authorized(config, user_id):
    try:
        member = api_json(f"{API}/guilds/{config['EQINV_DISCORD_GUILD_ID']}/members/{user_id}",
                          headers={"Authorization": "Bot " + config["EQINV_DISCORD_BOT_TOKEN"]})
    except DiscordError as exc:
        raise DiscordError(f"Discord server member lookup: {exc}") from exc
    if member is None:
        return False
    if not isinstance(member, dict) or not isinstance(member.get("roles"), list):
        raise DiscordError("Discord returned an invalid guild member response.")
    return config["EQINV_DISCORD_ROLE_ID"] in member["roles"]
