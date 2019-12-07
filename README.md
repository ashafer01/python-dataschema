# dataschema

Define a schema for your data or configurations. Designed to wrap around existing Python types as well as
user-defined classes and functions as thinly as possible. Tries to stay out of your way and be extremely flexible.

*In Development* not yet completely tested or API-stable.

## About

### Basic Overview

There are 5 main classes that make up a data schema. You will choose one of these as the "root" of your data. Component
types may be any Python built-in type, user-defined class, or the specific values `True`, `False`, and `None`.

* `TypeSpec` is similar to a Union type. It may name one or more simple types or other Specs, any of which will
  satisfy the spec.
* `EnumSpec` is for defining an enumerated type, where only by having one of a set of values does a value identify
  as the type. All enumerated values must be Hashable.
* `IterSpec` is for defining an iterable where all elements must conform to one TypeSpec. The number of value elements
  is indeterminate, but may be bounded by use of constraints.
* `SeqSpec` is for defining a sequence where each element must conform to one specific TypeSpec. The number of value
  elements must be exactly equal to the number of specified types.
* `DictSpec` is for defining mapping/dictionary types. Keys may be any specific value (such as a string). They also
  may be any type or Spec, in which case they are treated like a TypeSpec for all keys without a specific value match.
  For both modes of key, the value may be any type or Spec. Validating and canonicalizing cross-references within the
  mapping is also supported (see below).

Three additional classes are available for user consumption.

* `Type` wraps a single simple type. It's main purpose is for use as a component type in another Spec where values of
  this type must be canonicalized into another value or type, potentially based upon the non-canonical value. This
  technically will work as a "root" class but it likely will only decrease efficiency in that case.
* `Spec` is the abstract base class for all 6 classes listed above. Only useful for type-checking.
* `Reference` is used to define `DictSpec` cross-references. More below.

Once you select a root type, you can define your schema and start checking values. For a very quick and simple
example:

```python
from dataschema import TypeSpec, EnumSpec

# "Our data may be any integer, the string "hello", the string "world", the complex number 5+6i, and is optional with a
# default of integer 17"
schema = TypeSpec((int, EnumSpec(("hello", "world", complex(5, 6))), None), default=17)

# All of these succeed and return the canonicalized/normalized schema value shown in the comment
schema.check_value(14)  # 14 -- all ints are valid
schema.check_value(42)  # 42 -- all ints are valid
schema.check_value("hello")  # "hello" -- a valid enumerated value
schema.check_value("world")  # "world" -- a valid enumerated value
schema.check_value(5+6j)  # complex(5, 6) -- a valid enumerated value
schema.check_value(None) # 17 -- default
schema.check_value('')  # 17 -- by default, all falsey non-numeric non-bool values trigger default regardless of type
                        #   Note: the test for whether or not to use the default can be customized

# All of the following are invalid and an InvalidValueError would be raised upon making the call
schema.check_value(4.2)  # float not a valid type
schema.check_value([14, 15, 16])  # list not a valid types
schema.check_value("foo")  # string not a valid type
```

All Spec support the `check_value()` method. It's typically the only method you'll need.

*More in-depth details of each Spec will appear in a future section/document.*


### Backend-Oriented Exception Messages

When data is invalid, a single `InvalidValueError` is thrown. If the schema was for an iterable or mapping, then
each message will be combined and formatted in the single top-level exception. The individual messages are available for
the top-level exception only.

For example: specifying a list of dicts which turns out to be invalid: The exception message for the list contains all
of the messages combined, and there is also a list of messages attached to the exception object describing what caused
each invalid dict to fail, but each of those messages in turn is aggregated describing each invalid dict key/value.
Inner exception objects are caught and disregarded and are not available as "caused by" exceptions or any other means.

The benefit is that checking and normalization/canonicalization happen within one call and with a single\* iteration
over the data.

The tradeoff is that it's hard/impossible to, for example, build a JSON object from a web form, transmit it to the
server and run it through a dataschema, return the results to the browser, and then tell the user which specific fields
in the form are invalid. As mentioned above the messages are essentially always combined and formatted, and they tend
to assume that anyone reading the messages can also read and comprehend the schema.

\* DictSpecs need multiple iterations for some optional features (though iterations beyond the first are typically
partial iterations depending on use case).


TODO *Docs are in progress*
