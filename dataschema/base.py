from __future__ import annotations

from abc import ABC
from typing import Optional, Any, Union, Callable, Sequence, Tuple

from ._utils import InvalidValueError, BadSchemaError

Validator = Callable[[Any], bool]


class Constraint:
    """
    A generic constraint based on a callable that returns a True value if the constraint is met.
    """
    def __init__(self,
                 test: Validator,
                 message: str):
        """
        ---
        test: A callable which returns a False value if the constraint is not met
        message: The message to put in an `InvalidValueError` if the constraint is not met
        """
        self.test = test
        self.message = message

    def evaluate(self, value):
        result = self.test(value)
        if not result:
            raise InvalidValueError(self.message)


ConstraintTuple = Tuple[Validator, str]
_Constraint = Union[Constraint, ConstraintTuple]
Constraints = Optional[Union[_Constraint, Sequence[_Constraint]]]

# types that can routinely be explicitly set to a false value and be meaningfully
# different from empty/unset in the context of "data"
_explicitly_falsifiable = (int, float, complex, bool)


def default_is_unset(value: Any) -> bool:
    """Return True if a value is probably unset/empty, or functionally
    equivalent to such

    This is the default function used to decide if the default should be used
    instead of the value under validation
    """
    return not value and not isinstance(value, _explicitly_falsifiable)


def canonicalize_constraints(constraints: Constraints) -> Tuple[Constraint, ...]:
    if not constraints:
        return tuple()
    if isinstance(constraints, Constraint):
        return (constraints,)
    try:
        if not isinstance(constraints[0], (tuple, Constraint)):
            return (Constraint(*constraints),)
    except TypeError:
        raise BadSchemaError('single constraint must be Constraint or tuple[Validator, str]')
    try:
        result = []
        for constraint in constraints:
            if isinstance(constraint, Constraint):
                result.append(constraint)
            elif isintance(constraint, tuple):
                result.append(Constraint(*constraint))
            else:
                raise BadSchemaError('elements of constraints must be tuple or Constraint')
        return tuple(result)
    except TypeError:
        raise BadSchemaError('constraints must be iterable')


class Spec:
    """Abstract base class for all Spec / schema elements"""
    _hash_props: Tuple[str] = ()

    def __init__(self,
                 optional: bool,
                 default: Any = None,
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
        """
        ---
        optional: Set to True to mark this Spec as optional
        default: |
            * A value to return if the `is_unset` function returns True, OR
            * A callable (as determined by the `callable()` builtin) which returns the value to use as default
        is_unset: |
            A function accepting a value under validation, and returning True if the value is considered unset, and
            therefore that the `default` should be returned instead of attempting to validate the value
        constraints: A single `Constraint` or an iterable of `Constraint`
        """
        self.optional = optional
        self._default = default
        self._is_unset = is_unset
        self._constraints = canonicalize_constraints(constraints)
        if optional:
            try:
                d_value = self.default()
                self._check_value(d_value)
            except InvalidValueError as e:
                raise BadSchemaError(f'Invalid schema, default value is spec-invalid: {e}')
        self._base_kwds = (
            ('optional', self.optional),
            ('default', self._default),
            ('is_unset', self._is_unset),
            ('constraints', self._constraints),
        )
        self._base_hash_vals = (self.__class__, optional, default, is_unset, constraints)
        self._hash = None

    def __hash__(self):
        if self._hash is None:
            self._hash = hash((
                *self._base_hash_vals,
                *(getattr(self, name) for name in self._hash_props)
            ))
        return self._hash

    def default(self) -> Any:
        """Get the default value.

        Either returns the `default` constructor argument, or calls and reutnrs it if it's `callable()`
        """
        if callable(self._default):
            return self._default()
        else:
            return self._default

    def check_constraints(self, value: Any) -> None:
        """Check the passed value against any constraints passed to this Spec

        Raises an `InvalidValueError` if invalid, otherwise returns None.
        """
        if not self._constraints:
            return
        if self._is_unset(value) and self.optional:
            return
        failure_messages = []
        for constraint in self._constraints:
            try:
                constraint.evaluate(value)
            except InvalidValueError as e:
                failure_messages.append(str(e))
        if failure_messages:
            if len(self._constraints) == 1:
                raise InvalidValueError(f'Does not meet value constraint: {failure_messages[0]}')
            else:
                raise InvalidValueError('Does not meet value constraints', failure_messages)

    def check_value(self, value: Any) -> Any:
        """Validate that a value conforms with the entire Spec. The primary interface to a schema.

        If valid, returns a canonicalized version of the value (for example, an `IterSpec` will
        return a list for any iterable passed to `check_value`).

        If invalid, raises an InvalidValueError.
        """
        if self._is_unset(value) and self.optional:
            value = self.default()
        c_value = self._check_value(value)
        self.check_constraints(c_value)
        return c_value

    def _check_value(self, value):
        raise NotImplementedError()

    def type_name(self) -> str:
        raise NotImplementedError()

    def _set_default_kwds(self, kwds: dict):
        for key, value in self._base_kwds:
            kwds.setdefault(key, value)

    def copy(self, **kwds) -> Spec:
        """Create a copy of this Spec, optionally updating constructor keyword args"""
        self._set_default_kwds(kwds)
        for kwd in self._hash_props:
            kwds.setdefault(kwd, getattr(self, kwd))
        return self.__class__(**kwds)

    def add_constraints(self, constraints: Constraints) -> Spec:
        """Create a copy of this Spec with new constraints appended to the sequence"""
        return self.copy(constraints=(
            *self._constraints,
            *canonicalize_constraints(constraints)
        ))

    def __call__(self, **kwds):
        return self.copy(**kwds)


# These get converted to an InvalidValueError when caught during canonicalization
# All other exceptions will immediately propagate, including InvalidValueError
_canonicalization_invalidating_exceptions = (ValueError, TypeError, AttributeError, KeyError)

Canonicalize = Optional[Callable[[Any], Any]]


class Canonicalizable(Spec, ABC):
    """Abstract base class for Spec that can be canonicalized"""
    _canonicalization_invalid_exception: Exception = InvalidValueError

    def __init__(self,
                 canonicalize: Canonicalize = None,
                 optional: bool = False,
                 default: Any = None,
                 is_unset: Validator = default_is_unset,
                 constraints: Constraints = None):
        """
        ---
        canonicalize: Callable that transforms the identified value of the subclass instance into another value or type
        """
        self._canonicalize = canonicalize
        Spec.__init__(self, optional, default, is_unset, constraints)
        self._base_hash_vals = (*self._base_hash_vals, canonicalize)
        self._base_kwds = (
            *self._base_kwds,
            ('canonicalize', canonicalize),
        )

    def canonicalize(self, value: Any) -> Any:
        """Attempt to canonicalize a value under validation"""
        try:
            if self._canonicalize:
                return self._canonicalize(value)
            else:
                return value
        except _canonicalization_invalidating_exceptions as e:
            raise self._canonicalization_invalid_exception(f'{e.__class__.__name__} during canonicalization: {e}')

    def check_value(self, value: Any) -> Any:
        c_value = Spec.check_value(self, value)
        return self.canonicalize(c_value)
