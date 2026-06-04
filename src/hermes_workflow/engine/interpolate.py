from __future__ import annotations
import re

_TOKEN = re.compile(r"\$\{([^}]+)\}")


class InterpolationError(ValueError):
    pass


def interpolate(s: str, *, params: dict, expand_vars: dict) -> str:
    """Substitute only ${params.*} and ${<expand-var>.*}; raise on any unknown ref/namespace."""
    def repl(m):
        ref = m.group(1).strip()
        ns, _, rest = ref.partition(".")
        if ns == "params":
            if rest not in params:
                raise InterpolationError(f"unknown param {rest!r}")
            return str(params[rest])
        if ns in expand_vars:
            obj = expand_vars[ns]
            if rest not in obj:
                raise InterpolationError(f"unknown field {rest!r} on {ns!r}")
            return str(obj[rest])
        raise InterpolationError(f"unknown reference namespace {ns!r}")
    return _TOKEN.sub(repl, s)
