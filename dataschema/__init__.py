from typing import Optional, Dict, Tuple, Callable, Any, Union, Iterable, Hashable


class InvalidValueError(Exception):
    def __init__(self, msg, error_count=1):
        Exception.__init__(self, msg)
        self.error_count = error_count


class BadSchemaError(Exception):
    pass


Validator = Callable[[Any], bool]

Constraint = Tuple[Validator, str]
Constraints = Union[Constraint, Iterable[Constraint]]


class Spec(object):
    def __init__(self,
                 optional: bool,
                 default: Any = None,
                 is_unset: Validator = lambda value: not value and value is not False and not isinstance(value, (int, float)),
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
                raise BadSchemaError(f'Invalid schema, default value is spec-invalid: {e.args[0]}')
        self._hash = None
        self._base_hash = (optional, default, is_unset, constraints)

    def __hash__(self):
        if self._hash is None:
            raise RuntimeError('Programming error - class did not set self._hash')
        return self._hash

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
        for c, message in self._constraints:
            result = c(value)
            if not result:
                raise InvalidValueError(f'Constraint not met (result={repr(result)}): {message}')

    def _check_value(self, value):
        c_value = self._check_value_type(value)
        self.check_constraints(c_value)
        return c_value

    def check_value(self, value):
        if self._is_unset(value) and self.optional:
            value = self.default()
        return self._check_value(value)

    def _check_value_type(self, value):
        raise NotImplementedError()

    def type_name(self) -> str:
        raise NotImplementedError()


BaseType = Union[type, Spec, bool, None]
Types = Union[BaseType, Tuple[BaseType, ...]]


def get_type_name(t: BaseType):
    if isinstance(t, type):
        return t.__name__
    elif isinstance(t, Spec):
        return t.type_name()
    else:
        return repr(t)


def get_types_names(types: Types):
    if not isinstance(types, tuple):
        return [get_type_name(types)]
    return [get_type_name(t) for t in types]


def must_be_msg(types: Types):
    if not isinstance(types, tuple):
        return 'Must be ' + get_type_name(types)
    elif len(types) == 1:
        return 'Must be ' + get_type_name(types[0])
    else:
        return 'Must be one of: ' + ', '.join(get_types_names(types))


class InvalidValueNoTypeMatch(InvalidValueError):
    pass


def check_value_base_type(t: BaseType, value: Any):
    if isinstance(t, type):
        if isinstance(value, t):
            return value
    elif isinstance(t, Spec):
        return t.check_value(value)
    elif isinstance(t, bool):
        if value is t:
            return value
    elif t is None:
        if value is None:
            return value
    else:
        raise BadSchemaError(f'Invalid schema definition -- unknown type spec value {repr(t)}')
    raise InvalidValueNoTypeMatch(must_be_msg(t))


def check_value_types(types: Types, value: Any):
    if isinstance(types, tuple):
        for t in types:
            try:
                return check_value_base_type(t, value)
            except InvalidValueNoTypeMatch:
                pass
        raise InvalidValueNoTypeMatch(must_be_msg(types))
    else:
        return check_value_base_type(types, value)


class Type(Spec):
    def __init__(self,
                 t: BaseType,
                 canonicalize: Optional[Callable[[Any], Any]] = None,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = lambda value: not value and not isinstance(value, (int, float)),
                 constraints: Optional[Constraints] = None):
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
        except ValueError as e:
            raise InvalidValueError(f'ValueError during canonicalization: {str(e)}')
        except TypeError as e:
            raise InvalidValueError(f'TypeError during canonicalization: {str(e)}')

    def _check_value_type(self, value):
        value = check_value_base_type(self.type, value)
        return self.canonicalize(value)

    def type_name(self) -> str:
        return get_type_name(self.type)


class EnumSpec(Type):
    def __init__(self,
                 values: Iterable[Hashable],
                 canonicalize: Optional[Callable[[Any], Any]] = None,
                 constraints: Optional[Constraints] = None,
                 optional: bool = False,
                 is_unset: Validator = lambda value: not value,
                 default: Any = None):
        self.values = values
        Type.__init__(self, None, canonicalize, optional, default, is_unset, constraints)
        self._hash = hash((self._hash, EnumSpec, frozenset(values)))

    def _check_value_type(self, value):
        if value in self.values:
            return self.canonicalize(value)
        else:
            raise InvalidValueNoTypeMatch(f'Must match be {self.type_name()}')

    def type_name(self) -> str:
        return 'enum=' + '/'.join([repr(v) for v in self.values])


class TypeSpec(Spec):
    def __init__(self,
                 types: Types,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = lambda value: not value and not isinstance(value, (int, float)),
                 constraints: Optional[Constraints] = None):
        if not isinstance(types, tuple):
            types = (types,)
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


def check_value_iterable(c_type, types, value):
    if not isinstance(value, c_type):
        raise InvalidValueNoTypeMatch(f'Must be {c_type.__name__}')

    c_values = []
    failure_messages = []
    for i, l_value in enumerate(value):
        try:
            c_values.append(check_value_types(types, l_value))
        except InvalidValueError as e:
            failure_messages.append(f'Index {i} is invalid: {e.args[0]}')
    if failure_messages:
        raise InvalidValueError('Items do not conform with iterable spec:\n' + '\n'.join(failure_messages),
                                error_count=len(failure_messages))
    return c_type(c_values)


class IterSpec(Spec):
    def __init__(self,
                 types: Types,
                 c_type=list,
                 optional: bool = False,
                 default: Any = list,
                 is_unset: Validator = lambda value: not value,
                 constraints: Optional[Constraints] = None):
        self.types = types
        self.c_type = c_type
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, IterSpec, c_type, types))

    def _check_value_type(self, value):
        return check_value_iterable(self.c_type, self.types, value)

    def type_name(self) -> str:
        return self.c_type.__name__


