import typing
from collections import abc
from typing import Optional, Mapping, Tuple, Callable, Any, Union, Iterable, Hashable, Sequence, Collection

from .utils import (
    repr_seq_str,
    indent_msg_lines,
    InvalidValueError,
    InvalidValueNoTypeMatch,
    BadSchemaError,
)
from .spec import (
    Spec,
    Validator,
    Constraints,
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


# These get converted to an InvalidValueError when caught during canonicalization
# All other exceptions will immediately propagate, including InvalidValueError
_canonicalization_invalidating_exceptions = (ValueError, TypeError, AttributeError, KeyError)


class Type(Spec):
    """Spec for a single simple type.

    Capable of value canonicalization.
    """

    def __init__(self,
                 base_type: SimpleType,
                 canonicalize: Optional[Callable[[Any], Any]] = None,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
        if not isinstance(base_type, SimpleType.__args__):
            raise BadSchemaError('Type may only be used with one of: type/True/False/None')
        self.base_type = base_type
        self._canonicalize = canonicalize
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, Type, t, canonicalize))

    def canonicalize(self, value):
        try:
            if self._canonicalize:
                return self._canonicalize(value)
            else:
                return value
        except _canonicalization_invalidating_exceptions as e:
            raise InvalidValueError(f'{e.__class__.__name__} during canonicalization: {e}')

    def _check_value_type(self, value):
        value = check_value_base_type(self.base_type, value)
        return self.canonicalize(value)

    def type_name(self) -> str:
        return get_base_type_name(self.base_type)

    def copy(self, **kwds):
        kwds.setdefault('base_type', self.base_type)
        kwds.setdefault('canonicalize', self._canonicalize)
        self._set_default_kwds(kwds)
        return Type(**kwds)


class EnumSpec(Type):
    """Spec for a type consisting of arbitrary enumerated values.

    Values may be any type, but must be Hashable.
    Capable of value canonicalization.
    """

    def __init__(self,
                 values: Iterable[Hashable],
                 canonicalize: Optional[Callable[[Any], Any]] = None,
                 constraints: Constraints = None,
                 optional: bool = False,
                 is_unset: Validator = lambda value: not value,
                 default: Any = None):
        if optional and None not in values:
            values = [*values, None]
        self.values = frozenset(values)
        optional = None in values
        Type.__init__(self, None, canonicalize, optional, default, is_unset, constraints)
        self._hash = hash((self._hash, EnumSpec, self.values))
        self._copy_kwds = ('values', 'canonicalize')

    def _check_value_type(self, value):
        if value in self.values:
            return self.canonicalize(value)
        else:
            raise InvalidValueNoTypeMatch(f'Must match {self.type_name()}')

    def type_name(self) -> str:
        return 'enum=' + repr_seq_str(self.values, '/')


class TypeSpec(Spec):
    """Spec for a union of types, or in other words a type that is an enumeration of types (not values).

    Note that including `None` in `types` is equivalent to setting the `optional` flag True.

    Not capable of value canonicalization. Embed a Type/EnumSpec for a specific type if canonicalization is needed.
    """

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
        self._hash = hash((self._base_hash, TypeSpec, types))
        self._copy_kwds = ('types',)

    def _check_value_type(self, value):
        return check_value_types(self.types, value)

    def type_name(self) -> str:
        return '/'.join(get_types_names(self.types))


BaseIterable = typing.Type[Union[Iterable, Collection]]
_runtime_iterable = (abc.Iterable, abc.Collection)


