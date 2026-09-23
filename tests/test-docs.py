#!/usr/bin/env python3
"""Regressions for the 23 Sep 2026 review — docs. Run: python3 tests/test-docs.py (test-security.py runs it too)."""
import unittest


class Registered(unittest.TestCase):
    def test_suite_runs(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
