import configparser
import os
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().with_name("config.ini")
SETTING_NAMES = frozenset({
    "EQINV_DB_HOST", "EQINV_DB_PORT", "EQINV_DB_NAME", "EQINV_DB_USER",
    "EQINV_DB_PASSWORD", "EQINV_SECRET_KEY", "EQINV_DISCORD_CLIENT_ID",
    "EQINV_DISCORD_CLIENT_SECRET", "EQINV_DISCORD_REDIRECT_URI",
    "EQINV_DISCORD_GUILD_ID", "EQINV_DISCORD_ROLE_ID", "EQINV_DISCORD_BOT_TOKEN",
    "EQINV_ALLOW_INSECURE_LAN_HTTP",
})


def load_config(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with path.open(encoding="utf-8-sig") as file:
            parser.read_file(file)
    except FileNotFoundError:
        return {}
    except (configparser.Error, UnicodeError):
        raise ValueError(f"Unable to parse {path}; check its INI syntax.") from None
    if parser.defaults() or parser.sections() != ["eqinv"]:
        raise ValueError(f"{path} must contain exactly one [eqinv] section.")
    values = dict(parser.items("eqinv"))
    unknown = set(values) - SETTING_NAMES
    if unknown:
        raise ValueError(f"Unknown settings in {path}: {', '.join(sorted(unknown))}")
    return values


FILE_SETTINGS = load_config(CONFIG_PATH)


def get_setting(name, default=""):
    return os.environ.get(name, FILE_SETTINGS.get(name, default))
