import unittest

from invoice.pricing import line_total


class LineTotalTests(unittest.TestCase):
    def test_multiplies_price_by_quantity(self):
        self.assertEqual(line_total(250, 4), 1000)

    def test_zero_quantity_costs_nothing(self):
        self.assertEqual(line_total(250, 0), 0)