ReferenceChecker = Callable[[dict, Any], bool]


class RefSpec(object):
    def __init__(self,
                 test: Optional[Tuple[ReferenceChecker, str]] = None,
                 update: Optional[Tuple[ReferenceChecker, Callable[[dict, Any], Any]]] = None,
                 optional: bool = False):
        if not update and not test:
            raise BadSchemaError('At least one of update or test must be set')
        self._update = update
        self._test = test
        self.optional = optional
        self._hash = hash((RefSpec, test, update, optional))

    def __hash__(self):
        return self._hash

    def evaluate(self, root_config, value):
        if self._update:
            if self._update[0](root_config, value):
                value = self._update[1](root_config, value)
        if self._test:
            if self._test[0](root_config, value):
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
            raise InvalidValueError(f'Value for key {repr(key)} does not conform with spec: {e.args[0]}')
    raise InvalidValueNoTypeMatch('No match for dict type keys')


class DictSpec(Spec):
    def __init__(self,
                 schema: Dict[Hashable, Types],
                 references: Optional[Dict[Hashable, RefSpec]] = None,
                 optional: bool = False,
                 default: Any = dict,
                 is_unset: Validator = lambda value: not value,
                 constraints: Optional[Constraints] = None):
        self.schema = schema
        self.references = references
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._hash = hash((self._base_hash, DictSpec, frozenset(self.schema.items()), frozenset(self.references.items())))

    def type_name(self) -> str:
        return 'dict'

    def _check_value_type(self, mapping):
        if not isinstance(mapping, dict):
            raise InvalidValueNoTypeMatch('Must be dict')

        unhandled_keys = set(mapping.keys())
        failure_messages = []
        c_mapping = {}

        type_key_specs = []

        # check for exact key matches
        for key, spec in self.schema.items():
            if isinstance(key, type):
                type_key_specs.append((key, spec))
                continue
            try:
                value = mapping[key]
                unhandled_keys.remove(key)
                c_mapping[key] = check_value_types(spec, value)
            except KeyError:
                if isinstance(spec, Spec) and spec.optional:
                    d_value = spec.default()
                    c_mapping[key] = spec.check_value(d_value)
                else:
                    failure_messages.append(f'Missing required config key {repr(key)}')
            except InvalidValueError as e:
                failure_messages.append(f'Invalid value for key {repr(key)}: {e.args[0]}')

        # check for key type matches
        if unhandled_keys and type_key_specs:
            for key in list(unhandled_keys):
                value = mapping[key]
                try:
                    c_key, c_value = check_type_key_spec(type_key_specs, key, value)
                    unhandled_keys.remove(key)
                    c_mapping[c_key] = c_value
                except InvalidValueNoTypeMatch:
                    pass
                except InvalidValueError as e:
                    failure_messages.append(e.args[0])
                    unhandled_keys.remove(key)

        if unhandled_keys:
            unhandled_keys = ", ".join([repr(key) for key in unhandled_keys])
            valid_keys = ', '.join(get_types_names(self.schema.keys()))
            failure_messages.append(f'Keys {unhandled_keys} are unhandled; valid keys are: {valid_keys}')

        if failure_messages:
            raise InvalidValueError('Does not conform with dict spec:\n' + '\n'.join(failure_messages),
                                    error_count=len(failure_messages))

        # handle any references
        failure_messages = []
        if self.references:
            for key, ref_spec in self.references.items():
                try:
                    value = c_mapping[key]
                    c_mapping[key] = ref_spec.evaluate(mapping, value)
                except InvalidValueError as e:
                    failure_messages.append(e.args[0])
                except KeyError:
                    if ref_spec.optional:
                        pass
                    else:
                        failure_messages.append(f'Missing required reference key {repr(key)}')

        if failure_messages:
            raise InvalidValueError('Does not comply with dict reference spec:\n' + '\n'.join(failure_messages),
                                    error_count=len(failure_messages))

        return c_mapping
