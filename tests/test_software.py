"""Alpha DJ Bud with VirtualDJ, Serato, Traktor and rekordbox libraries."""
import json
import os
import socket
import tempfile
import time
import unittest

from tests import fixture, fixture_others as fx
from alpha_dj_bud import software
from alpha_dj_bud.library_base import file_id

TITLES = [s[1] for s in fx.SONGS]


def names(lib):
    return [(n["name"], n["depth"], n["type"]) for n in lib.tree() if n["group"] == "app"]


class ReaderChecks:
    """Common checks: every reader gives the same tracks and playlists."""

    def check_library(self, lib, paths, all_name):
        self.assertIsNone(lib.error)
        self.assertEqual(sorted(t.title for t in lib.tracks.values()), sorted(TITLES))
        t = lib.get(file_id(paths[0]))
        self.assertEqual((t.title, t.artist, t.key), ("Propuesta Indecente", "Romeo Santos", "3A"))
        self.assertAlmostEqual(t.bpm, 128.0, places=1)
        self.assertEqual(lib.file_path(t.id), paths[0])
        self.assertEqual(lib.get(file_id(paths[4])).key, "8A")
        tree = names(lib)
        self.assertEqual(tree[0][0], all_name)
        self.assertIn(("Bachata", 0, "folder"), tree)
        self.assertIn(("Sensual", 1, "playlist"), tree)
        self.assertIn(("Salsa", 0, "playlist"), tree)
        sensual = next(n["id"] for n in lib.tree() if n["name"] == "Sensual")
        self.assertEqual(lib.tracks_in(sensual), [file_id(p) for p in paths[:4]])
        bachata = next(n["id"] for n in lib.tree() if n["name"] == "Bachata")
        self.assertEqual(len(lib.tracks_in(bachata)), 4)   # the folder includes its playlists


class VirtualDJTest(unittest.TestCase, ReaderChecks):
    def test_library_history_and_now_playing(self):
        tmp = tempfile.mkdtemp()
        home, paths = fx.virtualdj(tmp)
        self.assertEqual(software.find("virtualdj", home), home)
        lib = software.open_library("virtualdj", home)
        lib.refresh(force=True)
        self.check_library(lib, paths, "virtualdj")
        mtime, info = lib.read_now_playing()
        self.assertEqual(lib.match_now_playing(info), file_id(paths[3]))
        h = lib.history()
        self.assertEqual([x["track_id"] for x in h], [file_id(paths[2]), file_id(paths[3])])
        self.assertEqual(lib.history_sessions()[0]["tracks"], [file_id(paths[2]), file_id(paths[3])])


class SeratoTest(unittest.TestCase, ReaderChecks):
    def test_library_crates_and_sessions(self):
        tmp = tempfile.mkdtemp()
        home, paths = fx.serato(tmp)
        lib = software.open_library("serato", software.find("serato", home))
        lib.refresh(force=True)
        self.check_library(lib, paths, "serato")
        _m, info = lib.read_now_playing()
        self.assertEqual(lib.match_now_playing(info), file_id(paths[3]))
        self.assertEqual(info["deck"], 1)       # deck 2 in Serato = index 1
        self.assertEqual(len(lib.history_sessions()[0]["tracks"]), 2)


