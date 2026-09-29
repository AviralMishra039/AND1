import utils.config as _config


def _load_langfuse():
    if not _config.TRACING_ENABLED:
        return None
    try:
        from langfuse.decorators import langfuse_context, observe

        return observe, langfuse_context
    except Exception:
        try:
            from langfuse import observe

            return observe, None
        except Exception:
            print("[tracing] Langfuse is configured but could not be imported.")
            return None


def _noop_observe(*args, **kwargs):
    """No-op stand-in when Langfuse is not configured."""
    if args and callable(args[0]) and not kwargs:
        return args[0]

    def decorator(fn):
        return fn

    return decorator


_loaded = _load_langfuse()
observe = _loaded[0] if _loaded else _noop_observe
langfuse_context = _loaded[1] if _loaded else None
