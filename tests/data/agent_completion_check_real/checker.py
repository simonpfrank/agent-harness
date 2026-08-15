"""Deterministic completion_check target for integration tests.

Fails on its first invocation, passes on every invocation after that —
independent of model behavior, so a real fail-then-retry-then-pass cycle
can be proven without needing to synchronize with what the model does.
"""

import pathlib
import sys

_COUNTER = pathlib.Path(__file__).parent / "counter.txt"


def main() -> int:
    count = int(_COUNTER.read_text()) if _COUNTER.exists() else 0
    _COUNTER.write_text(str(count + 1))
    return 0 if count >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
