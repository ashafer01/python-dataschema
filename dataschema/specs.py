from __future__ import annotations
import typing
from collections import abc
from typing import (
    Optional,
    Any,
    Union,
    Tuple,
    List,
    Dict,
    Callable,
    Hashable,
    Iterable,
    Sequence,
    Mapping,
)

from ._utils import (
    repr_seq_str,
    InvalidValueError,
    InvalidValueNoTypeMatch,
    BadSchemaError,
)
from .base import (
    Spec,
    Canonicalizable,
    Validator,
    Constraints,
    Canonicalize,
    default_is_unset,
)

SimpleType = Union[type, bool, type(None)]  # All types in this Union must also work with isinstance()
BaseType = Union[SimpleType, Spec, list, set, dict]
Types = Union[BaseType, Tuple[BaseType, ...]]


def canonicalize_base_type(t):
    """Return a Spec instance for list/set/dict/tuple and unmodified value for type/bool/Spec/None"""

    if isinstance(t, (Spec, *SimpleType.__args__)):
        return t
    elif isinstance(t, tuple):
        return TypeSpec(t)
    elif isinstance(t, list):
        return IterSpec(tuple(t))
    elif isinstance(t, set):
        return EnumSpec(t)
    elif isinstance(t, dict):
        return DictSpec(t)
    else:
        raise BadSchemaError(f'{t!r} is not a valid Type: must be type/bool/Spec/None/tuple/list/set/dict')


def canonicalize_types(types):
    """Convert a Types (possibly one BaseType) to a tuple of canonicalized base types"""
    c_types = []
    if isinstance(types, tuple):
        for t in types:
            c_types.append(canonicalize_base_type(t))
    else:
        c_types.append(canonicalize_base_type(types))
    return tuple(c_types)


def get_base_type_name(t: Any):
    """Get the string name for a canonicalized BaseType"""
    if isinstance(t, type):
        return t.__name__
    elif isinstance(t, Spec):
        return t.type_name()
    else:
        return repr(t)


def get_types_names(types: Any):
    """Get the string name for a canonicalized Types"""
    if not isinstance(types, tuple):
        return [get_base_type_name(types)]
    return [get_base_type_name(t) for t in types]


def must_be_msg(types: Any):
    """Obtain an exception message beginning with "Must be" for any Types"""
    if not isinstance(types, tuple):
        return 'Must be ' + get_base_type_name(types)
    elif len(types) == 1:
        return 'Must be ' + get_base_type_name(types[0])
    else:
        return 'Must be one of: ' + ', '.join(get_types_names(types))


def check_value_base_type(t: BaseType, value: Any):
    """Validate that value conforms with the BaseType and return the canonicalized value if so

    Raises InvalidValueError if the value is invalid
    """
    t = canonicalize_base_type(t)
    if isinstance(t, type):
        if isinstance(value, t):
            return value
    elif isinstance(t, Spec):
        return t.check_value(value)
    elif isinstance(t, bool) or t is None:
        if value is t:
            return value
    else:
        raise BadSchemaError(f'Invalid schema definition -- unknown type spec value {t!r}')
    raise InvalidValueNoTypeMatch(must_be_msg(t))


def check_value_types(types: Types, value: Any):
    """Validate that the value conforms with the Types and return the canonicalized value if so

    Raises InvalidValueError if the value is invalid
    """
    types = canonicalize_types(types)
    for t in types:
        try:
            return check_value_base_type(t, value)
        except InvalidValueNoTypeMatch:
            pass
    raise InvalidValueNoTypeMatch(must_be_msg(types))


def simple_is_unset(value: Any) -> bool:
    return not value


