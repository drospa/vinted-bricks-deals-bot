"""P1 data-quality rules, with real titles from the 15/10/2026 digest. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import daily_deals as dd  # noqa: E402

CAT = dd.load_catalogue(os.path.join(ROOT, "sets.csv"))


def run(title, price, cond="Muy bueno"):
    item = {"id": 1, "title": title, "price": price, "url": "u", "condition": cond}
    deals, susp, lotr, sw, stats = dd.evaluate([item], CAT)
    return deals + susp, lotr, sw, stats


class TestExclusions(unittest.TestCase):
    def assertExcluded(self, title, price, reason):
        *_, stats = run(title, price)
        self.assertEqual(stats["excluded"][reason], 1, title)

    def test_accessories(self):
        for t in ["kit de iluminacion led yeabricks rivendell 10316", "LED lighting kit for Lego 10316",
                  "tower of orthanc barad dur 10333 alternative build", "Vitrina para Lego 75192",
                  "Kit luces LED para Lego Minas Tirith 11377", "Briksmax light kit 10354"]:
            self.assertExcluded(t, 15, "accessory")

    def test_incomplete(self):
        for t in ["lego star wars 75242 75235 incompleet", "lego 75102 mancano pezzi",
                  "lego city 60220 faltan piezas", "lego 75102 missing pieces", "lego 75102 onvolledig"]:
            self.assertExcluded(t, 20, "incomplete")

    def test_negated_incomplete_is_kept(self):
        for t in ["lego 75102 no faltan piezas", "lego 75102 completo no le falta ninguna pieza",
                  "lego 75102 no missing pieces"]:
            *_, stats = run(t, 30)
            self.assertEqual(sum(stats["excluded"].values()), 0, t)


class TestFigures(unittest.TestCase):
    def test_complete_set_with_figure_word_is_a_set(self):
        _, lotr, _, _ = run("lego icons elmo sauron lord of the rings minifigure set 11373 completo", 60)
        self.assertFalse(lotr[0]["figure"])
        _, lotr, _, _ = run("lego lord of the rings 40893 grond completo minifigures raro gwp mordor", 100)
        self.assertFalse(lotr[0]["figure"])

    def test_real_figures_stay_figures(self):
        for t, p in [("lego minifig 10316 rivendell lord of the rings", 190),
                     ("lego 10354 minifigura senor de los anillos", 15),
                     ("lego 10354 minifigura completa senor de los anillos", 15)]:  # complete figure, cheap
            _, lotr, _, _ = run(t, p)
            self.assertTrue(lotr[0]["figure"], t)

    def test_with_minifigures_city_set_not_excluded(self):
        deals, *_ , stats = run("lego city 60220 completo con minifiguras", 10)
        self.assertEqual(sum(stats["excluded"].values()), 0)
        self.assertEqual(stats["matched"], 1)


if __name__ == "__main__":
    unittest.main()
