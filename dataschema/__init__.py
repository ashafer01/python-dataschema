import typing
from collections import abc
from typing import Optional, Dict, Tuple, Callable, Any, Union, Iterable, Hashable, Sequence, Collection


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


Validator = Callable[[Any], bool]

Constraint = Tuple[Validator, str]
Constraints = Union[Constraint, Iterable[Constraint]]

# types that can routinely be explicitly set to a falsey value and be meaningfully
# different from False in the context of "data"
_explicitly_falsifiable = (int, float, complex, bool)


def is_implicitly_falsey(value):
    """Return True if a value is "implicitly" falsey, i.e. unlikely to be an explicit user-set falsey value"""
    return not value and not isinstance(value, _explicitly_falsifiable)


class Spec(object):
    """Abstract base class for schema spec elements.

    This defines all of the common features of all Spec:

    `optional` A flag indicating whether or not the value is optional.
    `default` The default value, or a callable returning the default value (callables are not passed any arguments)
    `is_unset` A callable accepting a value under validation. If it returns True, the `default` will be used instead
       of the candidate value.
    `constraints` A single 2-tuple, or sequence of 2-tuples. The first tuple element must be a callable that returns a
       falsey value if the constraint is not met. The second tuple element must be a string message to indicate the
       nature of the failure.
    """

    def __init__(self,
                 optional: bool,
                 default: Any = None,
                 is_unset: Validator = is_implicitly_falsey,
                 constraints: Optional[Constraints] = None):
        self.optional = optional
        self._default = default
        self._is_unset = is_unset
        if constraints and not isinstance(constraints[0], tuple):
            constraints = (constraints,)
        self._constraints = constraints
        if optional:
            try:
                d_value = self.default()
                self._check_value(d_value)
            except InvalidValueError as e:
                raise BadSchemaError(f'Invalid schema, default value is spec-invalid: {str(e)}')
        self._hash = None
        self._base_hash = (optional, default, is_unset, constraints)
        self._base_kwds = (
            ('optional', self.optional),
            ('default', self._default),
            ('is_unset', self._is_unset),
            ('constraints', self._constraints),
        )

    def __hash__(self):
        if self._hash is None:
            raise RuntimeError('Programming error - class did not set self._hash')
        return self._hash

    def _set_default_kwds(self, kwds: dict):
        for key, value in self._base_kwds:
            kwds.setdefault(key, value)

    def default(self):
        if callable(self._default):
            return self._default()
        else:
            return self._default

    def check_constraints(self, value) -> None:
        if not self._constraints:
            return
        if self._is_unset(value) and self.optional:
            return
        failure_messages = []
        for c, message in self._constraints:
            result = c(value)
            if not result:
                failure_messages.append(f'Constraint not met (return={repr(result)}): {message}')
        if failure_messages:
            if len(self._constraints) == 1:
                raise InvalidValueError(failure_messages[0])
            else:
                raise InvalidValueError('Does not meet value constraints', failure_messages)

    def _check_value(self, value):
        c_value = self._check_value_type(value)
        self.check_constraints(c_value)
        return c_value

    def check_value(self, value):
        if self._is_unset(value) and self.optional:
            value = self.default()
        return self._check_value(value)

    def __call__(self, **kwds):
        return self.copy(**kwds)

    def _check_value_type(self, value):
        raise NotImplementedError()

    def type_name(self) -> str:
        raise NotImplementedError()

    def copy(self, **kwds):
        raise NotImplementedError()


SimpleType = Union[type, bool, type(None)]  # All types in this Union must also work with isinstance()
BaseType = Union[SimpleType, Spec, list, set, dict]
Types = Union[BaseType, Tuple[BaseType, ...]]


def canonicalize_base_type(t):
    """Return a Spec instance for list/set/dict/tuple and unmodified value for type/bool/Spec/None"""

    if isinstance(t, (type, bool, Spec)) or t is None:
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
        raise BadSchemaError(f'{repr(t)} is not a valid Type: must be type/bool/Spec/None/tuple/list/set/dict')


def canonicalize_types(types):
    """Convert a Types (possibly one BaseType) to a tuple of canonicalized base types"""
    c_types = []
    if isinstance(types, tuple):
        for t in types:
            c_types.append(canonicalize_base_type(t))
    else:
        c_types.append(canonicalize_base_type(types))
    return tuple(c_types)


def get_base_type_name(t: BaseType):
    """Get the string name for a canonicalized BaseType"""
    if isinstance(t, type):
        return t.__name__
    elif isinstance(t, Spec):
        return t.type_name()
    else:
        return repr(t)


def get_types_names(types: Types):
    """Get the string name for a canonicalized Types"""
    if not isinstance(types, tuple):
        return [get_base_type_name(types)]
    return [get_base_type_name(t) for t in types]


