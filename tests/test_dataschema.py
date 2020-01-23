import dataschema

import unittest

typical_data_types = (
    (str, "a string", 5),
    (int, 5, "not an int"),
    (float, 4.2, 5),
    (bool, False, "not a bool"),
    (type(None), None, "not none"),
    (list, ["a list", 5, 4.2, complex(5, 4), frozenset((5, 6, 7))], "not a list"),
    (dict, {"a dict": 5, frozenset((1, 2, 3)): complex(4, 2)}, 174),
    (True, True, "NOT TRUE!"),
    (False, False, True),
    (None, None, 0),
)


class TestDataSchema(unittest.TestCase):
    def test_check_value_base_type(self):
        for simple_type, good_value, bad_value in typical_data_types:
            with self.subTest(f'Test good value for simple type {dataschema.get_base_type_name(simple_type)}'):
                c_value = dataschema.check_value_base_type(simple_type, good_value)
                self.assertEqual(c_value, good_value, msg='Value was mutated')
            with self.subTest(f'Test bad value for simple type {dataschema.get_base_type_name(simple_type)}'):
                with self.assertRaises(dataschema.BadSchemaError):
                    dataschema.check_value_base_type(simple_type, bad_value)

    def test_type_simple(self):
        for simple_type, good_value, bad_value in typical_data_types:
            t = dataschema.Type(simple_type)
            with self.subTest(f'Test good value for simple type {dataschema.get_base_type_name(simple_type)}'):
                c_value = t.check_value(good_value)
                self.assertEqual(c_value, good_value, msg='Value was mutated')
            with self.subTest(f'Test bad value for simple type {dataschema.get_base_type_name(simple_type)}'):
                with self.assertRaises(dataschema.BadSchemaError):
                    t.check_value(bad_value)

    def test_type_canonicalize(self):
        with self.subTest('Test good canonicalize'):
            t = dataschema.Type(str, lambda s: 5)
            c_value = t.check_value("some random string")
            self.assertEqual(c_value, 5)

        with self.subTest('Test canonicalize ValueError'):
            with self.assertRaises(dataschema.BadSchemaError):
                t = dataschema.Type(str, lambda s: int(s))
                t.check_value("definitely not numeric")

        with self.subTest('Test canonicalize TypeError'):
            with self.assertRaises(dataschema.BadSchemaError):
                t = dataschema.Type(str, lambda s: s())
                t.check_value("definitely not callable")

        class TestError(Exception):
            pass

        def raise_test_error(s):
            raise TestError()

        with self.subTest('Verify propagation of other exceptions during canonicalize'):
            with self.assertRaises(TestError):
                t = dataschema.Type(int, raise_test_error)
                t.check_value(5)

    def test_type_invalid_default(self):
        with self.subTest('Type mismatch for default on Type'):
            with self.assertRaises(dataschema.BadSchemaError):
                dataschema.Type(str, default=5, optional=True)

        with self.subTest('Constraint failure for default on Type'):
            with self.assertRaises(dataschema.BadSchemaError):
                dataschema.Type(str,
                                default='foo',
                                constraints=(lambda v: v.startswith('x'), 'Must start with x'),
                                optional=True)

    def test_type_callable_default(self):
        t = dataschema.Type(dict, default=dict, optional=True)
        v1 = t.check_value(None)
        v2 = t.check_value(None)
        self.assertIsInstance(v1, dict)
        self.assertEqual(v1, v2)
        self.assertIsNot(v1, v2)

    def test_type_spec(self):
        t = dataschema.TypeSpec(types=(int, dataschema.Type(str, lambda s: 5), None),
                              default=5,
                              constraints=(lambda v: v == 5, 'Must be 5'))
        valid_5s = (5, "fifty seven", None, "")
        for five in valid_5s:
            with self.subTest(f'Test good value {repr(five)}'):
                c_value = t.check_value(five)
                self.assertEqual(c_value, 5)

        not_valid_5s = (17, True)
        for not_five in not_valid_5s:
            with self.subTest(f'Test bad value {repr(not_five)}'):
                with self.assertRaises(dataschema.InvalidConfigError):
                    t.check_value(not_five)

        t = dataschema.TypeSpec(types=tuple([i[0] for i in typical_data_types]))
        for _, good_value, _ in typical_data_types:
            with self.subTest(f'Test good value with wide union {repr(good_value)}'):
                c_value = t.check_value(good_value)
                self.assertEqual(c_value, good_value)

        bad_value = complex(4, 5)
        with self.subTest(f'Test bad value with wide union {repr(bad_value)}'):
            with self.assertRaises(dataschema.InvalidConfigError):
                t.check_value(bad_value)

    def test_enum_spec(self):
        test_values = ("a string", 5, 6.4, complex(5, 4), frozenset('xyz'))
        t = dataschema.EnumSpec(values=test_values)

        for v in test_values:
            with self.subTest(f'Check enum value {repr(v)}'):
                c_value = t.check_value(v)
                self.assertEqual(c_value, v)

        bad_values = ("another string", 6, 7.5, complex(6, 5), set('abc'))

        for v in bad_values:
            with self.subTest(f'Check bad enum value {repr(v)}'):
                with self.assertRaises(dataschema.InvalidConfigError):
                    t.check_value(v)
