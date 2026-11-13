"""a provider key never reaches a file the run writes.

an answer, a gate's output or a provider's error can quote one: a model that
printed its environment, a test that echoed it, a cli that named the key it
was refused with. whatever writes a recording or the run's record passes its
text through here first.
"""
import re

# the key prefix and at least a few of its characters, so the bare prefix in
# prose is left alone
KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
SAID = "sk-ant-REDACTED"


def redact(text):
    """-> text with every provider key in it replaced; anything that is not
    text is handed back as it came."""
    if not isinstance(text, str) or "sk-ant-" not in text:
        return text
    return KEY.sub(SAID, text)


def redacted(value):
    """-> value with every string inside it, at any depth, redacted."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redacted(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redacted(v) for v in value)
    return value
