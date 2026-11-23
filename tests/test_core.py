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
        np = self.lib.history()[-1]
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


class UpdaterTest(unittest.TestCase):
    def _zip(self, version="9.9.9", broken=False):
        import io
        import zipfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for folder in ("alpha_dj_bud", "assets"):
                for dp, _, files in os.walk(os.path.join(root, folder)):
                    if "__pycache__" in dp:
                        continue
                    for fn in files:
                        full = os.path.join(dp, fn)
                        arc = "repo-abc123/" + os.path.relpath(full, root)
                        data = open(full, "rb").read()
                        if arc.endswith("alpha_dj_bud/__init__.py"):
                            data = ('__version__ = "%s"\n' % version).encode()
                        if broken and arc.endswith("alpha_dj_bud/server.py"):
                            data = b"this is not python ("
                        z.writestr(arc, data)
            z.writestr("repo-abc123/requirements.txt", "")
        return buf.getvalue()

    def _home(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "app", "alpha_dj_bud"))
        with open(os.path.join(home, "app", "alpha_dj_bud", "__init__.py"), "w") as f:
            f.write('__version__ = "1.0.0"\n')
        with open(os.path.join(home, "app", "requirements.txt"), "w") as f:
            f.write("")
        return home

    def test_version_compare(self):
        from alpha_dj_bud import updater
        self.assertTrue(updater.is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("v1.4.0", "1.4.0"))
        self.assertFalse(updater.is_newer("1.3.1", "1.4.0"))

    def test_install_swaps_code_and_keeps_backup(self):
        from alpha_dj_bud import updater
        home = self._home()
        v = updater.install(home, info={"available": True}, zip_bytes=self._zip("9.9.9"))
        self.assertEqual(v, "9.9.9")
        with open(os.path.join(home, "app", "alpha_dj_bud", "__init__.py")) as f:
            self.assertIn("9.9.9", f.read())
        with open(os.path.join(home, "app.old", "alpha_dj_bud", "__init__.py")) as f:
            self.assertIn("1.0.0", f.read())
        self.assertTrue(os.path.isfile(os.path.join(home, "app", "assets", "AppIcon.icns")))

    def test_broken_update_keeps_current_version(self):
        from alpha_dj_bud import updater
        home = self._home()
        with self.assertRaises(updater.UpdateError) as cm:
            updater.install(home, info={"available": True}, zip_bytes=self._zip(broken=True))
        self.assertEqual(cm.exception.code, "verify")
        with open(os.path.join(home, "app", "alpha_dj_bud", "__init__.py")) as f:
            self.assertIn("1.0.0", f.read())

    def test_zip_with_escaping_paths_is_refused(self):
        import io
        import zipfile
        from alpha_dj_bud import updater
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.py", "x")
        with self.assertRaises(updater.UpdateError) as cm:
            updater.install(self._home(), info={"available": True}, zip_bytes=buf.getvalue())
        self.assertEqual(cm.exception.code, "badZip")

    def test_not_installed_app_refuses_network_update(self):
        from alpha_dj_bud import updater
        with self.assertRaises(updater.UpdateError) as cm:
            updater.install(tempfile.mkdtemp())
        self.assertEqual(cm.exception.code, "notInstalled")


