#!/usr/bin/env python3
"""Test the print injection logic locally"""

import ast

code = """
import unittest

def sum_numbers(numbers):
    return sum(numbers)

class TestSumNumbers(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(sum_numbers([]), 0)

    def test_single(self):
        self.assertEqual(sum_numbers([5]), 5)
"""

def inject_prints(code: str) -> str:
    try:
        tree = ast.parse(code)
    except Exception as exc:
        print(f"Failed to parse: {exc}")
        return code

    class AssertPrintInjector(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if not node.name.startswith("test"):
                return node

            print(f"\n Processing test function: {node.name}")
            new_body = []

            for stmt in node.body:
                print(f"  Statement type: {type(stmt).__name__}")

                # Handle unittest assertions
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                    print(f"    Found Call")

                    if isinstance(call.func, ast.Attribute):
                        print(f"      Attribute: {call.func.attr}")
                        if isinstance(call.func.value, ast.Name):
                            print(f"        Name: {call.func.value.id}")

                            if (call.func.value.id == 'self' and
                                call.func.attr.startswith('assert') and
                                len(call.args) >= 1):
                                print(f"        ✅ MATCH! Will inject print for: {ast.unparse(call.args[0])}")
                                self._add_print_statements(new_body, call.args[0])

                new_body.append(stmt)

            node.body = new_body
            return node

        def _add_print_statements(self, new_body, expr):
            """Helper to add print statements"""
            new_body.append(ast.Expr(
                value=ast.Call(
                    func=ast.Name(id='print', ctx=ast.Load()),
                    args=[ast.Constant(value="\n=== Program Output ===")],
                    keywords=[]
                )
            ))
            new_body.append(ast.Expr(
                value=ast.Call(
                    func=ast.Name(id='print', ctx=ast.Load()),
                    args=[expr],
                    keywords=[]
                )
            ))
            new_body.append(ast.Expr(
                value=ast.Call(
                    func=ast.Name(id='print', ctx=ast.Load()),
                    args=[ast.Constant(value="===================\n")],
                    keywords=[]
                )
            ))

    injector = AssertPrintInjector()
    modified_tree = injector.visit(tree)

    try:
        modified_code = ast.unparse(modified_tree)
        return modified_code
    except Exception as exc:
        print(f"Failed to unparse: {exc}")
        return code

print("Original code:")
print("=" * 60)
print(code)
print("=" * 60)

modified = inject_prints(code)

print("\n\nModified code:")
print("=" * 60)
print(modified)
print("=" * 60)
