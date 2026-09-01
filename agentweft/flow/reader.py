"""one yaml reader, for every file that is a spec.

it lived in the runner's config and read flow.yaml only. the workflow file had
its own reading, one line of `safe_load`, which is how a second file format
ends up with a second set of rules nobody chose.

so it moves here, next to the spec it produces, and both files get the same
one: the same duplicate-key rule, the same failure, the same message.
"""
import yaml


class OrderedLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    # safe_load quietly keeps the LAST of two identical keys, so a file with
    # two "steps:" blocks loses the first one and the order changes under you
    # with nothing in the output to say why. the same is true of two "agents:"
    # in one phase, which is why this is not the flow file's rule any more.
    seen = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in seen:
            raise yaml.YAMLError("duplicate key: " + str(key))
        seen[key] = loader.construct_object(v, deep=deep)
    return seen


OrderedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


def read(text):
    """-> whatever the file says, with duplicate keys refused."""
    return yaml.load(text, OrderedLoader)