class NowPlayingFileTest(unittest.TestCase):
    def _write(self, db, title, artist, length="03:20"):
        p = os.path.join(os.path.dirname(db), "NowPlaying.txt")
        with open(p, "w") as f:
            f.write("Title: %s\nArtist: %s\nAlbum: X\nTime: %s\n" % (title, artist, length))
        t = time.time() + 1
        os.utime(p, (t, t))

    def test_now_playing_file_drives_current_and_ignores_history(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        db = fixture.build(os.path.join(tmp, "MediaLibrary.db"))
        from alpha_dj_bud.server import AppState
        st = AppState(db)
        st.action("playlist", {"id": "F-BACHATA"})
        self._write(db, "Darte un Beso", "Prince Royce")
        st.poll()
        self.assertEqual(st.snapshot()["current"]["id"], "t03")
        self.assertTrue(st.snapshot()["nowPlayingFile"])
        # a pre-listen lands in djay history: must NOT change the playing track
        fixture.add_history(db, "H9", "t05", deck=0)
        os.utime(db, None)
        st.poll()
        self.assertEqual(st.snapshot()["current"]["id"], "t03")
        # djay moves on air to the next track
        self._write(db, "Obsesión", "Aventura")
        st.poll()
        snap = st.snapshot()
        self.assertEqual(snap["current"]["id"], "t05")
        self.assertEqual(snap["brain"]["transitions"], 1)

    def test_unknown_track_is_reported(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        db = fixture.build(os.path.join(tmp, "MediaLibrary.db"))
        from alpha_dj_bud.server import AppState
        st = AppState(db)
        self._write(db, "Not In Library", "Nobody")
        st.poll()
        self.assertEqual(st.snapshot()["nowPlayingUnmatched"]["title"], "Not In Library")


class NativeDragLogicTest(unittest.TestCase):
    def test_row_lookup_and_method_cycling(self):
        from alpha_dj_bud import native_drag as nd
        home = tempfile.mkdtemp()
        nd.configure(home, lambda tid: "/x/%s.mp3" % tid)
        nd.set_rows([{"id": "a", "x": 10, "y": 100, "w": 300, "h": 40},
                     {"id": "b", "x": 10, "y": 144, "w": 300, "h": 40}])
        self.assertEqual(nd.row_at_point(50, 120), "a")
        self.assertEqual(nd.row_at_point(50, 150), "b")
        self.assertIsNone(nd.row_at_point(50, 300))
        # djay rejects the first method -> next drag uses the next one
        nd._state["method"] = "url"
        nd._last["method"] = "url"
        nd._ended(0)
        self.assertEqual(nd._state["method"], "files")
        nd._last["method"] = "files"
        nd._ended(1)  # accepted: remembered
        self.assertEqual(nd._state["method"], "files")
        nd._state["method"] = "url"
        nd.configure(home, None)  # reload from disk
        self.assertEqual(nd._state["method"], "files")


class AppleMusicMergeTest(unittest.TestCase):
    def test_music_playlists_tracks_keys_and_files(self):
        from alpha_dj_bud.music_library import key_bpm_from_text
        self.assertEqual(key_bpm_from_text("12A - 126 - 01 Es Evidente.m4a"), ("12A", 126.0))
        self.assertEqual(key_bpm_from_text("12A - Energy 6"), ("12A", None))
        tmp = tempfile.mkdtemp()
        lib = DjayLibrary(fixture.build(os.path.join(tmp, "MediaLibrary.db")))
        lib.refresh(force=True)
        f = os.path.join(tmp, "12A - 126 - 01 Es Evidente.m4a")
        open(f, "wb").close()
        data = {
            "tracks": {
                111: {"pid": 111, "title": "Propuesta Indecente", "artist": "Romeo Santos", "bpm": None,
                      "comments": "", "duration": 200.0, "genre": "", "path": os.path.join(tmp, "prop.mp3")},
                222: {"pid": 222, "title": "Es Evidente", "artist": "Akai Rojas", "bpm": None,
                      "comments": "12A - Energy 6", "duration": 249.0, "genre": "Bachata", "path": f},
            },
            "playlists": [
                {"pid": 9, "parent": None, "name": "DJ", "folder": True, "items": []},
                {"pid": 10, "parent": 9, "name": "BCHTA", "folder": False, "items": [111, 222]},
            ],
        }
        lib.set_apple_music(data)
        ids = lib.tracks_in("am:pl:10")
        self.assertEqual(ids[0], "t01")                  # matched to djay's own track (key/BPM from djay)
        new = lib.get(ids[1])
        self.assertEqual((new.title, new.key, new.bpm), ("Es Evidente", "12A", 126.0))
        self.assertEqual(lib.file_path(ids[1]), f)       # draggable file
        tree = lib.tree()
        names = [(n["name"], n["depth"], n["group"]) for n in tree]
        self.assertEqual(names[0], ("djay", 0, "app"))            # all djay tracks first
        self.assertIn(("Musica", 0, "music"), names)               # whole Music library
        self.assertIn(("BCHTA", 1, "music"), names)
        self.assertEqual(set(lib.tracks_in("am:all")), set(ids))
        self.assertIn("t01", lib.tracks_in("djay:all"))
        self.assertNotIn(ids[1], lib.tracks_in("djay:all"))
        self.assertEqual(lib.tracks_in("am:root"), ids)  # folder includes sub-playlists
        # NowPlaying from the Music source is found too
        self.assertEqual(lib.match_now_playing({"title": "Es Evidente", "artist": "Akai Rojas"}), ids[1])
        # survives a djay database reload
        lib.refresh(force=True)
        self.assertEqual(lib.tracks_in("am:pl:10"), ids)


class V19Test(unittest.TestCase):
    def _state(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        from alpha_dj_bud.server import AppState
        return AppState(fixture.build(os.path.join(tmp, "MediaLibrary.db"))), tmp

    def test_tolerance_per_genre(self):
        lib = DjayLibrary(fixture.build(os.path.join(tempfile.mkdtemp(), "MediaLibrary.db")))
        lib.refresh(force=True)
        pool = lib.tracks_in("F-BACHATA")
        rec = lambda g: {x["id"] for x in recommender.recommend(lib, lib.get("t01"), pool, [], None, g, {"variety": 0})[0]}
        self.assertNotIn("t09", rec("bachata"))   # +12 BPM
        self.assertNotIn("t09", rec("zouk"))       # zouk ±10: +12 still out
        self.assertIn("t12", rec("salsa"))         # +4 within salsa ±6
        custom = {x["id"] for x in recommender.recommend(lib, lib.get("t01"), pool, [], None, "zouk",
                  {"variety": 0, "bpmToleranceByGenre": {"zouk": 12}})[0]}
        self.assertIn("t09", custom)

    def test_up_and_down_picks_are_tagged_and_on_top(self):
        lib = DjayLibrary(fixture.build(os.path.join(tempfile.mkdtemp(), "MediaLibrary.db")))
        lib.refresh(force=True)
        out, _ = recommender.recommend(lib, lib.get("t01"), lib.tracks_in("F-BACHATA"), [], None,
                                       "bachata", {"variety": 0})
        plain, _ = recommender.recommend(lib, lib.get("t01"), lib.tracks_in("F-BACHATA"), [], None,
                                         "bachata", {"variety": 0, "limit": 50})
        self.assertEqual([x["id"] for x in out[:3]], [x["id"] for x in plain[:3]])  # 3 best untouched
        self.assertFalse(any(x.get("bpmTag") for x in out[:3]))
        for x in out:
            if x.get("bpmTag"):
                self.assertIn(x, out[3:5])                     # only at positions 4-5
                self.assertGreaterEqual(abs(x["bpmDelta"]), 4)  # at least 4 BPM
        # the picks ignore the genre tolerance: 4..10 BPM, closest to 4 first
        from alpha_dj_bud.djay_library import Track
        for tid, bpm, key in (("x5", 133.0, "3A"), ("x7", 135.0, "3A"), ("x11", 139.5, "3A"),
                              ("d6", 122.0, "4A"), ("d9", 119.0, "4A")):
            lib.tracks[tid] = Track(tid, "Demo " + tid, "Artist " + tid, bpm, key, 200.0)
        pool = lib.tracks_in("F-BACHATA") + ["x5", "x7", "x11", "d6", "d9"]
        out3, _ = recommender.recommend(lib, lib.get("t01"), pool, [], None, "bachata", {"variety": 0})
        tags = {x.get("bpmTag"): x for x in out3 if x.get("bpmTag")}
        self.assertEqual(tags["up"]["id"], "x5")      # +5 (bachata ±4 doesn't matter), not +7
        self.assertEqual(tags["down"]["id"], "d6")    # -6, the closest available going down
        self.assertEqual(out3[3]["bpmTag"], "up")
        self.assertEqual(out3[4]["bpmTag"], "down")
        self.assertNotIn("x11", [x["id"] for x in out3])   # +11.5: beyond 10
        self.assertNotIn("x7", [x["id"] for x in out3])    # outside tolerance and not the pick

    def test_genre_buttons_switch_the_night(self):
        st, _ = self._state()
        st.action("event", {"event": "bachata"})
        st.action("genre", {"genre": "zouk"})
        self.assertEqual((st.settings["event"], st.settings["genre"]), ("zouk", "zouk"))
        st.action("genre", {"genre": "salsa"})
        self.assertEqual(st.settings["event"], "salsa")
        st.action("genre", {"genre": "bachata"})
        self.assertEqual(st.settings["event"], "mista")   # bachata + salsa = mixed night

    def test_window_frames_kept_on_screen(self):
        st, _ = self._state()
        screens = [{"x": 0, "y": 0, "w": 1440, "h": 900}]
        self.assertEqual(st.window_frame("mini", screens), {"x": None, "y": None, "w": 300, "h": 480})
        st.settings["windowFrames"] = {"normal": {"x": 900, "y": 300, "w": 1080, "h": 760},
                                       "mini": {"x": 5000, "y": 10, "w": 260, "h": 300}}
        f = st.window_frame("normal", screens)
        self.assertEqual((f["x"] + f["w"] <= 1440, f["y"] + f["h"] <= 900), (True, True))
        self.assertIsNone(st.window_frame("mini", screens)["x"])  # off-screen: re-placed
        self.assertEqual(st.window_frame("mini", screens)["w"], 260)  # but keeps its size

    def test_folders_source(self):
        from alpha_dj_bud.local_files import read_tags
        st, tmp = self._state()
        music = os.path.join(tmp, "Música DJ")
        os.makedirs(os.path.join(music, "Bachata 2026"))
        for name in ("12A - 126 - Akai Rojas - Es Evidente.mp3", "Romeo Santos - Propuesta Indecente.mp3"):
            open(os.path.join(music, "Bachata 2026", name), "wb").close()
        open(os.path.join(music, "notes.txt"), "w").close()
        m = read_tags(os.path.join(music, "Bachata 2026", "12A - 126 - Akai Rojas - Es Evidente.mp3"))
        self.assertEqual((m["key"], m["bpm"], m["artist"], m["title"]), ("12A", 126.0, "Akai Rojas", "Es Evidente"))
        self.assertFalse(st.action("folders", {"add": os.path.join(tmp, "nope")})["ok"])
        st.action("folders", {"add": music})
        st.scan_folders()
        tree = [n for n in st.library.tree() if n["group"] == "files"]
        self.assertEqual([(n["name"], n["depth"]) for n in tree], [("Música DJ", 0), ("Bachata 2026", 1)])
        ids = st.library.tracks_in(tree[0]["id"])
        self.assertEqual(len(ids), 2)
        self.assertIn("t01", ids)                          # matched to djay's own track
        new = st.library.get([i for i in ids if i != "t01"][0])
        self.assertEqual((new.key, new.bpm), ("12A", 126.0))
        self.assertTrue(st.library.file_path(new.id).endswith("Es Evidente.mp3"))
        st.library.refresh(force=True)                     # survives djay reloads
        self.assertEqual(len(st.library.tracks_in(tree[0]["id"])), 2)
        st.action("folders", {"remove": music})
        self.assertFalse([n for n in st.library.tree() if n["group"] == "files"])


class MusicAppFallbackTest(unittest.TestCase):
    def test_music_app_reply_is_parsed(self):
        import json
        import subprocess
        from unittest import mock
        from alpha_dj_bud import music_library as ml
        reply = {"tracks": [["D11A7E8C3F2B0001", "Es Evidente", "Akai Rojas", 126, "12A - Energy 6", 249.0,
                             "Bachata", "/Users/x/Music/Es Evidente.m4a"],
                            ["D11A7E8C3F2B0002", "Podcast-ish", "", 0, "", 10.0, "", None]],
                 "playlists": [["00000000000000AA", None, "DJ", "folder", []],
                               ["00000000000000AB", "00000000000000AA", "BCHTA", "none",
                                ["D11A7E8C3F2B0001", "D11A7E8C3F2B0002"]],
                               ["00000000000000AC", None, "Podcasts", "Podcasts", []]]}
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps(reply), stderr="")
        with mock.patch("subprocess.run", return_value=done):
            data = ml._load_via_music_app()
        pid = int("D11A7E8C3F2B0001", 16)
        self.assertEqual(data["tracks"][pid]["path"], "/Users/x/Music/Es Evidente.m4a")
        names = {p["name"]: p for p in data["playlists"]}
        self.assertTrue(names["DJ"]["folder"])
        self.assertEqual(names["BCHTA"]["parent"], int("AA", 16))
        self.assertNotIn("Podcasts", names)          # special list with no songs
        self.assertEqual(len(names["BCHTA"]["items"]), 2)


class LiveBpmTest(unittest.TestCase):
    def test_bpm_found_next_to_the_title_in_any_layout(self):
        from alpha_dj_bud.deck_reader import pick_bpm, bpm_values
        it = lambda text, x, y, w=120, h=20: {"text": text, "frame": (x, y, w, h)}
        # layout A (this Mac): title on top, BPM button in the mixer below
        a = [it("Crazy", 97, 226, 500), it("DJ Nico & Mayinbito", 97, 245, 400), it("126.0", 610, 240, 60),
             it("124.5", 88, 328, 74), it("0.0 %", 88, 348, 74), it("-03:24", 611, 226),
             it("Es Evidente", 900, 226, 400), it("128.0", 1380, 240, 60)]
        self.assertEqual(pick_bpm(a, "Crazy", 126.0)[0], 126.0)       # the closest one
        self.assertEqual(pick_bpm(a, "Es Evidente", 126.0)[0], 128.0)
        # layout B (laptop): decks stacked, BPM in a text with the artist, title shortened
        b = [it("Amantes - Remix Versi…", 40, 600), it("EKA · 120.3 BPM", 40, 622),
             it("16", 300, 610), it("Otra Canción", 40, 700), it("118.0", 300, 720)]
        self.assertEqual(pick_bpm(b, "Amantes - Remix Version Extended", 118.0)[0], 120.3)
        # no title on screen / implausible values
        self.assertEqual(pick_bpm(b, "Missing", 118.0)[2], "title not found")
        c = [it("Amantes", 0, 0), it("12.5", 10, 0), it("240.0", 900, 900)]
        self.assertEqual(pick_bpm(c, "Amantes", 118.0)[2], "title found, no BPM near it")
        self.assertEqual(bpm_values("126.0 BPM"), [(126.0, True)])
        self.assertEqual(bpm_values("126"), [(126.0, False)])
        self.assertEqual(bpm_values("0.0 %"), [])

    def test_suggestions_follow_the_tempo_set_in_djay(self):
        tmp = tempfile.mkdtemp()
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        from alpha_dj_bud.server import AppState
        st = AppState(fixture.build(os.path.join(tmp, "MediaLibrary.db")))
        st.action("playlist", {"id": "F-BACHATA"})
        st.action("current", {"id": "t01"})            # analysed at 128
        before = {x["id"]: x["bpmDelta"] for x in st.snapshot()["suggestions"]}
        st.live = {"bpm": 131.0, "deck": 0, "track": "t01"}   # DJ pushed the tempo to 131
        snap = st.snapshot()
        self.assertEqual((snap["current"]["bpm"], snap["current"]["bpmAnalyzed"]), (131.0, 128.0))
        self.assertTrue(snap["current"]["bpmLive"])
        after = {x["id"]: x["bpmDelta"] for x in snap["suggestions"]}
        self.assertEqual(after["t12"], 1.0)              # 132 vs 131 (was +4 vs 128)
        self.assertNotEqual(before.get("t05"), after.get("t05"))
        st.action("options", {"liveBpm": False})        # option off: back to analysed BPM
        self.assertEqual(st.snapshot()["current"]["bpm"], 128.0)
