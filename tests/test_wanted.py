"""Wanted list. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import daily_deals as dd  # noqa: E402
import wanted as wl  # noqa: E402

CAT = dd.load_catalogue(os.path.join(ROOT, "sets.csv"))
# A frozen copy: the live wanted.json changes whenever /want or /unwant is sent to the bot,
# and the tests must not depend on what is being watched today.
WANTED = wl.load(os.path.join(os.path.dirname(__file__), "fixtures", "wanted.json"))


def it(i, title, price=100, cond="Muy bueno"):
    return {"id": i, "title": title, "price": price, "url": f"https://www.vinted.es/items/{i}-x", "condition": cond}


class TestMatch(unittest.TestCase):
    def test_fixture_list(self):
        self.assertEqual({w["number"] for w in WANTED},
                         {"21367", "71837", "71860", "10365", "75397", "72032", "75453"})

    def test_live_list_is_valid(self):
        live = wl.load(os.path.join(ROOT, "wanted.json"))
        for w in live:
            self.assertRegex(w["number"], r"^\d{4,6}$")
            self.assertTrue(w["name"])
        self.assertEqual(len(live), len({w["number"] for w in live}))

    def test_number_and_keyword(self):
        self.assertEqual(wl.match("Lego 10365 barco Jack Sparrow nuevo", WANTED)["number"], "10365")
        self.assertEqual(wl.match("LEGO 75397-1 Jabba", WANTED)["number"], "75397")
        self.assertEqual(wl.match("Lego Tintin cohete", WANTED)["number"], "21367")
        self.assertIsNone(wl.match("Tintin comic El loto azul", WANTED))   # keyword needs 'lego'
        self.assertIsNone(wl.match("Lego 103650 random", WANTED))
        self.assertIsNone(wl.match("Lego 75192 Falcon", WANTED))

    def test_evaluate_filters(self):
        hits, excl = dd.evaluate_wanted([
            it(1, "Lego 10365 Jack Sparrow precintado", 280, "Nuevo con etiquetas"),
            it(2, "compatible 10365 barco pirata", 60),
            it(3, "Minifigura Jack Sparrow del set 10365", 15),
            it(4, "Kit luces LED para Lego 10365", 30),
            it(5, "Lego 75192 Falcon", 300),
        ], WANTED)
        self.assertEqual([h["id"] for h in hits], [1])
        self.assertAlmostEqual(hits[0]["discount"], 1 - 280 / 349.99)
        self.assertEqual(excl, Counter({"keywords": 1, "figure": 1, "accessory": 1}))

    def test_real_false_positives_20_10(self):
        """Titles from the 20/10/2026 dry run that are not the set."""
        bad = ["Support mural pour LEGO Pirates des Caraïbes Black Pearl 10365",
               "Lego 10365 Captain Jack Sparrow's Pirate Ship pirati caraibi solo istruzioni",
               "Notice SEUL lego idea Moon Rocket set 21367",
               "Lego 21367 - personnages Tintin - lot complet",
               "Cadre LEGO Tintin fusée 50x70 – On a marché sur la lune",
               "Lepin Ninjago city workshop 71837",
               "Lego Star Wars 75397 figura de la princesa Leia esclava nueva",
               "LEGO 72032 Super Mario - Standard Kart (Caixa vazia)"]
        hits, _ = dd.evaluate_wanted([it(i, t, 75) for i, t in enumerate(bad)], WANTED)
        self.assertEqual([h["title"] for h in hits], [])
        good = ["Lego Cohete Lunar Tintín 21367",
                "LEGO Star Wars 75397 – Jabba’s Sail Barge – 3942 pieces", "Lego Mario Toad 72032",
                "Lego le seigneur des anneaux 10316 fondcombe avec 15 figurines neuf"]
        hits, _ = dd.evaluate_wanted([it(i, t, 150) for i, t in enumerate(good)], WANTED)
        self.assertEqual(len(hits), 3)  # 10316 is not on the wanted list

    def test_without_figures_dropped(self):
        titles = ["Lego 21367 La fusée de Tintin sans personnnages", "Lego 75397 sin minifiguras",
                  "LEGO 10365 without minifigures", "Lego 75453 senza minifigure"]
        hits, excl = dd.evaluate_wanted([it(i, t, 150) for i, t in enumerate(titles)], WANTED)
        self.assertEqual((hits, excl["no figures"]), ([], 4))

    def test_queries(self):
        qs = wl.search_queries(WANTED)
        self.assertIn("lego 10365", qs)
        self.assertIn("lego tintin", qs)
        self.assertEqual(len(qs), len(set(qs)))


class TestCommands(unittest.TestCase):
    def test_add_from_catalogue_and_remove(self):
        e, msg = wl.apply_command([], "/want 75192", CAT)
        self.assertEqual(e[0]["number"], "75192")
        self.assertTrue(e[0]["rrp"])
        self.assertTrue(msg.startswith("Added"))
        e, msg = wl.apply_command(e, "/want 75192 650,50 Halcón Milenario", CAT)
        self.assertEqual((e[0]["rrp"], e[0]["name"], len(e)), (650.5, "Halcón Milenario", 1))
        e, msg = wl.apply_command(e, "/unwant 75192", CAT)
        self.assertEqual(e, [])
        _, msg = wl.apply_command(e, "/unwant 75192", CAT)
        self.assertIn("not in the wanted list", msg)

    def test_unknown_set_and_bad_input(self):
        e, _ = wl.apply_command([], "/want@LegoBot 99999 25 Mystery", {})
        self.assertEqual(e[0], {"number": "99999", "name": "Mystery", "year": None, "rrp": 25.0})
        e2, msg = wl.apply_command(e, "/want abc", {})
        self.assertEqual(e2, e)
        self.assertIn("not a set number", msg)
        self.assertEqual(wl.apply_command(e, "hello", {}), (e, None))
        self.assertIn("99999 Mystery", wl.apply_command(e, "/wanted", {})[1])

    def test_fetch_commands_filters_chat(self):
        class R:
            status_code = 200
            def json(self):
                return {"result": [
                    {"update_id": 10, "message": {"chat": {"id": 1}, "text": "/want 10365"}},
                    {"update_id": 11, "message": {"chat": {"id": 2}, "text": "/want 75192"}},
                ]}
        texts, nxt = wl.fetch_commands("t", "1", 5, lambda *a, **k: R())
        self.assertEqual((texts, nxt), (["/want 10365"], 12))


class TestMessage(unittest.TestCase):
    def test_block_and_footer(self):
        hits, excl = dd.evaluate_wanted([it(1, "Lego 72032 kart estandar", 12, "Nuevo sin etiquetas")], WANTED)
        stats = {"scanned": 0, "excluded": Counter(), "matched": 0, "unidentified": 0}
        info = {"watched": 7, "excluded": excl, "replies": "Added 75192 Millennium Falcon (849.99€)"}
        text = "".join(dd.build_messages([], [], [], [], stats, {"active": 0, "already": 0}, [], "20/10/2026",
                                         hits, info))
        self.assertIn("🎯 1 wanted", text)
        self.assertIn("Wanted list</b>", text)
        self.assertIn("72032 Mario Kart: Kart estándar", text)
        self.assertIn("-40%", text)
        self.assertIn("Wanted: 7 sets watched · 1 new", text)
        self.assertIn("Added 75192", text)

    def test_no_wanted_block_when_empty(self):
        stats = {"scanned": 0, "excluded": Counter(), "matched": 0, "unidentified": 0}
        text = "".join(dd.build_messages([], [], [], [], stats, {"active": 0, "already": 0}, [], "20/10/2026"))
        self.assertNotIn("Wanted", text)


if __name__ == "__main__":
    unittest.main()
