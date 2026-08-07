import enum
from collections.abc import Callable


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Persist Python Enum `.value` strings rather than member names."""
    return [str(member.value) for member in enum_cls]
