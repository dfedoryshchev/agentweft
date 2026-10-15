import sys

from config import load


def run(args):
    settings = load()
    return settings["port"], args


if __name__ == "__main__":
    print(run(sys.argv[1:]))
