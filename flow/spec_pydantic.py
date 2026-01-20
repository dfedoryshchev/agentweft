"""poc. run by hand, nothing imports this.

check() is thirty lines of me reimplementing what a schema library does, and it
only catches what i remembered to check. trying pydantic to see if the spec
gets shorter.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Step(BaseModel):
    role: str
    prompt: Optional[str] = None
    fanout: bool = False
    on_redo: Optional[str] = None


class Promises(BaseModel):
    inputs: str = ""
    outputs: str = ""
    invariants: List[str] = Field(default_factory=list)


class FlowSpec(BaseModel):
    name: str
    steps: List[Step]
    promises: Promises = Field(default_factory=Promises)
    schedule: Optional[str] = None
    timeout: int = 300
    retries: int = 3
    workers: int = 3


if __name__ == "__main__":
    import sys

    import yaml

    raw = yaml.safe_load(open(sys.argv[1]).read())
    print(FlowSpec(**raw))