class Type(Canonicalizable):
    """
    `Type` wraps a single simple type (an instance of `type`, `True`, `False`, or `None) and allows annotation with
    additional schema controls. Typically, `Type` should only be used within other compound Specs, and not as the root
    of a schema.

    Values identify as the Type when they are an instance of the wrapped `type`, or identical if wrapping `True`,
    `False`, or `None`.

    The wrapped simple type is the required first argument to the constructor. If no additional arguments are passed,
    _it should not be used_.
    """
    _hash_props = ('base_type',)

    def __init__(self,
                 base_type: SimpleType,
                 canonicalize: Canonicalize = None,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
        """
        ---
        base_type: The single wrapped type, bool value, or None
        """
        if not isinstance(base_type, SimpleType.__args__):
            raise BadSchemaError('Type may only be used with one of: type/True/False/None')
        self.base_type = base_type
        Canonicalizable.__init__(self, canonicalize, optional, default, is_unset, constraints)

    def _check_value(self, value):
        return check_value_base_type(self.base_type, value)

    def type_name(self) -> str:
        return get_base_type_name(self.base_type)


class CType(Type):
    """
    `CType` is just like `Type`, with the exception being with canonicalization and type identity.

    A value identifies as a `Type` by being an instance of or identical to it's wrapped type. If a `Type` has a
    `canonicalize` function, and it fails to canonicalize, it is considered an invalid value _of that Type_.

    With a `CType`, the value _only identifies as the type_ if it meets the identity criteria for `Type` _as well as_
    being able to successfully canonicalize.

    This creates significant effect in the handling of, for example, TypeSpec.

    TypeSpec((Type(str, int), EnumSpec('foo', 'bar')) would find the check value of 'foo' to be invalid, because it
    would first identify as a Type(str, ...) and then be considered invalid because it cannot be canonicalized with
    int(), thereby invalidating the TypeSpec before the EnumSpec is checked. Using CType(str, int) would prevent
    this because 'foo' would not identify as the Type.
    """
    _canonicalization_invalid_exception: Exception = InvalidValueNoTypeMatch


class EnumSpec(Canonicalizable):
    """Spec for a type consisting of arbitrary enumerated values.

    Values may be any type, but must be Hashable.
    Capable of value canonicalization.
    """
    _hash_props: Tuple[str] = ('values',)

    def __init__(self,
                 values: Iterable[Hashable],
                 canonicalize: Canonicalize = None,
                 constraints: Constraints = None,
                 optional: bool = False,
                 is_unset: Validator = simple_is_unset,
                 default: Any = None):
        if optional and None not in values:
            values = [*values, None]
        optional = None in values
        self.values = frozenset(values)
        Canonicalizable.__init__(self, canonicalize, optional, default, is_unset, constraints)

    def _check_value(self, value):
        if value in self.values:
            return value
        else:
            raise InvalidValueNoTypeMatch(f'Must match {self.type_name()}')

    def type_name(self) -> str:
        return 'enum=' + repr_seq_str(self.values, '/')


class TypeSpec(Spec):
    """Spec for a union of types, or in other words a type that is an enumeration of types (not values).

    Note that including `None` in `types` is equivalent to setting the `optional` flag True.

    Not capable of value canonicalization. Embed a Type/EnumSpec for a specific type if canonicalization is needed.
    """
    _hash_props: Tuple[str] = ('types',)

    def __init__(self,
                 types: Types,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
        types = canonicalize_types(types)
        if optional and None not in types:
            types = (*types, None)
        optional = None in types
        self.types = types
        Spec.__init__(self, optional, default, is_unset, constraints)

    def _check_value(self, value):
        return check_value_types(self.types, value)

    def type_name(self) -> str:
        return '/'.join(get_types_names(self.types))


IterableType = typing.Type[Iterable]


class IterSpec(Spec):
    """Spec for an iterable. Behaves like TypeSpec on each element of an iterable value, with the key
    exception being that presence of `None` is *not equivalent* to `optional=True`.

    By default, the value will be canonicalized to a Python `list`. This can be overridden by passing the `c_type`
    argument. This may be any Iterable type that accepts a literal list of values as its only argument when called.

    Not directly capable of value canonicalization besides ensuring the desired Iterable type. Embed Type/EnumSpec if
    individual list element values must be canonicalized.
    """
    _hash_props: Tuple[str] = ('types', 'c_type')

    def __init__(self,
                 types: Types,
                 c_type: IterableType = list,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = simple_is_unset,
                 constraints: Constraints = None):
        self.types = canonicalize_types(types)
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)

    def _check_value(self, value):
        if not isinstance(value, abc.Iterable):
            raise InvalidValueNoTypeMatch(f'Must be iterable')

        c_values = []
        failure_messages = []
        for i, l_value in enumerate(value):
            try:
                c_values.append(check_value_types(self.types, l_value))
            except InvalidValueError as e:
                failure_messages.append(f'Index {i} is invalid: {e}')
        if failure_messages:
            raise InvalidValueError('Items do not conform with iterable spec', failure_messages)
        return self.c_type(c_values)

    def type_name(self) -> str:
        return self.c_type.__name__


class SeqSpec(Spec):
    """Spec for a sequence where specific types must appear in a specific sequence.

    By default, canonicalizes the sequence to a Python `tuple`; no other value canonicalization is supported. Embed
    a Type/EnumSpec to canonicalize specific sequence elements based on their type.

    Does not support variable-length sequences. `type_sequence` and a value under validation must have the same length.
    """
    _hash_props: Tuple[str] = ('type_sequence', 'c_type')

    def __init__(self,
                 type_sequence: Sequence[BaseType],
                 c_type: IterableType = tuple,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = simple_is_unset,
                 constraints: Constraints = None,
                 auto_optional: bool = False):
        self.type_sequence = type_sequence
        self.c_type = c_type

        if auto_optional:
            if optional or default is not list:
                raise BadSchemaError('cannot pass auto_optional=True with optional or default')
            if not type_sequence:
                raise BadSchemaError('cannot pass auto_optional=True with empty type_sequence')
            auto_default = self._auto_optional()
            if auto_default:
                optional = True
                default = auto_default

        Spec.__init__(self, optional, default, is_unset, constraints)

    def _auto_optional(self):
        default_seq = []
        for spec in self.type_sequence:
            if isinstance(spec, Spec) and spec.optional:
                d_value = spec.default()
                default_seq.append(spec.check_value(d_value))
            else:
                default_seq.clear()
                break
        return self.c_type(default_seq)

    def type_name(self):
        return 'sequence(' + ', '.join(get_types_names(self.type_sequence)) + ')'

    def _check_value(self, value):
        if not isinstance(value, abc.Sequence):
            raise InvalidValueNoTypeMatch(f'Must be Sequence type')

        seq_len = len(self.type_sequence)
        if len(value) != seq_len:
            raise InvalidValueError(f'Sequence must have exactly {seq_len} elements')

        c_values = []
        failure_messages = []
        for i, spec in enumerate(self.type_sequence):
            s_value = value[i]
            try:
                c_values.append(check_value_base_type(spec, s_value))
            except InvalidValueError as e:
                failure_messages.append(f'Sequence index {i} is invalid: {str(e)}')
        if failure_messages:
            raise InvalidValueError('Sequence does not conform with spec', failure_messages)
        return self.c_type(c_values)


RefKeys = Tuple[Hashable, ...]
RefUpdate = Callable[..., Any]
RefTest = Callable[..., bool]


class Post:
    def __init__(self, ref_keys: RefKeys):
        if not ref_keys:
            raise BadSchemaError('At least one reference key must be specified for Update/Post')
        self.ref_keys = ref_keys
        self._hash = None
        self._hash_vals = ()

    def __hash__(self):
        if self._hash is None:
            self._hash = hash((self.__class__, self.ref_keys, *self._hash_vals))
        return self._hash

    def evaluate(self, c_mapping: dict) -> None:
        raise NotImplementedError()

    def _get_ref_values(self, c_mapping: dict) -> List:
        ref_values = []
        missing_ref_keys = []
        for key in self.ref_keys:
            try:
                ref_values.append(c_mapping[key])
            except KeyError:
                missing_ref_keys.append(repr(key))
        if missing_ref_keys:
            missing_ref_keys = ', '.join(missing_ref_keys)
            raise InvalidValueError(f'Missing ref_keys {missing_ref_keys}')
        return ref_values


def default_gate(*_) -> bool:
    return True


class Update(Post):
    def __init__(self, *ref_keys,
                 update: RefUpdate,
                 gate: RefTest = default_gate):
        Post.__init__(self, ref_keys)
        self.update = update
        self.gate = gate
        self._hash_vals = (update, gate)

    def evaluate(self, c_mapping: dict) -> None:
        ref_values = self._get_ref_values(c_mapping)
        if self.gate(*ref_values):
            c_mapping[self.ref_keys[0]] = self.update(*ref_values)


class Test(Post):
    def __init__(self, *ref_keys,
                 test: RefTest,
                 message: str):
        Post.__init__(self, ref_keys)
        self.test = test
        self.message = message
        self._hash_vals = (test, message)

    def evaluate(self, c_mapping: dict) -> None:
        ref_values = self._get_ref_values(c_mapping)
        if not self.test(*ref_values):
            raise InvalidValueError(self.message)


class ConditionalDictSpec:
    value_condition_specs: Dict[Hashable, DictSpec] = {}
    apply_default_spec: bool = False
    optional: bool = False

    def __init__(self,
                 value_condition_specs: Mapping[Hashable, Union[Mapping, DictSpec]],
                 optional: bool = False,
                 default: Any = None,
                 apply_default_spec: bool = False):
        for key, dict_spec in value_condition_specs.items():
            dict_spec = canonicalize_base_type(dict_spec)
            if not isinstance(dict_spec, DictSpec):
                raise BadSchemaError('value_condition_spec values must be DictSpec instances')
            if dict_spec.type_key_specs:
                type_keys = repr_seq_str(dict_spec.type_key_specs, key=lambda i: i[0])
                raise BadSchemaError(f'type keys {type_keys} are not allowed in ConditionalDictSpec sub-Specs')
            value_condition_specs[key] = dict_spec
        if apply_default_spec:
            try:
                self.default_spec = value_condition_specs[default]
            except KeyError:
                raise BadSchemaError(f'default={default!r} does not exist in value_condition_specs '
                                     f'and apply_default_spec=True')
        else:
            self.default_spec = None
        self.value_condition_specs = value_condition_specs
        self.apply_default_spec = apply_default_spec
        self.optional = optional
        self._default = default
        self._hash = hash((
            ConditionalDictSpec,
            tuple(value_condition_specs.items()),
            apply_default_spec,
            optional,
            default,
        ))

    def __hash__(self):
        return self._hash

    def default(self, checker):
        if self.apply_default_spec:
            checker.check_dict_spec(self.default_spec, unhandled_ok=True)
        return self._default

    def check_value(self, checker, value):
        try:
            value_spec = self.value_condition_specs[value]
            checker.check_dict_spec(value_spec, unhandled_ok=True)
            return value
        except KeyError:
            raise InvalidValueError(must_be_msg(tuple(self.value_condition_specs.keys())))
        except InvalidValueError as e:
            raise InvalidValueError(f'Does not conform with conditional spec for value {value!r}: {e}')


DictSpecValue = Union[Types, ConditionalDictSpec]
DictItemPair = (Hashable, DictSpecValue)
DictItemTuple = Tuple[DictItemPair]
DictSchema = Optional[Mapping[DictItemPair]]
IterableSchema = Optional[Iterable[DictItemTuple]]
PostProcessing = Optional[Iterable[Post]]


class DictSpec(Spec):
    """
    Define a schema for a dictionary or other Mapping type
    """
    value_key_specs: Tuple[DictItemTuple, ...] = ()
    type_key_specs: Tuple[DictItemTuple, ...] = ()
    post: Tuple[Post, ...] = ()
    name: str = 'dict'
    unhandled_ok: bool = False

    _hash_props: Tuple[str] = (
        'value_key_specs',
        'type_key_specs',
        'post',
        'name',
        'unhandled_ok',
    )

    def __init__(self,
                 schema: DictSchema = None,
                 value_key_specs: IterableSchema = None,
                 type_key_specs: IterableSchema = None,
                 post: PostProcessing = None,
                 name: str = 'dict',
                 unhandled_ok: bool = False,
                 optional: bool = False,
                 default: Any = dict,
                 is_unset: Validator = simple_is_unset,
                 constraints: Constraints = None,
                 auto_optional: bool = False):
        """
        ---
        schema: |
            This is mainly a convenience parameter to allow defining the DictSpec using a dict, such that the spec looks
            a lot like a valid value. Keys may either be specific values (see `value_key_specs`) as well as types
            or Specs (see `type_key_specs`). Values must always be a type or Spec.
        value_key_specs: |
            An iterable of 2-tuples, where:

            * The first element is any valid, Hashable dictionary key that is expected in a valid, canonical value dict
            * The second element is a type or Spec with which to validate the values in the dict under validation

            To mark a key as optional, set its value to a Spec with `optional=True`.

            Value key specs may use the special value `ConditionalDictSpec`. This allows for enumerating a set of
            allowed values for the key, and defining an additional `DictSpec` to apply when the dict under validation
            contains a matching value. This is designed for keys like `"type"` which need to impose additional
            constraints on the structure of the dict.
        type_key_specs: |
            An iterable of 2-tuples, where both elements are types or Specs.

            After processing `value_key_specs`, any remaining keys in the dict under validation will be checked for
            a type match on the first element of a `type_key_spec`. All values that match will then be validated against
            the type/Spec in the 2nd element of the `type_key_spec`.

            Type keys are implicitly optional. Use a constraint to require, for example, a certain number of string
            keys in the dict.

            `ConditionalDictSpec` is not allowed with type keys specs.
        post: |
            An iterable of instances of the `Post` ABC, currently `Update` and `Test`. After the dict is considered
            "type-valid" by passing the requirements defined in the schema, additional post-processing steps can be
            applied, typically be associated with cross-references between dict keys. See `Update` and `Test` for more
            details.
        name: A string containing a canonical name for this `DictSpec`. Primarily used in error messages.
        unhandled_ok: Set to True to consider the dict valid if it contains unhandled keys after processing the schema
        auto_optional: |
            Set to True to make the `DictSpec` optional if all value keys are optional or if there are only
            type keys, and auto-generate a default dict where all value keys are set to their default value.
        """

        if schema:
            if value_key_specs or type_key_specs:
                raise BadSchemaError('May not specify both schema and value_key_specs/type_key_specs')
            value_key_specs, type_key_specs = self._dict_schema_to_sequences(schema)
        else:
            if not value_key_specs and not type_key_specs:
                raise BadSchemaError('One of schema or value_key_specs/type_key_specs must be specified')

        for _, spec in type_key_specs:
            if isinstance(spec, ConditionalDictSpec):
                raise BadSchemaError('type keys may not use ConditionalDictSpec')

        if value_key_specs:
            self.value_key_specs = tuple(value_key_specs)
        if type_key_specs:
            self.type_key_specs = tuple(type_key_specs)
        if post:
            self.post = tuple(post)
        self.name = name
        self.unhandled_ok = unhandled_ok

        if auto_optional:
            if optional or default is not dict:
                raise BadSchemaError('cannot pass auto_optional=True with optional or default')
            if self.value_key_specs:
                auto_default = self._auto_optional()
                if auto_default:
                    optional = True
                    default = auto_default
            elif self.type_key_specs:
                optional = True
            else:
                raise BadSchemaError('cannot pass auto_optional=True with empty schema/value_key_specs/type_key_specs')

        Spec.__init__(self, optional, default, is_unset, constraints)

    def _auto_optional(self):
        default_dict = {}
        for value_key, spec in self.value_key_specs:
            if isinstance(spec, Spec) and spec.optional:
                d_value = spec.default()
                default_dict[value_key] = spec.check_value(d_value)
            else:
                default_dict.clear()
                break
        return default_dict

    @staticmethod
    def _dict_schema_to_sequences(schema: DictSchema):
        value_key_specs = []
        type_key_specs = []
        for key, spec in schema.items():
            try:
                type_key = canonicalize_base_type(key)
                type_key_specs.append((type_key, spec))
            except BadSchemaError:
                value_key_specs.append((key, spec))
        return value_key_specs, type_key_specs

    def type_name(self) -> str:
        return self.name

    def _check_value(self, mapping):
        if not isinstance(mapping, abc.Mapping):
            raise InvalidValueNoTypeMatch('Must be mapping/dict')

        return self._DictSpecValueChecker(mapping).check_dict_spec(self, self.unhandled_ok)

    class _DictSpecValueChecker:
        def __init__(self, mapping):
            self.mapping = mapping
            self.c_mapping = {}
            self.failure_messages = []
            self.unhandled_keys = set(mapping.keys())

        def _check_dict_spec_value(self, spec, value):
            if isinstance(spec, ConditionalDictSpec):
                return spec.check_value(self, value)
            else:
                return check_value_base_type(spec, value)

        def _check_value_key_specs(self, dict_spec):
            for key, spec in dict_spec.value_key_specs:
                try:
                    self.unhandled_keys.remove(key)
                    value = self.mapping[key]
                    self.c_mapping[key] = self._check_dict_spec_value(spec, value)
                except KeyError:
                    if isinstance(spec, Spec) and spec.optional:
                        d_value = spec.default()
                        self.c_mapping[key] = spec.check_value(d_value)
                    elif isinstance(spec, ConditionalDictSpec) and spec.optional:
                        self.c_mapping[key] = spec.default(self)
                    else:
                        self.failure_messages.append(f'Missing required mapping key {key!r}')
                except InvalidValueError as e:
                    self.failure_messages.append(f'Invalid value for key {key!r}: {e}')

        def _check_type_key_spec(self, dict_spec, key, value):
            for type_key, spec in dict_spec.type_key_specs:
                try:
                    c_key = check_value_base_type(type_key, key)
                except InvalidValueError:
                    continue
                try:
                    c_value = self._check_dict_spec_value(spec, value)
                    return c_key, c_value
                except InvalidValueError as e:
                    raise InvalidValueError(f'Value for key {key!r} does not conform with spec: {e}')
            raise InvalidValueNoTypeMatch('No match for dict type keys')

        def _check_type_key_specs(self, dict_spec):
            if self.unhandled_keys and dict_spec.type_key_specs:
                for key in list(self.unhandled_keys):
                    value = self.mapping[key]
                    try:
                        c_key, c_value = self._check_type_key_spec(dict_spec, key, value)
                        self.unhandled_keys.remove(key)
                        self.c_mapping[c_key] = c_value
                    except InvalidValueNoTypeMatch:
                        pass
                    except InvalidValueError as e:
                        self.failure_messages.append(str(e))
                        self.unhandled_keys.remove(key)

        def _post_processing(self, dict_spec: DictSpec):
            for post in dict_spec.post:
                try:
                    post.evaluate(self.c_mapping)
                except InvalidValueError as e:
                    self.failure_messages.append(str(e))
            if self.failure_messages:
                raise InvalidValueError('Post processing has failed', self.failure_messages)

        @staticmethod
        def _add_keys(all_keys, key_specs):
            for key, _ in key_specs:
                try:
                    hash(key)
                    all_keys.append(key)
                except TypeError:
                    raise BadSchemaError(f'DictSpec key {key!r} is not Hashable')

        def check_dict_spec(self, dict_spec: DictSpec, unhandled_ok: bool):
            self._check_value_key_specs(dict_spec)
            self._check_type_key_specs(dict_spec)

            if not unhandled_ok and self.unhandled_keys:
                unhandled_keys = repr_seq_str(self.unhandled_keys)
                all_keys = []
                self._add_keys(all_keys, dict_spec.value_key_specs)
                self._add_keys(all_keys, dict_spec.type_key_specs)
                keys_must_be = must_be_msg(all_keys)
                self.failure_messages.append(f'Keys {unhandled_keys} are unhandled; valid keys {keys_must_be}')

            if self.failure_messages:
                raise InvalidValueError('Does not conform with dict schema', self.failure_messages)

            self._post_processing(dict_spec)

            return self.c_mapping