class IterSpec(Spec):
    """Spec for an iterable. Behaves like TypeSpec on each element of an iterable value, with the key
    exception being that presence of `None` is *not equivalent* to `optional=True`.

    By default, the value will be canonicalized to a Python `list`. This can be overridden by passing the `c_type`
    argument. This may be any Iterable type that accepts a literal list of values as its only argument when called.

    Not directly capable of value canonicalization besides ensuring the desired Iterable type. Embed Type/EnumSpec if
    individual list element values must be canonicalized.
    """

    def __init__(self,
                 types: Types,
                 c_type: BaseIterable = list,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = lambda value: not value,
                 constraints: Constraints = None):
        self.types = canonicalize_types(types)
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, IterSpec, c_type, types))
        self._copy_kwds = ('types', 'c_type')

    def _check_value_type(self, value):
        if not isinstance(value, _runtime_iterable):
            raise InvalidValueNoTypeMatch(f'Must be collection or iterable')

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
    def __init__(self,
                 type_sequence: Sequence[BaseType],
                 c_type: BaseIterable = tuple,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = lambda value: not value,
                 constraints: Constraints = None):
        self.type_sequence = type_sequence
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, SeqSpec, c_type, type_sequence))
        self._copy_kwds = ('type_sequence', 'c_type')

    def type_name(self):
        return 'sequence(' + ', '.join(get_types_names(self.type_sequence)) + ')'

    def _check_value_type(self, value):
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


ReferenceValidator = Callable[[dict, Any], bool]
ReferenceUpdator = Callable[[dict, Any], Any]
ReferenceTest = Optional[Tuple[ReferenceValidator, str]]
ReferenceUpdate = Optional[Tuple[ReferenceValidator, ReferenceUpdator]]


class Reference:
    """Used in `references` for DictSpec along with a key"""

    def __init__(self,
                 test: ReferenceTest = None,
                 update: ReferenceUpdate = None):
        if not update and not test:
            raise BadSchemaError('At least one of update or test must be set')
        self._update = update
        self._test = test
        self._hash = hash((Reference, test, update))

    def __hash__(self):
        return self._hash

    def evaluate(self, mapping, value):
        if self._update:
            if self._update[0](mapping, value):
                value = self._update[1](mapping, value)
        if self._test:
            if not self._test[0](mapping, value):
                raise InvalidValueError(self._test[1])
        return value


class ConditionalDictSpec:
    """For use only as a value within a DictSpec

    Define an additional DictSpec to apply if the value under validation matches
    one of a given set of values.
    """
    def __init__(self,
                 value_condition_specs: Mapping[Hashable, Union[Mapping, DictSpec]],
                 optional: bool = False,
                 default: Any = None
                 apply_default_spec: bool = False):
        for key, dict_spec in value_condition_specs.items():
            dict_spec = canonicalize_base_type(dict_spec)
            if not isinstance(dict_spec, DictSpec):
                raise BadSchemaError('value_condition_spec values must be DictSpec instances')
            value_condition_specs[key] = dict_spec
            if dict_spec.type_key_specs:
                type_keys = repr_seq_str(dict_spec.type_key_specs, key=lambda i: i[0])
                raise BadSchemaError('type keys {type_keys} are not allowed in ConditionalDictSpec sub-Specs')
        if apply_default_spec:
            try:
                self.default_spec = value_condition_specs[default]
            except KeyError:
                raise BadSchemaError(f'default={default!r} does not exist in value_condition_specs and apply_default_spec=True')
        else:
            self.default_spec = None
        self.value_condition_specs = value_condition_specs
        self.optional = optional
        self._default = default
        self.apply_default_spec = apply_default_spec

    def default(self, checker):
        if self.apply_default_spec:
            checker.check_dict_spec(self.default_spec, unhandled_ok=True)
        return self._default

    def check_value(self, checker, value):
        try:
            value_spec = self.value_condition_spec[value]
            checker.check_dict_spec(value_spec, unhandled_ok=True)
            return value
        except KeyError:
            raise InvalidValueError(must_be_msg(tuple(self.value_condition_specs.keys())))
        except InvalidValueError as e:
            raise InvalidValueError(f'Does not conform with conditional spec for value {value!r}: {e}')


DictSpecValue = Union[Types, ConditionalDictSpec]
DictSchema = Optional[Mapping[Hashable, DictSpecValue]]
IterableSchema = Optional[Iterable[Tuple[Hashable, DictSpecValue]]]
References = Optional[Iterable[Tuple[Hashable, Reference]]]


