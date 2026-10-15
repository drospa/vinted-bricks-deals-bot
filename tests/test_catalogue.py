"""Catalogue row building, without calling Brickset. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_catalogue as bc  # noqa: E402

FX = {"GBP": 0.80, "USD": 1.00, "CAD": 1.50}
TODAY = "2026-10-15"


def s(number, year, legocom, tags=None):
    return {"number": number, "name": "x", "theme": "t", "subtheme": "", "year": year, "pieces": 1,
            "LEGOCom": legocom, "extendedData": {"tags": tags or []}}


class TestToRow(unittest.TestCase):
    def test_euro_price_wins(self):
        r = bc.to_row(s("10316", 2023, {"DE": {"retailPrice": 499.99, "dateFirstAvailable": "2023-02-09"},
                                        "UK": {"retailPrice": 429.99}}), TODAY, FX)
        self.assertEqual((r["rrp"], r["rrp_region"], r["rrp_approx"], r["retired"]), (499.99, "DE", "", "no"))

    def test_gbp_fallback_is_approximate(self):
        r = bc.to_row(s("79008", 2013, {"UK": {"retailPrice": 80.0, "dateFirstAvailable": "2013-06-01",
                                               "dateLastAvailable": "2015-01-01"}}), TODAY, FX)
        self.assertEqual((r["rrp"], r["rrp_region"], r["rrp_approx"], r["retired"]), (100.0, "UK", "yes", "yes"))

    def test_no_data_old_set_is_retired_new_set_is_not(self):
        self.assertEqual(bc.to_row(s("9469", 2012, {}), TODAY, FX)["retired"], "yes")
        self.assertEqual(bc.to_row(s("99999", 2025, {}), TODAY, FX)["retired"], "no")

    def test_promo_has_no_price(self):
        r = bc.to_row(s("40893", 2026, {"US": {"retailPrice": 0}}), TODAY, FX)
        self.assertEqual((r["rrp"], r["promo"]), (None, "yes"))
        r = bc.to_row(s("30999", 2026, {}, tags=["Gift With Purchase"]), TODAY, FX)
        self.assertEqual(r["promo"], "yes")


if __name__ == "__main__":
    unittest.main()
