# Alpha DJ Bud

🇬🇧 **English** · 🇮🇹 [Italiano](README.it.md)

A next-track assistant for DJs who play **Bachata, Salsa and Zouk** with **djay Pro on Mac**. It suggests the next tracks in real time.

The app is in **English** by default and can be switched to **Italian** or **Spanish** in ⚙ Settings → **Language**.

![Alpha DJ Bud](docs/screenshot-full.png)

## What it does

1. **Connects to djay Pro automatically.** It reads djay's library (read-only, it never changes anything): `~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db`. When you start a track, djay writes it to its history and Bud picks it up in about 1–2 seconds.
2. **You set it up before the night:**
   - **Event**: Bachata, Salsa, Zouk or a mixed night.
   - **Now playing**: the genre you are playing right now.
   - **Folder / Playlist**: one djay folder or playlist per genre. Folders include every playlist inside them. Bud remembers the choice for each genre.
3. **Suggests the next tracks** from the chosen folder, with these rules:
   - **Key (Camelot Wheel)**. Example with 3A playing: **3A, 3B, 2A, 4A** and **9A, 9B** (6-step jump). The same rules apply to B keys.
   - **BPM**: same BPM or at most **±4** (adjustable).
   - **Never the same artist twice in a row.** Featurings and collaborations count too ("Romeo Santos & Drake", "feat. Romeo Santos"...). The rule can cover the last N tracks.
   - Tracks already played in the set are excluded.
4. **Learns your taste**, offline on your Mac and separately for each genre. It records:
   - the transitions you actually make, whether you follow its suggestions or not;
   - the tracks you play most;
   - the key relations you prefer and whether you tend to raise or lower the BPM;
   - the suggestions you always skip;
   - the ♥ and ✕ you give.

   The more sets you play, the more this counts (**CONFIDENCE** meter). **"Learn from djay history"** also learns from sets you played in the past.
5. **MINI window**: the **▣ MINI** button turns the app into a small 360×560 window that **stays on top** of djay. It shows only the genre, the playing track and the suggestions.

<img src="docs/screenshot-mini.png" width="260" alt="MINI mode">

## Installation (Mac)

1. Download the repository (green **Code → Download ZIP** button) and unzip it.
2. **Double-click** `Alpha DJ Bud.command`.
   - If macOS says the app is not safe or can't be verified, see [Unblocking the app](#unblocking-the-app-macos-security-warning) below.
   - On first launch it installs `pywebview`, which needs internet once. This gives the native window and the always-on-top mode.
   - If Python 3 is missing, open Terminal and run `xcode-select --install`.
3. Open djay Pro, choose the genre and folder in Alpha DJ Bud, and start playing.

### Unblocking the app (macOS security warning)

macOS (Gatekeeper) blocks every file downloaded from the internet that is not signed by a developer registered with Apple. This doesn't mean the file is dangerous. You only need to unblock it once, in one of two ways.

**Option 1 – From System Settings (recommended)**

1. Try to open `Alpha DJ Bud.command` and close the warning with **Done** / **OK**.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to **Security**. Next to the message about "Alpha DJ Bud.command", click **Open Anyway**.
4. Confirm with your Mac password. From then on a double-click opens it normally.

On recent macOS versions the old "right-click → Open" trick no longer works.

**Option 2 – From Terminal (unblocks the whole folder)**

1. Open **Terminal** (Spotlight → "Terminal").
2. Type `xattr -dr com.apple.quarantine ` (with a space at the end), **drag the Alpha DJ Bud folder into the window**, and press Enter.
3. Double-clicking `Alpha DJ Bud.command` now works.

**If double-clicking still doesn't work**, start it from Terminal: type `bash ` (with a space), drag in the `Alpha DJ Bud.command` file and press Enter.

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
| Playing track | Automatic from djay (deck shown), or **▶** on a suggestion, or search in "Pick manually" |
| Like / don't suggest | **♥** / **✕** on the suggestion row |
| End of the night | **END SET**: saves what Bud has learned |
| New set | **NEW SET**: resets played and hidden tracks |
| Settings ⚙ | Language (English / Italiano / Español), BPM tolerance, artist window, 6-step jump, double/half tempo, key from Mixed In Key comments, automatic genre switch, library path |

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
  app.py           launch and window (pywebview / browser)
  web/             interface (HTML/CSS/JS, translations in i18n.js)
tests/             tests with a fake djay library
```

Tests: `python3 -m unittest discover -s tests -t .`

To add a language, copy the `en` block in `alpha_dj_bud/web/i18n.js`, translate it, and add the code to `LANGUAGES` in `server.py` and to the selector in `index.html`.

## Known limits

- **djay Pro for macOS** only (on Windows djay doesn't expose its data the same way).
- djay's database format is undocumented. A djay update could change it; in that case the **DJAY** light turns red.
- The playing track comes from djay's history, so it appears when djay logs it as played.
