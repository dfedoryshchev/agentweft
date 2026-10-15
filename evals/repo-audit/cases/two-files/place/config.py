import yaml


def load(path="settings.yml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