class TraktorTest(unittest.TestCase, ReaderChecks):
    def test_collection_and_playlists(self):
        tmp = tempfile.mkdtemp()
        coll, paths = fx.traktor(tmp)
        self.assertEqual(software.find("traktor", os.path.dirname(coll)), coll)
        lib = software.open_library("traktor", coll, broadcast_port=0)
        lib.refresh(force=True)
        self.check_library(lib, paths, "traktor")
        self.assertNotIn("_LOOPS", [n[0] for n in names(lib)])
        self.assertEqual(lib.read_now_playing(), (None, None))
        lib.close()

    def test_broadcast_gives_the_track_on_air(self):
        tmp = tempfile.mkdtemp()
        coll, paths = fx.traktor(tmp)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        lib = software.open_library("traktor", coll, broadcast_port=port)
        lib.refresh(force=True)
        for _ in range(50):
            if lib.broadcast.status["listening"]:
                break
            time.sleep(0.05)
        c = socket.create_connection(("127.0.0.1", port))
        c.sendall(b"SOURCE /stream ICE/1.0\r\nAuthorization: Basic c291cmNlOmhhY2ttZQ==\r\n"
                  b"Content-Type: application/ogg\r\n\r\n")
        self.assertIn(b"200 OK", c.recv(100))
        c.sendall(fx.traktor_broadcast("Bachata Rosa", "Juan Luis Guerra"))
        for _ in range(50):
            if lib.read_now_playing()[1]:
                break
            time.sleep(0.05)
        _m, info = lib.read_now_playing()
        self.assertEqual(lib.match_now_playing(info), file_id(paths[3]))
        # next track: Traktor starts a new Ogg stream with new comments
        c.sendall(fx.traktor_broadcast("Obsesión", "Aventura", serial=8))
        for _ in range(50):
            if (lib.read_now_playing()[1] or {}).get("title") == "Obsesión":
                break
            time.sleep(0.05)
        self.assertEqual(lib.match_now_playing(lib.read_now_playing()[1]), file_id(paths[2]))
        c.close()
        lib.close()

    def test_ogg_parser_handles_split_pages(self):
        from alpha_dj_bud.traktor_library import OggCommentParser
        got = []
        p = OggCommentParser(got.append)
        data = fx.traktor_broadcast("Idilio", "Willie Colón")
        for i in range(0, len(data), 7):          # arrives in small pieces
            p.feed(data[i:i + 7])
        self.assertEqual(got, [{"title": "Idilio", "artist": "Willie Colón"}])


class RekordboxTest(unittest.TestCase, ReaderChecks):
    def test_master_db(self):
        tmp = tempfile.mkdtemp()
        db, paths = fx.rekordbox(tmp)
        lib = software.open_library("rekordbox", software.find("rekordbox", db))
        lib.refresh(force=True)
        self.check_library(lib, paths, "rekordbox")
        self.assertNotIn("Deleted", [t.title for t in lib.tracks.values()])
        self.assertNotIn("Smart", [n[0] for n in names(lib)])
        _m, info = lib.read_now_playing()
        self.assertEqual(lib.match_now_playing(info), file_id(paths[3]))
        fx.rekordbox_play(db, "1000", "2026-11-23 22:05:00.000 +00:00", 1)
        _m, info = lib.read_now_playing()
        self.assertEqual(info["track_id"], file_id(paths[0]))
        self.assertEqual(len(lib.history_sessions()[0]["tracks"]), 3)
        lib.close()

    def test_exported_xml(self):
        tmp = tempfile.mkdtemp()
        xml, paths = fx.rekordbox_xml(tmp)
        self.assertEqual(software.find("rekordbox", xml), xml)
        lib = software.open_library("rekordbox", xml)
        lib.refresh(force=True)
        self.assertEqual(len(lib.tracks), 5)
        self.assertEqual(lib.get(file_id(paths[1])).key, "3B")
        sensual = next(n["id"] for n in lib.tree() if n["name"] == "Sensual")
        self.assertEqual(lib.tracks_in(sensual), [file_id(paths[0]), file_id(paths[1])])


class KeyFormatsTest(unittest.TestCase):
    def test_open_key_and_traktor_index(self):
        from alpha_dj_bud import camelot
        self.assertEqual(camelot.parse("1d"), "8B")
        self.assertEqual(camelot.parse("6m"), "1A")
        self.assertEqual(camelot.parse("12d"), "7B")
        self.assertEqual(camelot.from_traktor_index(21), "8A")
        self.assertEqual(camelot.from_traktor_index(0), "8B")
        self.assertIsNone(camelot.from_traktor_index(30))


