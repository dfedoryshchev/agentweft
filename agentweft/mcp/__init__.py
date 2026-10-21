__all__ = ["Client", "serve"]


# server imports the runner, whose gates import preflight from this package,
# so loading server here makes a first import of the gates a loop.
def __getattr__(name):
    if name == "Client":
        from .client import Client
        return Client
    if name == "serve":
        from .server import serve
        return serve
    raise AttributeError("module " + __name__ + " has no attribute " + name)
