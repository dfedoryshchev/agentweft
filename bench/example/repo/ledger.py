def parse(line):
    amount, note = line.split(" ", 1)
    return {"amount": float(amount), "note": note.strip()}


def add(entries, amount, note=""):
    if amount == 0:
        raise ValueError("an amount of 0 is not an entry")
    entries.append({"amount": float(amount), "note": note})
    return entries


def balance(entries):
    return sum(e["amount"] for e in entries)
