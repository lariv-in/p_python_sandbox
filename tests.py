"""Tests for Python executor."""

import unittest
from .executor import execute_code


class TestBasics(unittest.TestCase):
    def test_simple(self):
        r = execute_code("result = 2 + 2")
        self.assertTrue(r.success)
        self.assertEqual(r.result, 4)

    def test_print(self):
        r = execute_code('print("Hello")')
        self.assertTrue(r.success)
        self.assertIn("Hello", r.output)

    def test_loop(self):
        r = execute_code("result = sum(range(100))")
        self.assertTrue(r.success)
        self.assertEqual(r.result, 4950)

    def test_import(self):
        r = execute_code("import json; result = json.dumps({'a': 1})")
        self.assertTrue(r.success)
        self.assertEqual(r.result, '{"a": 1}')

    def test_timeout(self):
        r = execute_code("while True: pass", timeout=1)
        self.assertFalse(r.success)
        self.assertEqual(r.error_type, "TimeoutError")

    def test_error(self):
        r = execute_code("1/0")
        self.assertFalse(r.success)
        self.assertEqual(r.error_type, "ZeroDivisionError")


def run_quick_test():
    print("=" * 50)
    print("Python Executor Quick Test")
    print("=" * 50)

    print("\n1. Basic:")
    r = execute_code("result = 2 + 2")
    print(f"   2+2 = {r.result} (success: {r.success})")

    print("\n2. Print:")
    r = execute_code('print("Hello!")')
    print(f"   Output: {r.output.strip()}")

    print("\n3. Import:")
    r = execute_code("import math; result = math.sqrt(16)")
    print(f"   sqrt(16) = {r.result} (success: {r.success})")

    print("\n4. Loop:")
    r = execute_code("result = sum(i*i for i in range(10))")
    print(f"   Sum of squares: {r.result}")

    print("\n5. Timeout (1s):")
    r = execute_code("while True: pass", timeout=1)
    print(f"   Killed: {r.error_type}")

    print("\n6. File I/O:")
    r = execute_code("""
with open('test.txt', 'w') as f:
    f.write('hello')
with open('test.txt') as f:
    result = f.read()
""")
    print(f"   Read back: {r.result}, files: {r.temp_files}")

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        run_quick_test()
    else:
        unittest.main()
