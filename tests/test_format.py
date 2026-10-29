"""Formatting checks. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from legobot import digest  # noqa: E402


def item(i, title, price, cond="Muy bueno", set_no="?", name="set not identified", rrp=None, figure=False):
    disc = (1 - price / rrp) if rrp else None
    return {"id": i, "title": title, "price": price, "url": f"https://www.vinted.es/items/{i}-x",
            "condition": cond, "set_no": set_no, "set_name": name, "rrp": rrp, "retired": False,
            "discount": disc, "figure": figure, "lot": False, "known_rrp": None, "known_nums": []}


class TestFormat(unittest.TestCase):
    def test_fmt_pct(self):
        self.assertEqual(digest.fmt_pct(0.62), "-62%")
        self.assertEqual(digest.fmt_pct(-0.07), "+7%")
        self.assertEqual(digest.fmt_pct(0.0), "0%")

    def test_no_unicode_minus_and_grouping(self):
        deal = {**item(1, "x", 30, rrp=78, set_no="75102", name="Poe's X-wing"), "theme": "Star Wars"}
        lotr = [
            item(2, "rivendell", 390, set_no="10316", name="The Lord of the Rings: Rivendell", rrp=500),
            item(3, "rivendell", 400, set_no="10316", name="The Lord of the Rings: Rivendell", rrp=500),
            item(4, "elfe minifigurine", 10, set_no="10316", name="The Lord of the Rings: Rivendell",
                 rrp=500, figure=True),
            item(5, "lord of the rings orc", 6),
        ]
        stats = {"scanned": 3, "excluded": Counter({"keywords": 1}), "matched": 1, "unidentified": 1}
        msgs = digest.build_messages([deal], [], lotr, [], stats, {"active": 10, "already": 6}, [], "15/10/2026")
        text = "".join(msgs)
        self.assertNotIn("−", text)
        self.assertEqual(text.count("10316 Rivendell"), 1)        # one group header per set
        self.assertIn("-22%", text)
        self.assertNotIn("-98%", text)                            # figure never gets a set discount
        self.assertIn("LotR figures</b> (1", text)
        self.assertIn("6 already reported", text)
        self.assertTrue(all(len(m) <= 4096 for m in msgs))


if __name__ == "__main__":
    unittest.main()
