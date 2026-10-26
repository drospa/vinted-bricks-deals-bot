"""Lego Ideas experiment: every identified Ideas listing is kept, no discount filter.
Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import daily_deals as dd  # noqa: E402

CAT = dd.load_catalogue(os.path.join(ROOT, "sets.csv"))


def item(i, title, price, cond="Muy bueno"):
    return {"id": i, "title": title, "price": price, "url": f"https://www.vinted.es/items/{i}-x", "condition": cond}


class TestIdeas(unittest.TestCase):
    def test_no_discount_filter(self):
        ideas = []
        items = [item(1, "Lego Ideas 21318 Tree House", 240),        # ~4% off: would fail the 40% filter
                 item(2, "Lego 21318 casa del arbol", 300),          # above RRP: still listed
                 item(3, "Lego 40912 Sea Serpent", 15),              # GWP, no RRP
                 item(4, "Lego City 60337 tren", 50)]                # not Ideas: unaffected
        deals, susp, lotr, sw, stats = dd.evaluate(items, CAT, ideas=ideas)
        self.assertEqual(sorted(d["id"] for d in ideas), [1, 2, 3])
        self.assertNotIn(1, [d["id"] for d in deals + susp])
        self.assertIsNone(next(d for d in ideas if d["id"] == 3)["discount"])
        self.assertEqual(stats["matched"] + stats["unidentified"] + sum(stats["excluded"].values()), 4)

    def test_disabled_by_default(self):
        deals, susp, *_ = dd.evaluate([item(1, "Lego Ideas 21318 Tree House", 100)], CAT)
        self.assertEqual([d["id"] for d in deals + susp], [1])   # 60% off: normal deals path

    def test_quality_exclusions_still_apply(self):
        ideas = []
        dd.evaluate([item(1, "kit luces LED para Lego 21318", 20)], CAT, ideas=ideas)
        self.assertEqual(ideas, [])

    def test_message_block(self):
        ideas = []
        dd.evaluate([item(1, "Lego 21318 Tree House", 240), item(2, "Lego 21318", 200)], CAT, ideas=ideas)
        stats = {"scanned": 2, "excluded": Counter(), "matched": 2, "unidentified": 0}
        text = "".join(dd.build_messages([], [], [], [], stats, {"active": 0, "already": 0}, [], "26/10/2026",
                                         ideas=ideas))
        self.assertIn("💡 2 Ideas", text)
        self.assertIn("Lego Ideas</b> (experiment", text)
        self.assertEqual(text.count("21318 Tree House"), 1)


if __name__ == "__main__":
    unittest.main()
