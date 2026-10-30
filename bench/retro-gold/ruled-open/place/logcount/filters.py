from datetime import datetime


def parse_bound(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def since(entries, bound):
    return [e for e in entries if e.time >= bound]
