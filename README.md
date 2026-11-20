# Alpha DJ Bud

🇬🇧 **English** · 🇮🇹 [Italiano](README.it.md)

A next-track assistant for DJs who play **Bachata, Salsa and Zouk** with **djay Pro on Mac**. It suggests the next tracks in real time.

The app is in **English** by default and can be switched to **Italian** or **Spanish** in ⚙ Settings → **Language**.

![Alpha DJ Bud](docs/screenshot-full.png)

## What it does

1. **Connects to djay Pro automatically.** It reads djay's library (read-only, it never changes anything): `~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db`.
   - **Now playing follows your faders**: a track becomes "now playing" only when you **raise its deck's volume fader** (and the crossfader lets it through). Pre-listening a track with the fader at zero changes nothing. The **FADER** light is green when this is active.
   - If the faders can't be read (permission not given yet, or djay's mixer hidden), Bud falls back to djay's history: the track appears when djay logs it as played. You can choose the mode in ⚙ Settings → Now playing follows.
2. **You set it up before the night:**
   - **Event**: Bachata, Salsa, Zouk, or a mixed night (Bachata + Salsa).
   - **Now playing**: the genre you are playing right now.
   - **Folder / Playlist**: one djay folder or playlist per genre. Folders include every playlist inside them. Bud remembers the choice for each genre.
3. **Suggests the next tracks** from the chosen folder, with these rules:
   - **Key (Camelot Wheel)**. Example with 3A playing: **3A, 3B, 2A, 4A** and **9A, 9B** (6-step jump). The same rules apply to B keys.
   - **BPM**: same BPM or at most **±4** (adjustable).
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
5. **Drag into djay**: drag a suggestion straight onto a djay deck, just like dragging a file from the Finder. Rows with the ⠿ mark have a local file. Streaming tracks (TIDAL, Apple Music...) can't be dragged: load them from djay.
6. **MINI window**: the **▣ MINI** button turns the app into a small 360×560 window that **stays on top** of djay. It shows only the genre, the playing track and the suggestions.

<img src="docs/screenshot-mini.png" width="260" alt="MINI mode">

## Installation (Mac)

1. Download the repository (green **Code → Download ZIP** button, or the ZIP from the latest release) and unzip it.
2. **Double-click** `Install Alpha DJ Bud.command`.
   - If macOS says it is not safe or can't be verified, see [Unblocking the installer](#unblocking-the-installer-macos-security-warning) below.
   - The installer needs internet once, to download the components.
   - If Python 3 is missing, open Terminal and run `xcode-select --install`, then run the installer again.
3. The installer creates **Alpha DJ Bud.app** in your **Applications** folder (`~/Applications`), with its own name and icon, and opens it. Drag it to the Dock to keep it handy. After that you can delete the downloaded folder.
4. **Allow Accessibility** (needed to follow the faders): the first time, macOS asks to let the app control the computer. Open **System Settings → Privacy & Security → Accessibility** and turn on the entry that appears (it may be called **Python**: it's the engine running Alpha DJ Bud). Then quit and reopen Alpha DJ Bud. Bud only *reads* djay's faders: it never moves anything.
5. Open djay Pro, choose the genre and folder in Alpha DJ Bud, and start playing.

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

## During the night

| Action | How |
|---|---|
| Load into djay | Drag a suggestion onto a djay deck |
| Playing track | Automatic: changes when you raise a deck's fader (deck shown, "ON AIR"). If needed, set it with the search in "Set now playing manually" |
| Like / don't suggest | **♥** / **✕** on the suggestion row |
| End of the night | **END SET**: saves what Bud has learned |
| New set | **NEW SET**: resets played and hidden tracks |
| Settings ⚙ | Language (English / Italiano / Español), now playing detection (faders / history), suggestion variety, BPM tolerance, artist window, 6-step jump, double/half tempo, key from Mixed In Key comments, automatic genre switch, library path |

On a **mixed night**, if you play a track that sits in another genre's folder, Bud switches genre on its own.

**Key and BPM** are the ones analysed by djay. If a track hasn't been analysed yet, Bud tries to read the BPM from the title (e.g. "… 94 Bpm"). Tracks without key or BPM are counted among the excluded ones at the bottom of the list. If you use Mixed In Key, you can have Bud read the Camelot key written in the comments.

## Data

- Settings and Bud's memory live in `~/Library/Application Support/Alpha DJ Bud/` (`settings.json`, `brain.json`). To start from scratch, delete `brain.json`.
- The djay library is never modified.

## Code structure

```
alpha_dj_bud/
  tsaf.py          decoder for djay's binary TSAF format
  djay_library.py  folders, playlists, tracks, key/BPM, history (now playing)
  camelot.py       Camelot rules and djay key → Camelot mapping
  artists.py       artist / featuring matching
  recommender.py   suggestion filters and scoring
  learning.py      local learning per genre
  server.py        local server + djay monitor
  updater.py       in-app updates from GitHub releases
  native_drag.py   macOS file drag from the window onto djay
  deck_monitor.py  reads djay's volume faders and crossfader (macOS Accessibility)
  app.py           launch and window (pywebview / browser)
  web/             interface (HTML/CSS/JS, translations in i18n.js)
assets/            app icon
tools/make_icon.py draws the icon
tests/             tests with a fake djay library
```

Tests: `python3 -m unittest discover -s tests -t .`

To add a language, copy the `en` block in `alpha_dj_bud/web/i18n.js`, translate it, and add the code to `LANGUAGES` in `server.py` and to the selector in `index.html`.

## Known limits

- **djay Pro for macOS** only (on Windows djay doesn't expose its data the same way).
- djay's database format is undocumented. A djay update could change it; in that case the **DJAY** light turns red.
- Fader following reads djay's main window and works with decks 1 and 2. In history mode, the playing track appears when djay logs it as played.
- Drag works only for tracks with a local file, and the drive holding it must be connected. The full drag to djay needs the native window (installed app); in the browser it depends on the browser.
- With the native window, the Dock and the menu bar show "Alpha DJ Bud" and its icon; in a few places macOS may still say "Python", because that's the engine running the app.
