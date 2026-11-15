"""the start of every git command agentweft runs itself.

a place's `.git/config` is the place's: `git clone` ships none, but a step can
write one, and git runs a `core.fsmonitor` command on a status and the hooks
under `core.hooksPath` on a commit or a checkout, on the person's side, with
the run's whole environment. so agentweft's own git switches both off on its
command line, which ranks above every config file; a `-c` the caller adds
after them still wins (a worktree handed hooks of its own). the edit tools
are kept out of `.git/` as well (`shellwrite.KEEP_ALL`), so this is the
second wall, not the only one: `include.path`, `credential.helper`,
`core.sshCommand`, `diff.external` or a `filter.*` driver a step got into
the config some other way would still run.
"""
import os

OFF = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull)


def argv(*args):
    """-> `git` with the place's fsmonitor and hooks off, then `args`."""
    return ["git"] + list(OFF) + list(args)
