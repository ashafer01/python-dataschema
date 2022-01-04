"""Common re-usable composed specs"""
from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv6Address

from . import utils
from .base import Constraint
from .specs import (
    Type,
    CType,
    TypeSpec,
    IterSpec,
)

optional_bool = Type(bool, optional=True)
optional_str = Type(str, optional=True)
optional_int = Type(int, optional=True)
optional_float = Type(float, optional=True)

user_integer = TypeSpec((int, CType(str, int)))
user_float = TypeSpec((float, CType(str, float)))

number = TypeSpec((user_integer, user_float))

lowercased_str = Type(str, lambda s: s.lower())

str_list = IterSpec(str)
str_set = IterSpec(str, c_type=frozenset)

lowercased_str_list = IterSpec(lowercased_str)
lowercased_str_set = IterSpec(lowercased_str, c_type=frozenset)

str_list_or_single = utils.list_or_single(str)

ipv4_address = Type(str, IPv4Address)
ipv6_address = Type(str, IPv6Address)

port_number_constraint: Constraint = (
    lambda v: 1 <= v <= 65535,
    'Must be in port number range 1-65535'
)
port_number = user_integer(constraints=port_number_constraint)

_word_re = re.compile(r'^\w*$')
word_constraint: Constraint = (
    lambda s: bool(_word_re.match(s)),
    'Must contain only word characters'
)
word_str = Type(str, constraints=word_constraint)
word_str_minlength_3 = word_str.add_constraints(utils.minlen(3))
