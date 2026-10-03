import unittest

from invoice.pricing import bulk_total, line_total


class LineTotalTests(unittest.TestCase):
    def test_multiplies_price_by_quantity(self):
        self.assertEqual(line_total(250, 4), 1000)

    def test_zero_quantity_costs_nothing(self):
        self.assertEqual(line_total(250, 0), 0)


class BulkTotalTests(unittest.TestCase):
    def test_small_orders_pay_full_price(self):
        self.assertEqual(bulk_total(250, 9), 2250)

    def test_ten_or_more_units_get_ten_percent_off(self):
        self.assertEqual(bulk_total(250, 10), 2250)
        self.assertEqual(bulk_total(100, 20), 1800)
