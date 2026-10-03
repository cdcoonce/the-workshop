import unittest

from names.normalize import normalize_name


class NormalizeNameTests(unittest.TestCase):
    def test_trims_and_title_cases(self):
        self.assertEqual(normalize_name("  ada lovelace "), "Ada Lovelace")
