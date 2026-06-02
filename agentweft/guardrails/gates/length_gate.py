from .base import Gate, register


@register
class LengthGate(Gate):
    """the digest that ran to four pages is why this exists."""

    name = "length"

    def run(self, text):
        lines = [l for l in text.split("\n") if l.strip()]
        most = int(self.opts.get("max_lines", 0) or 0)
        least = int(self.opts.get("min_lines", 0) or 0)
        if most and len(lines) > most:
            return self.fail(str(len(lines)) + " lines, cap is " + str(most))
        if least and len(lines) < least:
            return self.fail(str(len(lines)) + " lines, wanted " + str(least))
        return self.ok(str(len(lines)) + " lines")
