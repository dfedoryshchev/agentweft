from pathlib import Path

from .base import Gate, register


@register
class QuoteGate(Gate):
    """every quote in the answer has to be in what the step was given.

    `source` names the input, a file or a folder, with `{INBOX}`, `{LOGS}` and
    `{WATCH}` read the way a prompt reads them. a span between double quotes
    of three words or more has to be in one of its files word for word,
    spacing aside. an answer that quotes something from a source that is not
    there fails: nothing to check against is not a pass.
    """

    name = "quote"
    options = ("source",)

    def run(self, text):
        from agentweft.runner.prompts import substitute
        from agentweft.runner.ruling import QUOTE_WORDS, QUOTED, flat

        quotes = [flat(q) for q in QUOTED.findall(text or "")
                  if len(q.split()) >= QUOTE_WORDS]
        if not quotes:
            return self.ok("nothing quoted")
        said = str(self.opts.get("source") or "")
        source = substitute(said).strip()
        if not source:
            return self.broke("no source to hold the quotes to (source: "
                              + said + ")")
        root = Path(source)
        if not root.is_absolute() and self.where:
            root = Path(self.where) / root
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(p for p in root.rglob("*") if p.is_file())
        else:
            return self.broke(source + " is not there to hold the quotes to")
        held = []
        for f in files:
            try:
                held.append(flat(f.read_text(encoding="utf-8",
                                             errors="replace")))
            except OSError:
                continue
        for q in quotes:
            if not any(q in h for h in held):
                return self.fail('"' + q + '" is in no file under ' + source)
        return self.ok(str(len(quotes)) + " quoted, all in " + source)
