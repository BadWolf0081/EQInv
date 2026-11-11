ROMAN_DISTILLERS = frozenset(
    tens + ones for tens in ("", "X", "XX", "XXX")
    for ones in ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX")
    if tens + ones and (tens != "XXX" or not ones)
)


def valid_distiller_class(value):
    return isinstance(value, str) and (value == "" or value == "Perfected only" or value in ROMAN_DISTILLERS)
