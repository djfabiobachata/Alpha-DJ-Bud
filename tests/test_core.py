import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alpha_dj_bud import artists, camelot, recommender, tsaf  # noqa: E402
from alpha_dj_bud.djay_library import DjayLibrary, bpm_from_text  # noqa: E402
from alpha_dj_bud.learning import Brain  # noqa: E402
from tests import fixture  # noqa: E402


class CamelotTest(unittest.TestCase):
    def test_rules_from_brief(self):
        ok = {k for k in [f"{n}{l}" for n in range(1, 13) for l in "AB"] if camelot.relation("3A", k)}
        self.assertEqual(ok, {"3A", "3B", "2A", "4A", "9A", "9B"})

    def test_wraparound(self):
        self.assertEqual(camelot.relation("12A", "1A"), camelot.REL_UP)
        self.assertEqual(camelot.relation("1B", "12B"), camelot.REL_DOWN)
        self.assertEqual(camelot.relation("8B", "2A"), camelot.REL_TRITONE)

    def test_djay_index(self):
        self.assertEqual(camelot.from_djay_index(0), "8B")
        self.assertEqual(camelot.from_djay_index(3), "3A")
        self.assertEqual(camelot.from_djay_index(23), "1A")
        self.assertIsNone(camelot.from_djay_index(None))

    def test_parse(self):
        self.assertEqual(camelot.parse("3A - Energy 7"), "3A")
        self.assertEqual(camelot.parse("Bbm"), "3A")
        self.assertEqual(camelot.parse("A#m"), "3A")
        self.assertEqual(camelot.parse("C"), "8B")
        self.assertIsNone(camelot.parse("Energy 7"))


class ArtistTest(unittest.TestCase):
    def test_shared(self):
        a = artists.artist_set("Romeo Santos")
        self.assertTrue(artists.shares_artist(a, artists.artist_set("Romeo Santos & Drake")))
        self.assertTrue(artists.shares_artist(a, artists.artist_set("Prince Royce", "Te Robaré (feat. Romeo Santos)")))
        self.assertTrue(artists.shares_artist(artists.artist_set("Aventura"), artists.artist_set("Aventura feat. Don Omar")))
        self.assertTrue(artists.shares_artist(artists.artist_set("Willie Colón"), artists.artist_set("Willie Colon x Hector Lavoe")))
        self.assertFalse(artists.shares_artist(a, artists.artist_set("Prince Royce")))


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = fixture.build(os.path.join(self.tmp, "MediaLibrary.db"))
        self.lib = DjayLibrary(self.db)
        self.assertTrue(self.lib.refresh(force=True))

    def test_tsaf_roundtrip(self):
        obj = {"_class": "X", "name": "Ciao", "n": 5, "f": 1.5, "l": ["a", "b"], "o": {"_class": "Y", "k": "v"}}
        self.assertEqual(tsaf.decode(fixture.encode(obj)), obj)

    def test_tracks(self):
        t = self.lib.get("t01")
        self.assertEqual((t.title, t.artist, t.bpm, t.key), ("Propuesta Indecente", "Romeo Santos", 128.0, "3A"))

    def test_tree_and_folders(self):
        names = [(n["name"], n["type"], n["depth"]) for n in self.lib.tree()]
        self.assertIn(("Bachata", "folder", 0), names)
        self.assertIn(("Bachata Sensual", "playlist", 1), names)
        folder = self.lib.tracks_in("F-BACHATA")
        self.assertEqual(len(folder), 12)
        self.assertNotIn("s01", folder)

    def test_now_playing(self):
        np = self.lib.now_playing()
        self.assertEqual(np["track_id"], "t01")
        self.assertEqual(np["deck"], 1)

    def test_bpm_from_title(self):
        self.assertEqual(bpm_from_text("Azukita (Intro) 130BPM"), 130.0)
        self.assertEqual(bpm_from_text("x_major__bpm_128"), 128.0)
        self.assertIsNone(bpm_from_text("Remix 2024"))


class RecommenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib = DjayLibrary(fixture.build(os.path.join(self.tmp, "MediaLibrary.db")))
        self.lib.refresh(force=True)
        self.brain = Brain(os.path.join(self.tmp, "brain.json"))
        self.pool = self.lib.tracks_in("F-BACHATA")

    def rec(self, played=(), **opts):
        return recommender.recommend(self.lib, self.lib.get("t01"), self.pool, list(played),
                                     self.brain, "bachata", opts)

    def test_rules(self):
        out, stats = self.rec()
        ids = [x["id"] for x in out]
        self.assertEqual(set(ids), {"t03", "t04", "t05", "t06", "t07", "t12"})
        self.assertEqual(stats["artist"], 2)   # t02 and t10 (Romeo Santos)
        self.assertEqual(stats["key"], 1)      # t08
        self.assertEqual(stats["bpm"], 1)      # t09
        self.assertEqual(stats["noData"], 1)   # t11

    def test_previous_artist_also_excluded(self):
        out, _ = self.rec(played=["t03", "t01"], artistWindow=2)  # Prince Royce played before
        ids = {x["id"] for x in out}
        self.assertNotIn("t04", ids)  # Prince Royce again
        self.assertNotIn("t03", ids)  # already played

    def test_no_tritone_option(self):
        out, _ = self.rec(includeTritone=False)
        self.assertFalse({"t06", "t07"} & {x["id"] for x in out})

    def test_learning_changes_ranking(self):
        before = [x["id"] for x in self.rec(variety=0)[0]]
        cur, nxt = self.lib.get("t01"), self.lib.get("t07")
        for _ in range(30):
            self.brain.observe("bachata", cur, nxt, save=False)
        after = [x["id"] for x in self.rec(variety=0)[0]]
        self.assertGreater(before.index("t07"), 0)
        self.assertEqual(after[0], "t07")
        self.assertTrue(self.brain.score("bachata", cur, nxt, camelot.REL_TRITONE)[1])

    def test_brain_persists(self):
        self.brain.observe("zouk", self.lib.get("t01"), self.lib.get("t03"))
        again = Brain(os.path.join(self.tmp, "brain.json"))
        self.assertEqual(again.stats("zouk")["transitions"], 1)
        self.assertEqual(again.stats("bachata")["transitions"], 0)