def must_be_msg(types: Types):
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
        raise BadSchemaError(f'Invalid schema definition -- unknown type spec value {repr(t)}')
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
# All other exceptions will immediately propagate, including InvalidValueError, however an InvalidValueError from an
# instance of Type is very likely to be caught and aggregated by a TypeSpec/IterSpec/DictSpec
_canonicalization_invalidating_exceptions = (ValueError, TypeError, AttributeError, KeyError)


class Type(Spec):
    """Spec for a single simple type.

    Capable of value canonicalization.
    """

    def __init__(self,
                 t: SimpleType,
                 canonicalize: Optional[Callable[[Any], Any]] = None,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = is_implicitly_falsey,
                 constraints: Optional[Constraints] = None):
        if not isinstance(t, SimpleType.__args__):
            raise BadSchemaError('Type may only be used with one of: type/True/False/None')
        self.type = t
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
            raise InvalidValueError(f'{e.__class__.__name__} during canonicalization: {str(e)}')

    def _check_value_type(self, value):
        value = check_value_base_type(self.type, value)
        return self.canonicalize(value)

    def type_name(self) -> str:
        return get_base_type_name(self.type)

    def copy(self, **kwds):
        kwds.setdefault('t', self.type)
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
                 constraints: Optional[Constraints] = None,
                 optional: bool = False,
                 is_unset: Validator = lambda value: not value,
                 default: Any = None):
        if optional and None not in values:
            values = [*values, None]
        self.values = frozenset(values)
        optional = None in values
        Type.__init__(self, None, canonicalize, optional, default, is_unset, constraints)
        self._hash = hash((self._hash, EnumSpec, self.values))

    def _check_value_type(self, value):
        if value in self.values:
            return self.canonicalize(value)
        else:
            raise InvalidValueNoTypeMatch(f'Must match be {self.type_name()}')

    def type_name(self) -> str:
        return 'enum=' + '/'.join([repr(v) for v in self.values])

    def copy(self, **kwds):
        kwds.setdefault('values', self.values)
        kwds.setdefault('canonicalize', self._canonicalize)
        self._set_default_kwds(kwds)
        return EnumSpec(**kwds)


class TypeSpec(Spec):
    """Spec for a union of types, or in other words a type that is an enumeration of types (not values).

    Note that including `None` in `types` is equivalent to setting the `optional` flag True.

    Not capable of value canonicalization. Embed a Type/EnumSpec for a specific type if canonicalization is needed.
    """

    def __init__(self,
                 types: Types,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = is_implicitly_falsey,
                 constraints: Optional[Constraints] = None):
        types = canonicalize_types(types)
        if optional and None not in types:
            types = (*types, None)
        optional = None in types
        self.types = types
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, TypeSpec, types))

    def _check_value_type(self, value):
        return check_value_types(self.types, value)

    def type_name(self) -> str:
        return '/'.join(get_types_names(self.types))

    def copy(self, **kwds):
        kwds.setdefault('types', self.types)
        self._set_default_kwds(kwds)
        return TypeSpec(**kwds)


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
                 constraints: Optional[Constraints] = None):
        self.types = canonicalize_types(types)
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, IterSpec, c_type, types))

    def _check_value_type(self, value):
        if not isinstance(value, _runtime_iterable):
            raise InvalidValueNoTypeMatch(f'Must be collection or iterable')

        c_values = []
        failure_messages = []
        for i, l_value in enumerate(value):
            try:
                c_values.append(check_value_types(self.types, l_value))
            except InvalidValueError as e:
                failure_messages.append(f'Index {i} is invalid: {str(e)}')
        if failure_messages:
            raise InvalidValueError('Items do not conform with iterable spec', failure_messages)
        return self.c_type(c_values)

    def type_name(self) -> str:
        return self.c_type.__name__

    def copy(self, **kwds):
        kwds.setdefault('types', self.types)
        kwds.setdefault('c_type', self.c_type)
        self._set_default_kwds(kwds)
        return IterSpec(**kwds)


class SeqSpec(Spec):
    """Spec for a sequence where specific types must appear in a specific sequence.

    By default, canonicalizes the sequence to a Python `tuple`; no other value canonicalization is supported. Embed
    a Type/EnumSpec to canonicalize specific sequence elements based on their type.

    Does not support variable-length sequences. `type_sequence` and a value under validation must have the same length.
    """
    def __init__(self,
                 type_sequence: Sequence[Types],
                 c_type: BaseIterable = tuple,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = lambda value: not value,
                 constraints: Optional[Constraints] = None):
        self.type_sequence = type_sequence
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, SeqSpec, c_type, type_sequence))

    def copy(self, **kwds):
        kwds.setdefault('type_sequence', self.type_sequence)
        kwds.setdefault('c_type', self.c_type)
        self._set_default_kwds(kwds)
        return SeqSpec(**kwds)

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


class Reference(object):
    """Used in `references` for DictSpec along with a key"""

    def __init__(self,
                 test: Optional[Tuple[ReferenceValidator, str]] = None,
                 update: Optional[Tuple[ReferenceValidator, Callable[[dict, Any], Any]]] = None):
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


