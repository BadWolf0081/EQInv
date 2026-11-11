import re


SOCKET_KEY = re.compile(r"socket_([1-9][0-9]*)_type")


def socket_number(key):
    match = SOCKET_KEY.fullmatch(key)
    if match and 1 <= int(match.group(1)) <= 255:
        return int(match.group(1))
    return None


def socket_type(stats, number):
    value = stats.get(f"socket_{number}_type")
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 255:
        return value
    return None
