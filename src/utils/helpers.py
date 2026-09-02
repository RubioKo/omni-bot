import re

DURATION_PATTERN = re.compile(r"(\d+)\s*(min|s|m|h|d)", re.IGNORECASE)


def parse_duration(text: str) -> int:
    total = 0
    for match in DURATION_PATTERN.finditer(text):
        num = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "s":
            total += num
        elif unit in ("m", "min"):
            total += num * 60
        elif unit == "h":
            total += num * 3600
        elif unit == "d":
            total += num * 86400
    return total