class ChooseSoftwareTest(unittest.TestCase):
    def _state(self, tmp, settings=None):
        os.environ["ALPHA_DJ_BUD_HOME"] = os.path.join(tmp, "home")
        os.makedirs(os.environ["ALPHA_DJ_BUD_HOME"], exist_ok=True)
        if settings is not None:
            with open(os.path.join(tmp, "home", "settings.json"), "w") as f:
                json.dump(settings, f)
        from alpha_dj_bud.server import AppState
        return AppState()

    def test_first_start_asks_then_follows_the_software(self):
        tmp = tempfile.mkdtemp()
        home, paths = fx.virtualdj(tmp)
        st = self._state(tmp)
        snap = st.snapshot()
        self.assertFalse(snap["software"]["chosen"])
        self.assertIsNone(st.library)
        st.poll()                                   # nothing to read before the choice
        st.settings["libraryPaths"] = {"virtualdj": home}
        r = st.action("software", {"id": "virtualdj"})
        self.assertEqual(r, {"ok": True, "restart": False})
        snap = st.snapshot()
        self.assertEqual(snap["software"]["id"], "virtualdj")
        self.assertTrue(snap["software"]["chosen"])
        self.assertEqual(snap["playlists"][0]["group"], "app")
        sensual = next(p["id"] for p in snap["playlists"] if p["name"] == "Sensual")
        st.action("playlist", {"id": sensual})
        st.poll()
        self.assertEqual(st.current_id, file_id(paths[3]))     # last entry of the history
        self.assertEqual(st.current_source, "app")
        self.assertTrue(st.snapshot()["suggestions"])
        # the choice is saved
        with open(os.path.join(tmp, "home", "settings.json")) as f:
            self.assertEqual(json.load(f)["software"], "virtualdj")
        # a new track played in VirtualDJ becomes the current one
        fx.virtualdj_play(home, paths[0], TITLES[0], "Romeo Santos", int(time.time()))
        st.poll()
        self.assertEqual(st.current_id, file_id(paths[0]))

    def test_switching_keeps_each_softwares_playlists(self):
        tmp = tempfile.mkdtemp()
        vhome, _ = fx.virtualdj(os.path.join(tmp, "v"))
        shome, _ = fx.serato(os.path.join(tmp, "s"))
        st = self._state(tmp, {"software": "virtualdj",
                               "libraryPaths": {"virtualdj": vhome, "serato": shome}})
        st.action("playlist", {"id": "virtualdj:all"})
        self.assertEqual(st.action("software", {"id": "serato"})["restart"], False)  # no window: reload here
        self.assertEqual(st.software(), "serato")
        self.assertEqual(st.settings["playlistByGenre"], {})
        self.assertEqual(st.library.SOFTWARE, "serato")
        st.action("playlist", {"id": "serato:all"})
        st.action("software", {"id": "virtualdj"})
        self.assertEqual(st.settings["playlistByGenre"], {"bachata": "virtualdj:all"})
        self.assertEqual(st.action("software", {"id": "nope"})["ok"], False)

    def test_existing_djay_user_is_asked_once(self):
        tmp = tempfile.mkdtemp()
        db = fixture.build(os.path.join(tmp, "MediaLibrary.db"))
        st = self._state(tmp, {"playlistByGenre": {"bachata": "F-BACHATA"}, "dbPath": db})
        self.assertFalse(st.snapshot()["software"]["chosen"])
        self.assertEqual(st.settings["libraryPaths"]["djay"], db)    # old setting kept
        st.action("software", {"id": "djay"})
        self.assertEqual(st.settings["playlistByGenre"], {"bachata": "F-BACHATA"})   # playlists kept
        self.assertEqual(st.pool()[:1], ["t01"])

    def test_detects_installed_software(self):
        tmp = tempfile.mkdtemp()
        st = self._state(tmp)
        found = st.detect_software()
        self.assertEqual(set(found), set(software.ORDER))


if __name__ == "__main__":
    unittest.main()
