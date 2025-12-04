#!/usr/bin/env python3
"""Debug script to inspect AST structure of unittest code"""

import ast

code = """
import unittest

def sum_numbers(numbers):
    return sum(numbers)

class TestSumNumbers(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(sum_numbers([]), 0)
"""

tree = ast.parse(code)

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
        print(f"Found test function: {node.name}")
        for stmt in node.body:
            print(f"  Statement type: {type(stmt).__name__}")
            if hasattr(stmt, 'value'):
                print(f"    Value type: {type(stmt.value).__name__}")
                if isinstance(stmt.value, ast.Call):
                    print(f"      Call func: {ast.unparse(stmt.value.func)}")
                    print(f"      Call args: {[ast.unparse(arg) for arg in stmt.value.args]}")
