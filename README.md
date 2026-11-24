# Alpha DJ Bud — by DJ Fabio

🇬🇧 **English** · 🇮🇹 [Italiano](README.it.md)

A next-track assistant for DJs who play **Bachata, Salsa and Zouk** on Mac with **djay Pro, VirtualDJ, rekordbox, Serato DJ (Lite / Pro) or Traktor Pro**. It suggests the next tracks in real time.

The app is in **English** by default and can be switched to **Italian** or **Spanish** in ⚙ Settings → **Language**.

![Alpha DJ Bud](docs/screenshot-full.png)

## Supported DJ software

The first time you open Alpha DJ Bud it asks which DJ software you use (the ones with a library on the Mac are marked). The choice is saved; to change it later go to ⚙ Settings → **DJ software**: Bud restarts and loads the library of the new software. Each software keeps its own folder/playlist per genre, and what Bud Brain learned follows the audio files.

| Software | Library and playlists | Track on air | What to do |
|---|---|---|---|
| **djay Pro** | `~/Music/djay/…/MediaLibrary.db` | `NowPlaying.txt` (1–2 s) | nothing |
| **VirtualDJ** | `database.xml`, Lists (`MyLists`) and old `Playlists` in `~/Library/Application Support/VirtualDJ` (or `~/Documents/VirtualDJ`), plus the `database.xml` on external drives | the day's History file, written while you play | nothing. VirtualDJ adds a track only after it has been audible for `historyDelay` seconds (45 by default, fader up): set it to 15–20 in Settings → Options for a quicker update |
| **Serato DJ Lite / Pro** | `database V2` and crates in `~/Music/_Serato_` (and `_Serato_` on external drives); sub-crates become folders | the history session, written while you play | nothing |
| **rekordbox 6 / 7** | `~/Library/Pioneer/rekordbox/master.db` (encrypted: the first time Bud installs the component to read it, internet needed) | the history in the database | nothing. If the database can't be opened: in rekordbox **File → Export Collection in xml format** and write that file in ⚙ Settings → library path (playlists only, no track on air) |
| **Traktor Pro** | `collection.nml` in `~/Documents/Native Instruments/Traktor <version>` (Traktor saves it when it closes or with File → Save Collection) | **Broadcasting** | in Traktor, Preferences → **Broadcasting**: Address `localhost`, Port `8000`, Format Ogg Vorbis (lowest quality is fine), then switch on Broadcasting (antenna icon). Bud listens on that port and reads only title and artist |

For every software: key and BPM come from the software's analysis (also Open Key, e.g. "6m", or musical keys like "Am"), drag works onto the deck's waveform like a drag from the Finder, and the live BPM is read from the software's window when it exposes it (otherwise Bud uses the analysed BPM). The Apple Music library and the folders on the Mac work the same with every software.

## What it does

The description below uses djay as the example; with the other software everything works the same way, with the differences listed in the table above.

1. **Connects to djay Pro automatically.** It reads djay's library (read-only, it never changes anything): `~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db`.
   - **Now playing** comes from `NowPlaying.txt`, the file djay itself updates with the track on air, so it changes in about 1–2 seconds. If that file isn't there, Bud uses djay's history. If needed, you can set the playing track manually with the search on the right.
   - If djay plays a track that isn't in any library Bud can read (e.g. streaming), a warning with its title appears at the top.
   - **Live BPM**: if you change the tempo in djay (tempo fader, SYNC, pitch), Bud finds the playing track's title in djay's window and reads the BPM shown next to it — whatever layout you use — and calculates the suggestions from the tempo you're actually playing at. The BPM box gets a green dot and shows the original BPM below ("orig. 118.0"). Needs the **Accessibility** permission (System Settings → Privacy & Security → Accessibility); without it Bud uses the analysed BPM. Can be turned off in ⚙ Settings, where you also see what Bud found (BPM read, or why not).
