"""Catalogue row building, without calling Brickset. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_catalogue as bc  # noqa: E402

FACTORS = {"US": 1.0, "UK": 1.25, "CA": 0.75}
TODAY = "2026-10-15"


def s(number, year, legocom, tags=None):
    return {"number": number, "name": "x", "theme": "t", "subtheme": "", "year": year, "pieces": 1,
            "LEGOCom": legocom, "extendedData": {"tags": tags or []}}


class TestToRow(unittest.TestCase):
    def test_euro_price_wins(self):
        r = bc.to_row(s("10316", 2023, {"DE": {"retailPrice": 499.99, "dateFirstAvailable": "2023-02-09"},
                                        "UK": {"retailPrice": 429.99}}), TODAY, FACTORS)
        self.assertEqual((r["rrp"], r["rrp_region"], r["rrp_approx"], r["retired"]), (499.99, "DE", "", "no"))

    def test_fallback_is_approximate_us_first(self):
        lc = {"US": {"retailPrice": 99.99, "dateFirstAvailable": "2013-06-01", "dateLastAvailable": "2014-12-02"},
              "UK": {"retailPrice": 89.99}, "DE": {}}
        r = bc.to_row(s("79008", 2013, lc), TODAY, FACTORS)
        self.assertEqual((r["rrp"], r["rrp_region"], r["rrp_approx"], r["retired"]), (99.99, "US", "yes", "yes"))
        r = bc.to_row(s("79008", 2013, {"UK": {"retailPrice": 80.0}}), TODAY, FACTORS)
        self.assertEqual((r["rrp"], r["rrp_region"]), (100.0, "UK"))

    def test_calibration_uses_median_ratio(self):
        sets = [s(str(i), 2020, {"DE": {"retailPrice": 100.0}, "US": {"retailPrice": 100.0},
                                 "UK": {"retailPrice": 90.0}}) for i in range(40)]
        f = bc.calibrate(sets, {"GBP": 0.85, "USD": 1.1, "CAD": 1.5})
        self.assertAlmostEqual(f["US"], 1.0)
        self.assertAlmostEqual(f["UK"], 100 / 90)
        self.assertAlmostEqual(f["CA"], 1 / 1.5)  # no CA data: ECB fallback

    def test_no_data_old_set_is_retired_new_set_is_not(self):
        self.assertEqual(bc.to_row(s("9469", 2012, {}), TODAY, FACTORS)["retired"], "yes")
        self.assertEqual(bc.to_row(s("99999", 2025, {}), TODAY, FACTORS)["retired"], "no")

    def test_promo_has_no_price(self):
        r = bc.to_row(s("40893", 2026, {"US": {"retailPrice": 0}}), TODAY, FACTORS)
        self.assertEqual((r["rrp"], r["promo"]), (None, "yes"))
        r = bc.to_row(s("30999", 2026, {}, tags=["Gift With Purchase"]), TODAY, FACTORS)
        self.assertEqual(r["promo"], "yes")


if __name__ == "__main__":
    unittest.main()