class DictSpec(Spec):
    """Spec for a dict/mapping.

    Always canonicalized to a dict.

    `schema` *keys* may either be an explicit value or a BaseType.

    Explicit key values are processed first; there must be an exact key match in the mapping under validation. Optional
    explicit keys are specified by making its value an optional Spec.

    If an optional explicit key is missing from a mapping under validation, the canonicalized result will contain the
    `default` for the value Spec.

    Type-value keys are treated much like a TypeSpec for mapping keys that have no explicit match. Type-value keys
    have implicit "optional" behavior. Use a constraint on the whole mapping if you need to validate things like
     "one or more keys of this type is set".

    `references` defines any cross-reference-dependent validation/canonicalization. Must be a sequence of 2-tuples where
    the first element is an explicit key defined in `schema`. The second element must be an instance of Reference.

    Not directly capable of value canonicalization besides forcing to a dict. Embed Type/EnumSpec if individual
    mapping key/value values must be canonicalized.
    """
    def __init__(self,
                 schema: DictSchema = None,
                 value_key_specs: IterableSchema = None,
                 type_key_specs: IterableSchema = None,
                 references: References = None,
                 name: str = 'dict',
                 optional: bool = False,
                 default: Any = dict,
                 is_unset: Validator = lambda value: not value,
                 constraints: Constraints = None):

        if not schema and not value_key_specs and not type_key_specs:
            raise BadSchemaError('One of schema or value_key_specs/type_key_specs must be specified')

        if schema:
            if value_key_specs or type_key_specs:
                raise BadSchemaError('May not specify both schema and value_key_specs/type_key_specs')
            value_key_specs, type_key_specs = self._dict_schema_to_sequences(schema)

        for _, spec in type_key_specs:
            if isinstance(spec, ConditionalDictSpec):
                raise BadSchemaError('type keys may not use ConditionalDictSpec')

        if value_key_specs:
            self.value_key_specs = tuple(value_key_specs)
        else:
            self.value_key_specs = tuple()
        if type_key_specs:
            self.type_key_specs = tuple(type_key_specs)
        else:
            self.type_key_specs = tuple()
        if references:
            self.references = tuple(references)
        else:
            self.references = tuple()
        self.name = name

        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, DictSpec, self.type_key_specs, self.value_key_specs,
                           self.references, self.name))
        self._copy_kwds = (
            'type_key_specs',
            'value_key_specs',
            'references',
            'name',
        )

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

    def _check_value_type(self, mapping):
        if not isinstance(mapping, abc.Mapping):
            raise InvalidValueNoTypeMatch('Must be mapping/dict')

        return self._DictSpecValueChecker(mapping).check_dict_spec(self)

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
                    value = mapping[key]
                    self.c_mapping[key] = self._check_dict_spec_value(spec, value)
                except KeyError:
                    if isinstance(spec, Spec) and spec.optional:
                        d_value = spec.default()
                        self.c_mapping[key] = spec.check_value(d_value)
                    elif isinstance(spec, ConditionalDictSpec) and spec.optional:
                        self.c_mapping[key] = spec.default(self)
                    else:
                        failure_messages.append(f'Missing required mapping key {key!r}')
                except InvalidValueError as e:
                    failure_messages.append(f'Invalid value for key {key!r}: {e}')

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

        def _check_references(self, dict_spec):
            for key, ref_spec in dict_spec.references:
                try:
                    value = c_mapping[key]
                    self.c_mapping[key] = ref_spec.evaluate(self.c_mapping, value)
                except InvalidValueError as e:
                    self.failure_messages.append(str(e))
            if self.failure_messages:
                raise InvalidValueError('Does not conform with reference spec', self.failure_messages)

        @staticmethod
        def _add_keys(all_keys, key_specs):
            for key, _ in key_specs
                try:
                    hash(key)
                    all_keys.append(key)
                except TypeError:
                    raise BadSchemaError(f'DictSpec key {key!r} is not Hashable')

        def check_dict_spec(self, dict_spec: DictSpec, unhandled_ok: bool = False):
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

            self._check_references(dict_spec)

            return self.c_mapping