TypeKeySpecs = Iterable[Tuple[BaseType, Types]]


def check_type_key_spec(type_key_specs: TypeKeySpecs, key: Any, value: Any) -> Tuple[Any, Any]:
    for type_key, spec in type_key_specs:
        try:
            c_key = check_value_base_type(type_key, key)
        except InvalidValueError:
            continue
        try:
            c_value = check_value_types(spec, value)
            return c_key, c_value
        except InvalidValueError as e:
            raise InvalidValueError(f'Value for key {repr(key)} does not conform with spec: {str(e)}')
    raise InvalidValueNoTypeMatch('No match for dict type keys')


SequenceSchema = Optional[Sequence[Tuple[Hashable, Types]]]
_not_a_type_key = object()


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
                 schema: Optional[Dict[Hashable, Types]] = None,
                 value_key_specs: SequenceSchema = None,
                 type_key_specs: SequenceSchema = None,
                 references: Optional[Sequence[Tuple[Hashable, Reference]]] = None,
                 optional: bool = False,
                 default: Any = dict,
                 is_unset: Validator = lambda value: not value,
                 constraints: Optional[Constraints] = None):

        if not schema and not value_key_specs and not type_key_specs:
            raise BadSchemaError('At least one of schema or value_key_specs/type_key_specs must be specified')

        _all_keys = []
        if schema:
            if value_key_specs or type_key_specs:
                raise BadSchemaError('May not specify both schema and value_key_specs/type_key_specs')
            value_key_specs = []
            type_key_specs = []
            for key, spec in schema.items():
                try:
                    hash(key)
                except TypeError:
                    raise BadSchemaError('DictSpec keys must be Hashable')
                _all_keys.append(key)
                try:
                    type_key = canonicalize_base_type(key)
                except BadSchemaError:
                    type_key = _not_a_type_key
                spec = canonicalize_base_type(spec)
                if type_key is _not_a_type_key:
                    value_key_specs.append((key, spec))
                else:
                    type_key_specs.append((type_key, spec))
        if type_key_specs:
            for k, _ in type_key_specs:
                _all_keys.append(k)
        if value_key_specs:
            for k, _ in value_key_specs:
                _all_keys.append(k)

        self._keys_must_be = must_be_msg(_all_keys)
        self.value_key_specs = tuple(value_key_specs)
        self.type_key_specs = tuple(type_key_specs)
        if references:
            self.references = tuple(references)
        else:
            self.references = tuple()

        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, DictSpec, self.type_key_specs, self.value_key_specs, self.references))

    def copy(self, **kwds):
        kwds.setdefault('type_key_specs', self.type_key_specs)
        kwds.setdefault('value_key_specs', self.value_key_specs)
        kwds.setdefault('references', self.references)
        self._set_default_kwds(kwds)
        return DictSpec(**kwds)

    def type_name(self) -> str:
        return 'dict'

    def _check_value_type(self, mapping):
        if not isinstance(mapping, dict):
            raise InvalidValueNoTypeMatch('Must be dict')

        failure_messages = []
        unhandled_keys = set(mapping.keys())
        c_mapping = {}

        # check for exact key matches
        for key, spec in self.value_key_specs:
            try:
                unhandled_keys.remove(key)
                value = mapping[key]
                c_mapping[key] = check_value_base_type(spec, value)
            except KeyError:
                if isinstance(spec, Spec) and spec.optional:
                    d_value = spec.default()
                    c_mapping[key] = spec.check_value(d_value)
                else:
                    failure_messages.append(f'Missing required mapping key {repr(key)}')
            except InvalidValueError as e:
                failure_messages.append(f'Invalid value for key {repr(key)}: {str(e)}')

        # check for key type matches
        if unhandled_keys and self.type_key_specs:
            for key in list(unhandled_keys):
                value = mapping[key]
                try:
                    c_key, c_value = check_type_key_spec(self.type_key_specs, key, value)
                    unhandled_keys.remove(key)
                    c_mapping[c_key] = c_value
                except InvalidValueNoTypeMatch:
                    pass
                except InvalidValueError as e:
                    failure_messages.append(str(e))
                    unhandled_keys.remove(key)

        if unhandled_keys:
            unhandled_keys = ", ".join([repr(key) for key in unhandled_keys])
            failure_messages.append(f'Keys {unhandled_keys} are unhandled; valid keys {self._keys_must_be}')

        if failure_messages:
            raise InvalidValueError('Does not conform with dict schema', failure_messages)

        # handle any references
        failure_messages = []
        if self.references:
            for key, ref_spec in self.references:
                try:
                    value = c_mapping[key]
                    c_mapping[key] = ref_spec.evaluate(c_mapping, value)
                except InvalidValueError as e:
                    failure_messages.append(str(e))

        if failure_messages:
            raise InvalidValueError('Does not comply with dict reference spec', failure_messages)

        return c_mapping
