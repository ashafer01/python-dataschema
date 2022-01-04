"""User-facing utility functions"""
from __future__ import annotations
from typing import Any

from .specs import (
    SimpleType,
    Type,
    TypeSpec,
    IterSpec,
)
from .base import Constraint

# "generics"


def list_or_single(t: SimpleType) -> TypeSpec:
    return TypeSpec((IterSpec(t), Type(t, lambda v: [v])))


# constraint factories


def minlen(length: int) -> Constraint:
    def check_length(value: Any) -> bool:
        return len(value) >= length
    return check_length, f'Must have length >= {length}'


def maxlen(length: int) -> Constraint:
    def check_length(value: Any) -> bool:
        return len(value) <= length
    return check_length, f'Must have length <= {length}'


def range_len(min_len: int, max_len: int) -> Constraint:
    def check_length(value: Any) -> bool:
        return min_len <= len(value) <= max_len
    return check_length, f'Must have length between {min_len}-{max_len}'


def exact_len(length: int) -> Constraint:
    def check_length(value: Any) -> bool:
        return len(value) == length
    return check_length, f'Must have exact length {length}'


def contains(test_value: Any) -> Constraint:
    def check_contains(value: Any) -> bool:
        return test_value in value
    return check_contains, f'Must contain {test_value!r}'


def min_value(min_val: Any) -> Constraint:
    def check_value(value: Any) -> bool:
        return value >= min_val
    return check_value, f'Must be >= {min_val!r}'


def max_value(max_val: Any) -> Constraint:
    def check_value(value: Any) -> bool:
        return value <= max_val
    return check_value, f'Must be <= {max_val!r}'


def range_value(min_val: Any, max_val: Any) -> Constraint:
    def check_value(value: Any) -> bool:
        return min_val <= value <= max_val
    return check_value, f'Must be between {min_val!r}-{max_val!r}'