2. **You set it up before the night:**
   - **Event**: Bachata, Salsa, Zouk, or a mixed night (Bachata + Salsa).
   - **Now playing**: the genre you are playing right now.
   - **Folder / Playlist**: one folder or playlist per genre. The menu is split into three groups, like djay's sources:
     - **djay**: "All djay tracks" and djay's own playlists and folders;
     - **Apple Music (Music app)**: "Whole Music library", special lists like "Purchased" and your Music playlists and folders (djay's "Music" source);
     - **Folders on the Mac**: the folders you add in Settings (djay's Finder / My files source, USB drives).

     Folders include every playlist inside them. Bud remembers the choice for each genre.
   - The **BACHATA / SALSA / ZOUK** buttons are always clickable (also in MINI): picking a genre outside the current night switches the night too.
3. **Suggests the next tracks** from the chosen folder, with these rules:
   - **Key (Camelot Wheel)**. Example with 3A playing: **3A, 3B, 2A, 4A** and **9A, 9B** (6-step jump). The same rules apply to B keys.
   - **BPM**: within a tolerance **set per genre** in ⚙ Settings (default Bachata ±4, Salsa ±6, Zouk ±10).
   - **Up / down in BPM**: after the 3 best suggestions, positions 4 and 5 hold the best track **to go up** (orange label) and the best **to go down** (blue label) in BPM. These two ignore the genre's tolerance: in every genre they are **4 to 10 BPM** away from the playing track, the closest to 4 first (4, then 5, …), so you can steer the energy of the set.
   - **Never the same artist twice in a row.** Featurings and collaborations count too ("Romeo Santos & Drake", "feat. Romeo Santos"...). The rule can cover the last N tracks.
   - Tracks already played in the set are excluded.
   - **Variety from night to night**: if you play the same hit on Friday and Saturday, the suggestions after it change. Tracks you put after it recently, and the ones already suggested then, move down. Within the same set the list stays stable. Adjustable in ⚙ Settings → Suggestion variety (Off / Low / Medium / High).
   - In the list, each artist appears only once at the top. Their other tracks follow further down.
4. **Learns your taste**, offline on your Mac and separately for each genre. It records:
   - the transitions you actually make, whether you follow its suggestions or not;
   - the tracks you play most;
   - the key relations you prefer and whether you tend to raise or lower the BPM;
   - the suggestions you always skip;
   - the ♥ and ✕ you give.

   The more sets you play, the more this counts (**CONFIDENCE** meter). **"Learn from djay history"** also learns from sets you played in the past.
5. **Music app tracks**: Bud reads the Music app library (playlists, files). Key and BPM come from djay's analysis when djay has analysed the track, otherwise from the Camelot key / BPM written in the comments or file name (e.g. "12A - 126 - Title", "12A - Energy 6" from Mixed In Key). The first time, macOS asks to allow access to **Media & Apple Music** (and, if Bud has to ask the Music app directly, **Automation → Music**). If the library isn't read, Settings shows the exact reason and a **Retry** button. Streaming tracks (Apple Music streaming, Spotify, TIDAL) have no file and can't be read or dragged.
6. **Folders on the Mac** (like djay's Finder / My files source and USB drives): in ⚙ Settings → Folders on the Mac, add the folders with your music. Each sub-folder becomes a playlist in the "Folders on the Mac" group. Title, artist, BPM and key come from djay's analysis or from the file tags / name.
7. **Drag into djay**: drag a suggestion onto a djay deck — drop it on the deck's **waveform area** (not on the title), just like dragging a file from the Finder. Rows with the ⠿ mark have a local file. Streaming tracks (TIDAL, Apple Music...) can't be dragged: load them from djay.
8. **MINI window**: the **▣ MINI** button turns the app into a small window that **stays on top** of djay, with only the genre buttons (clickable), the playing track and the suggestions. The normal window and the MINI window each **remember their own position and size**, and are always kept on screen.

<img src="docs/screenshot-mini.png" width="260" alt="MINI mode">

## Installation (Mac)

1. Download the repository (green **Code → Download ZIP** button, or the ZIP from the latest release) and unzip it.
2. **Double-click** `Install Alpha DJ Bud.command`.
   - If macOS says it is not safe or can't be verified, see [Unblocking the installer](#unblocking-the-installer-macos-security-warning) below.
   - The installer needs internet once, to download the components.
   - If Python 3 is missing, open Terminal and run `xcode-select --install`, then run the installer again.
3. The installer creates **Alpha DJ Bud.app** in your **Applications** folder (`~/Applications`), with its own name and icon, and opens it. Drag it to the Dock to keep it handy. After that you can delete the downloaded folder.
4. The first time, choose your DJ software. Then open it, choose the genre and folder in Alpha DJ Bud, and start playing.

### Updates

From v1.5.0 the app **updates itself**: at startup and every 6 hours it checks GitHub for a newer **release**. When there is one, a green **⬆ vX.Y.Z** button appears at the top. Click it, confirm, and in about 10 seconds the app closes and reopens with the new version. It never updates by itself during a set: you choose when.

- Before switching, the new version is tested; if it doesn't start, the current one is kept. The previous version is kept as a backup in `~/Library/Application Support/Alpha DJ Bud/app.old`.
- ⚙ Settings → Updates: turn the automatic check on/off, or **Check now**.
- Settings and what Bud has learned are always kept.
- Only published GitHub **releases** count (with a tag like `v1.6.0`), not every change to the code.

If you have a version older than 1.5.0, download this version once and run `Install Alpha DJ Bud.command`.

### Unblocking the installer (macOS security warning)

macOS (Gatekeeper) blocks every file downloaded from the internet that is not signed by a developer registered with Apple. This doesn't mean the file is dangerous. You only need to unblock it once, in one of two ways.

**Option 1 – From System Settings (recommended)**

1. Try to open `Install Alpha DJ Bud.command` and close the warning with **Done** / **OK**.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to **Security**. Next to the message about "Install Alpha DJ Bud.command", click **Open Anyway**.
4. Confirm with your Mac password. From then on a double-click opens it normally.

On recent macOS versions the old "right-click → Open" trick no longer works.

**Option 2 – From Terminal (unblocks the whole folder)**

1. Open **Terminal** (Spotlight → "Terminal").
2. Type `xattr -dr com.apple.quarantine ` (with a space at the end), **drag the Alpha DJ Bud folder into the window**, and press Enter.
3. Double-clicking `Install Alpha DJ Bud.command` now works.

**If double-clicking still doesn't work**, run it from Terminal: type `bash ` (with a space), drag in the `Install Alpha DJ Bud.command` file and press Enter.

The app created by the installer is built on your own Mac, so macOS doesn't block it.

### Without the native window

Without `pywebview` the app opens in Chrome/Edge/Brave in app mode, or in your default browser. In these cases the window does not stay on top of djay.

From Terminal:

```bash
python3 -m alpha_dj_bud.app            # native window
python3 -m alpha_dj_bud.app --browser  # in the browser
python3 -m alpha_dj_bud.app --db "/path/to/MediaLibrary.db"
```

## How Bud Brain works

Bud Brain is the part of the app that **learns your taste**. Everything stays on your Mac (`brain.json`), separately for each genre (Bachata, Salsa, Zouk), and nothing is sent anywhere.

**What it records**, every time a new track starts in djay:

| What | How it's used |
|---|---|
| **Transitions** (track A → track B) | If you often play B after A, B goes up when A is playing ("you played it after this track") |
| **How often each track is played** | Your most played tracks get a small boost ("one of your most played") |
| **Key relations you use** | If you usually mix in the same key, or +1, or relative A/B, those relations score higher |
| **BPM direction** | If you tend to go up, stay level or go down in BPM, suggestions that do the same score higher |
| **Suggestions you skip** | Tracks shown in the top 5 that you keep not choosing slowly go down |
| **♥ / ✕** | ♥ raises a track for that genre; ✕ hides it for the current set |
| **Recent nights** | Follow-ups you used after a hit in recent sets go down for a while, so suggestions change from night to night (Settings → Suggestion variety) |

**How a suggestion is scored**

1. **Hard rules first** (never broken): compatible Camelot key, BPM within the genre's tolerance (default Bachata ±4, Salsa ±6, Zouk ±10), no artist from the last N tracks, not already played in the set.
2. **Base score**: how good the key relation is (same key best, then relative / ±1, then +6) and how close the BPM is.
3. **Learned score**: the table above, blended with the base score. Its weight grows with **Confidence**.
4. **Variety**: a small night-to-night rotation, stable within the same set.
5. **Order**: the 3 best suggestions first, then the track to go up (4th) and to go down (5th) in BPM (4–10 BPM away, any genre), then the rest.

**The two dials**

- **CONFIDENCE**: how much Bud trusts what it has learned for the selected genre. It grows with the number of transitions it has seen: 0% = brand new (suggestions are based only on key and BPM), 100% = after about 40 transitions (the learned taste weighs up to about a third of the score).
- **FOLLOWED**: the share of your transitions where the track you played next was one of Bud's suggestions at that moment. It tells you how well Bud is guessing your choices.

**Tips**: press **LEARN FROM DJAY HISTORY** once per genre so Bud learns from the sets already in djay; press **END SET** at the end of the night. To start from scratch, delete `brain.json` in `~/Library/Application Support/Alpha DJ Bud/`.

## During the night

| Action | How |
|---|---|
| Load into djay | Drag a suggestion onto a djay deck |
| Playing track | Automatic from djay (NowPlaying.txt, or its history). If needed, set it with the search in "Set now playing manually" |
| Change genre | Click **BACHATA / SALSA / ZOUK** (also in MINI) |
| Like / don't suggest | **♥** / **✕** on the suggestion row |
| End of the night | **END SET**: saves what Bud has learned |
| New set | **NEW SET**: resets played and hidden tracks |
| Settings ⚙ | Language (English / Italiano / Español), BPM tolerance per genre, suggestion variety, folders on the Mac, artist window, 6-step jump, double/half tempo, key from Mixed In Key comments, automatic genre switch, library path |

On a **mixed night**, if you play a track that sits in another genre's folder, Bud switches genre on its own.

**Key and BPM**: first the values analysed by djay; otherwise the file tags (BPM / initial key), the Camelot key and BPM written in comments or file names (e.g. "12A - 126 - Title", "12A - Energy 6"), or the BPM in the title (e.g. "… 94 Bpm"). Tracks without key or BPM are counted among the excluded ones at the bottom of the list. If you use Mixed In Key, you can have Bud prefer the Camelot key written in the comments.

## Data

- Everything lives in `~/Library/Application Support/Alpha DJ Bud/`:
  - `settings.json`: your settings, playlists per genre, window positions;
  - `brain.json`: what Bud has learned (delete it to start from scratch);
  - `files-cache.json`: tags read from the folders on the Mac;
  - `drag-method.json`: the drag method djay accepts;
  - `alpha-dj-bud.log`: log for troubleshooting;
  - `app` / `venv`: the installed app (and `app.old`, the previous version).
- The djay library, the Music library and your files are never modified.

## Code structure

```
alpha_dj_bud/
  software.py      the supported DJ software and how to open each library
  library_base.py  what all libraries share (Apple Music, folders, files, now-playing matching)
  tsaf.py          decoder for djay's binary TSAF format
  djay_library.py  djay: folders, playlists, tracks, key/BPM, history (now playing)
  virtualdj_library.py  VirtualDJ: database.xml, lists, history
  serato_library.py     Serato: database V2, crates, history sessions
  traktor_library.py    Traktor: collection.nml, history, Broadcasting receiver
  rekordbox_library.py  rekordbox: master.db (SQLCipher) or exported XML
  camelot.py       Camelot rules and djay key → Camelot mapping
  artists.py       artist / featuring matching
  recommender.py   suggestion filters and scoring
  learning.py      local learning per genre
  server.py        local server + djay monitor
  updater.py       in-app updates from GitHub releases
  music_library.py Music app library (iTunesLibrary framework)
  local_files.py   folders on the Mac (tags via mutagen)
  deck_reader.py   reads the live BPM of the playing deck from djay's window (Accessibility)
  native_drag.py   macOS file drag from the window onto djay (3 methods, the one djay accepts is remembered)
  app.py           launch and window (pywebview / browser)
  web/             interface (HTML/CSS/JS, translations in i18n.js)
assets/            app icon
tools/make_icon.py draws the icon
tests/             tests with fake libraries of every software
```

Tests: `python3 -m unittest discover -s tests -t .`

To add a language, copy the `en` block in `alpha_dj_bud/web/i18n.js`, translate it, and add the code to `LANGUAGES` in `server.py` and to the selector in `index.html`.

## Known limits

- **Mac only**.
- The library formats of these programs are not officially documented. An update could change them; in that case the light next to the software's name turns red.
- **Traktor**: the track on air needs Broadcasting on (and Bud uses its port: Traktor can't broadcast to a real radio server at the same time); new tracks and playlists appear after Traktor saves its collection.
- **rekordbox**: with an exported XML the track on air isn't available; set it with the search.
- If djay doesn't write `NowPlaying.txt`, the playing track comes from djay's history, which djay doesn't update for every track.
- If a drag doesn't start, the app shows a message with the reason: send it to support. Details are also in `~/Library/Application Support/Alpha DJ Bud/alpha-dj-bud.log` (lines starting with `[drag]`).
- **Spotify, TIDAL, SoundCloud, Beatport and Apple Music streaming** playlists can't be read: djay doesn't save them on the Mac and those tracks have no file. Tracks djay has already analysed still appear in "All djay tracks".
- Drag works only for tracks with a local file, and the drive holding it must be connected. The full drag to djay needs the native window (installed app); in the browser it depends on the browser.
- With the native window, the Dock and the menu bar show "Alpha DJ Bud" and its icon; in a few places macOS may still say "Python", because that's the engine running the app.
