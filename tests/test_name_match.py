"""Name matching against the real catalogue. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from legobot import catalogue, filters  # noqa: E402
from legobot.name_match import NameIndex, load_aliases  # noqa: E402

CAT = catalogue.load_catalogue(os.path.join(ROOT, "sets.csv"))
IDX = NameIndex(CAT, load_aliases(os.path.join(ROOT, "aliases.json")))


class TestNameMatch(unittest.TestCase):
    def test_matches(self):
        for title, num in [("smeagol et deagol lego seigneur des anneaux neuf", "40761"),
                           ("lego la comarca nuevo", "10354"), ("game boy lego", "72046"),
                           ("lego seigneur des anneaux le conseil d'elrond", "79006"),
                           ("Lego Barad-dûr", "10333")]:
            self.assertEqual(IDX.match(title), num, title)

    def test_rejects_ambiguous_or_generic(self):
        for title in ["lego millennium falcon", "lego police station city", "lego boat", "lego elrond",
                      "lego star wars x-wing", "lord of the rings lego", "lego technic"]:
            self.assertIsNone(IDX.match(title), title)

    def test_negated_figure_is_not_a_figure(self):
        item = {"id": 1, "title": "lego icons lotr casque de sauron neuf sans figurine", "price": 50.0,
                "url": "u", "condition": "Muy bueno"}
        lotr = filters.evaluate([item], CAT)[2]
        self.assertEqual((lotr[0]["set_no"], lotr[0]["figure"], lotr[0]["by_name"]), ("11373", False, True))


if __name__ == "__main__":
    unittest.main()
