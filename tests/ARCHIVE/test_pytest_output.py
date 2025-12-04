#!/usr/bin/env python3
"""Test if pytest -s shows print output"""

import subprocess
import tempfile
import os

code = """
import unittest

def sum_numbers(numbers):
    return sum(numbers)

class TestSumNumbers(unittest.TestCase):
    def test_empty_list(self):
        print('\\n=== Program Output ===')
        print(sum_numbers([]))
        print('===================\\n')
        self.assertEqual(sum_numbers([]), 0)

    def test_single(self):
        print('\\n=== Program Output ===')
        print(sum_numbers([5]))
        print('===================\\n')
        self.assertEqual(sum_numbers([5]), 5)
"""

with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
    f.write(code)
    temp_file = f.name

try:
    print("Running pytest with -s flag:")
    print("=" * 60)
    result = subprocess.run(
        ['python', '-m', 'pytest', temp_file, '-v', '-s'],
        capture_output=True,
        text=True,
        timeout=10
    )

    print("STDOUT:")
    print(result.stdout)
    print("\nSTDERR:")
    print(result.stderr)
    print("\nReturn code:", result.returncode)

finally:
    os.unlink(temp_file)
