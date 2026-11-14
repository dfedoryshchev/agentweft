"""a provider key never reaches a file the run writes.

an answer, a gate's output or a provider's error can quote one: a model that
printed its environment, a test that echoed it, a cli that named the key it
was refused with. whatever writes a recording or the run's record passes its
text through here first.
"""
import re
import threading

# the key prefix and at least a few of its characters, so the bare prefix in
# prose is left alone
KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
SAID = "sk-ant-REDACTED"
# a key of another shape (a gateway's bearer token, a proxy's key) is
# redacted by its value: each value a key file handed, this process
HANDED = set()
# shorter than this, a value is ordinary text more often than a key, and
# redacting it would blank a word out of every later line of the process: a
# key file holding less is refused (`connectors.key_refused`)
SHORTEST = 20
lock = threading.Lock()


def handed(value):
    """remembers `value`, a key just handed to a step, so it is redacted
    wherever it shows up later."""
    if isinstance(value, str) and len(value) >= SHORTEST:
        with lock:
            HANDED.add(value)


def redact(text):
    """-> text with every provider key in it replaced; anything that is not
    text, or text with no key in it, is handed back as it came."""
    if not isinstance(text, str):
        return text
    out = KEY.sub(SAID, text) if "sk-ant-" in text else text
    with lock:
        values = sorted(HANDED, key=len, reverse=True)
    for value in values:
        if value in out:
            out = out.replace(value, SAID)
    return text if out == text else out


def redacted(value):
    """-> value with every string inside it, at any depth, redacted."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redacted(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redacted(v) for v in value)
    return value
