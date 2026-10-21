"""summaries over the numbers a command pulls out of the lines."""
import math


def nearest_rank(values, p):
    ordered = sorted(values)
    rank = math.ceil(p * len(ordered) / 100)
    return ordered[max(rank, 1) - 1]


def percentile_line(values, p):
    return "p" + str(p) + " " + str(nearest_rank(values, p))
