from .base import Gate, Result, build, registry
from . import (command_gate, coverage_gate, length_gate,  # noqa: F401
               redtest_gate, regex_gate,
               reject_gate)  # (they register themselves)

__all__ = ["Gate", "Result", "build", "registry"]
