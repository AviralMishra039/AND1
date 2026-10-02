import utils.config as _config


def _load_langfuse():
    if not _config.TRACING_ENABLED:
        return None
    try:
        from langfuse import get_client, observe

        get_client()
        return observe, get_client
    except Exception:
        try:
            from langfuse import observe

            return observe, None
        except Exception:
            print("[tracing] Langfuse is configured but could not be initialized.")
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
_get_client = _loaded[1] if _loaded else None


def langfuse_client():
    """Configured Langfuse client, or None when tracing is off."""
    if _get_client is None:
        return None
    try:
        return _get_client()
    except Exception:
        return None


def tag_trace(input=None, output=None):
    """Attach input/output to the current Langfuse trace (no-op when off)."""
    client = langfuse_client()
    if client is None:
        return
    try:
        if input is not None:
            client.set_current_trace_io(input=input)
        if output is not None:
            client.set_current_trace_io(output=output)
    except Exception as e:
        print(f"[tracing] tag_trace skipped: {e}")


def flush():
    """Flush pending trace exports (no-op when off)."""
    client = langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as e:
        print(f"[tracing] flush skipped: {e}")
