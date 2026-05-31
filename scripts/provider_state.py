"""Provider-state metadata adapter for Trinity review dispatch."""

try:
    from . import _review_metadata as _rm
except ImportError:
    import _review_metadata as _rm


def update_provider_state(*args, **kwargs):
    return _rm.update_provider_state(*args, **kwargs)


def append_result(*args, **kwargs):
    return _rm.append_result(*args, **kwargs)
