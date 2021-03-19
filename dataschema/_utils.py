from __future__ import annotations
from typing import Callable, Iterable, Any, Optional


def repr_seq_str(seq: Iterable[Any], delim: str = ', ', key: Callable[[Any], Any] = lambda i: i):
    return delim.join(repr(key(i)) for i in seq)


def indent_msg_lines(messages: Iterable[str]):
    indented_lines = []
    for m in messages:
        indented_lines.append('\n   '.join(m.split('\n')))
    return indented_lines


class InvalidValueError(Exception):
    """Base exception for any value that fails to validate or canonicalize"""
    def __init__(self, msg: str, messages: Optional[Iterable[str]] = None):
        if messages:
            self.messages = messages
            msg = msg + ':\n-- ' + '\n-- '.join(indent_msg_lines(messages))
        else:
            self.messages = [msg]
        self.message = msg
        self.error_count = len(self.messages)
        Exception.__init__(self, msg)

    def __str__(self):
        return self.message


class InvalidValueNoTypeMatch(InvalidValueError):
    """Exception for when there is explicitly no type match -- mostly used internally

    Users will typically only need to catch `InvalidValueError` (base of this class) and look at the message
    """
    pass


class BadSchemaError(Exception):
    pass