class ServerStateTest(unittest.TestCase):
    def test_monitor_follows_djay_and_learns(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        db = fixture.build(os.path.join(tmp, "MediaLibrary.db"))
        from alpha_dj_bud.server import AppState
        st = AppState(db)
        st.action("playlist", {"id": "F-BACHATA"})
        st.poll()
        snap = st.snapshot()
        self.assertEqual(snap["current"]["id"], "t01")
        self.assertTrue(snap["suggestions"])
        time.sleep(0.01)
        fixture.add_history(db, "H3", "t04", deck=0)
        os.utime(db, None)
        st.poll()
        snap = st.snapshot()
        self.assertEqual(snap["current"]["id"], "t04")
        self.assertEqual(snap["brain"]["transitions"], 1)
        self.assertEqual(snap["brain"]["followedPct"], 100)
        # mixed night: playing a salsa track switches genre automatically
        st.action("event", {"event": "mista"})
        st.action("genre", {"genre": "bachata"})
        st.action("playlist", {"genre": "salsa", "id": "F-SALSA"})
        st.action("current", {"id": "s01"})
        self.assertEqual(st.snapshot()["genre"], "salsa")


if __name__ == "__main__":
    unittest.main()


class LanguageTest(unittest.TestCase):
    def test_language_setting_and_translations(self):
        import json
        import re
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        from alpha_dj_bud.server import AppState
        st = AppState(fixture.build(os.path.join(tmp, "MediaLibrary.db")))
        self.assertEqual(st.snapshot()["language"], "en")
        st.action("options", {"language": "es"})
        self.assertEqual(AppState(st.library.path).snapshot()["language"], "es")
        st.action("options", {"language": "xx"})  # ignored
        self.assertEqual(st.snapshot()["language"], "es")
        # every language has the same keys as English
        with open(os.path.join(os.path.dirname(__file__), "..", "alpha_dj_bud", "web", "i18n.js"), encoding="utf-8") as f:
            js = f.read()
        blocks = dict(re.findall(r"\n  (en|it|es): \{(.*?)\n  \},", js, re.S))
        keys = {k: set(re.findall(r'"([\w.]+)":', v)) for k, v in blocks.items()}
        self.assertEqual(keys["it"], keys["en"])
        self.assertEqual(keys["es"], keys["en"])

    def test_legacy_relation_labels_migrated(self):
        import json
        p = os.path.join(tempfile.mkdtemp(), "brain.json")
        with open(p, "w") as f:
            json.dump({"version": 1, "genres": {"bachata": {"relations": {"stessa key": 3, "+6": 1}}}}, f)
        b = Brain(p)
        self.assertEqual(b.g("bachata")["relations"], {"same": 3, "tritone": 1})


class VarietyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib = DjayLibrary(fixture.build(os.path.join(self.tmp, "MediaLibrary.db")))
        self.lib.refresh(force=True)
        self.brain = Brain(os.path.join(self.tmp, "brain.json"))
        self.pool = self.lib.tracks_in("F-BACHATA")
        self.cur = self.lib.get("t01")

    def order(self, set_id, variety=50):
        out, _ = recommender.recommend(self.lib, self.cur, self.pool, [], self.brain, "bachata",
                                       {"variety": variety}, set_id=set_id)
        return [x["id"] for x in out]

    def test_stable_within_a_set(self):
        self.assertEqual(self.order("friday"), self.order("friday"))

    def test_changes_between_nights(self):
        orders = {tuple(self.order("night-%d" % i)) for i in range(8)}
        self.assertGreater(len(orders), 1)

    def test_off_means_deterministic_best_match(self):
        self.assertEqual(len({tuple(self.order("night-%d" % i, variety=0)) for i in range(5)}), 1)

    def test_last_nights_follow_up_is_pushed_down(self):
        friday = self.order("friday", variety=80)
        top = friday[0]
        # on Friday you played the hit t01 and then the top suggestion
        self.brain.observe("bachata", self.cur, self.lib.get(top), shown=friday,
                           save=False, when=time.time() - 86400, set_id="friday")
        saturday = self.order("saturday", variety=80)
        self.assertGreater(saturday.index(top), 0)
        self.assertNotEqual(saturday[:3], friday[:3])


class MixedNightAndLoadTest(unittest.TestCase):
    def test_mixed_night_is_bachata_and_salsa_only(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        from alpha_dj_bud.server import AppState
        st = AppState(fixture.build(os.path.join(tmp, "MediaLibrary.db")))
        st.action("event", {"event": "zouk"})
        self.assertEqual(st.snapshot()["genre"], "zouk")
        st.action("event", {"event": "mista"})
        snap = st.snapshot()
        self.assertEqual(snap["genre"], "bachata")
        self.assertEqual(snap["mixedGenres"], ["bachata", "salsa"])

    def test_suggestions_carry_the_audio_file_for_dragging(self):
        tmp = tempfile.mkdtemp()
        audio = os.path.join(tmp, "Música ñ")  # spaces and accents in the path
        os.makedirs(audio)
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        from alpha_dj_bud.server import AppState
        st = AppState(fixture.build(os.path.join(tmp, "MediaLibrary.db"), audio_dir=audio))
        st.action("playlist", {"id": "F-BACHATA"})
        st.action("current", {"id": "t01"})
        sug = st.snapshot()["suggestions"]
        self.assertTrue(sug and all(s["hasFile"] for s in sug))
        from urllib.parse import unquote
        path = unquote(sug[0]["fileUrl"][len("file://"):])
        self.assertTrue(os.path.isfile(path), path)
        self.assertEqual(st.track_file(sug[0]["id"]), path)
        self.assertIsNone(st.track_file("t11"))
        # no native window here: drag reports an error instead of crashing
        self.assertFalse(st.native_drag(sug[0]["id"])["ok"])
        self.assertEqual(st.native_drag("t11")["code"], "noFile")
