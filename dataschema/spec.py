from typing import Optional, Any, Union, Callable, Sequence, Tuple

Validator = Callable[[Any], bool]

Constraint = Tuple[Validator, str]
Constraints = Optional[Union[Constraint, Sequence[Constraint]]]

# types that can routinely be explicitly set to a false value and be meaningfully
# different from empty/unset in the context of "data"
_explicitly_falsifiable = (int, float, complex, bool)


def default_is_unset(value):
    """Return True if a value is probably unset/empty, or functionally
    equivalent to such

    This is the default function used to decide if the default should be used
    instead of the value under validation
    """
    return not value and not isinstance(value, _explicitly_falsifiable)


class Spec:
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
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
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
                raise BadSchemaError(f'Invalid schema, default value is spec-invalid: {e}')
        self._hash = None
        self._base_hash = (optional, default, is_unset, constraints)
        self._base_kwds = (
            ('optional', self.optional),
            ('default', self._default),
            ('is_unset', self._is_unset),
            ('constraints', self._constraints),
        )
        self._copy_kwds = ()

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
        failure_messages = []
        for c, message in self._constraints:
            result = c(value)
            if not result:
                failure_messages.append(f'Constraint not met (return={result!r}): {message}')
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

    def _check_value_type(self, value):
        raise NotImplementedError()

    def type_name(self) -> str:
        raise NotImplementedError()

    def _set_default_kwds(self, kwds: dict):
        for key, value in self._base_kwds:
            kwds.setdefault(key, value)

    def copy(self, **kwds):
        self._set_default_kwds(kwds)
        for kwd in self._copy_kwds:
            kwds.setdefault(kwd, getattr(self, kwd))
        return self.__class__(**kwds)

    def __call__(self, **kwds):
        return self.copy(**kwds)
