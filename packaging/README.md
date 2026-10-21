# Packaging: Muse Monitor as an app

A one-folder PyInstaller build that needs no Python on the target machine. macOS (Apple Silicon) now; Windows next.
Design and review: `debate/claude-packaging-proposal.md` (kept local).

| File | Role |
|---|---|
| `requirements-bundle.txt` | exactly what the app contains, fixed versions (OpenCV and pylsl included: camera, demo video and LSL are in the release) |
| `musemonitor.spec` | the PyInstaller build: bundles `extensions/` and `study/` as data (loaded from files at run time), finds the modules they import, collects native libraries (BrainFlow, liblsl, OpenCV), and writes the macOS `Info.plist` (Bluetooth and camera permission texts) |
| `entry.py` | the app's entry point (`musemonitor.app.main`) |
| `make_dmg.sh` | wraps the macOS app in a `.dmg` with an Applications link |
| `icon/` | the app icon: **`icon.svg` is the editable source** (design *A — headband + EEG*, `design-A-headband-eeg.pdf`); `make_icons.py` regenerates `MuseMonitor.icns` (macOS, with the standard margin), `MuseMonitor.ico` (Windows), `preview.png` and the window icon `src/musemonitor/ui/app_icon.png`. The generated files are committed. |

## Changing the icon

Edit `packaging/icon/icon.svg` (any vector editor, or by hand: colours and shapes are commented), or replace it with
another design of the same size (1024 × 1024, full bleed, rounded square), then:

```bash
~/.venvs/musemonitor/bin/python packaging/icon/make_icons.py      # .icns needs macOS
```

and rebuild the app.

## Build by hand (macOS)

Build **outside** an iCloud-synced folder (e.g. not on Desktop): Finder metadata there makes code signing fail.

```bash
python3.12 -m venv ~/.venvs/musemonitor-build && source ~/.venvs/musemonitor-build/bin/activate
pip install -r packaging/requirements-bundle.txt
pyinstaller packaging/musemonitor.spec --noconfirm --distpath /tmp/mm/dist --workpath /tmp/mm/build
"/tmp/mm/dist/Muse Monitor.app/Contents/MacOS/Muse Monitor" --self-check     # every check must say OK
packaging/make_dmg.sh /tmp/mm/dist MuseMonitor-macos-arm64.dmg
```

The GitHub workflow `.github/workflows/build.yml` does the same on `macos-15` (run it from the Actions tab, or push a
`v*` tag to attach the `.dmg` to a release).

## What the packaged app does differently

- Bundled extensions and studies are read from inside the app (read-only). **New extensions** are created with
  *Extensions ▸ Manage ▸ New extension…* and go to `~/.musemonitor/extensions` (there is no `plugins new` command in
  the app). Personal extensions there are loaded too, but can only use the libraries in the bundle
  (`requirements-bundle.txt` and the Python standard library).
- Recordings go to `~/MuseMonitor/data` (or `$MUSEMONITOR_DATA_DIR`), never inside the app.
- `--self-check [--report FILE]` exercises every feature without a headset (extensions, BrainFlow, Bluetooth backend,
  Qt Multimedia, OpenCV + YuNet, mp4 writing, LSL loopback), writing only to a temporary folder.
  `--quit-after SEC` opens the app and quits (a start-up smoke test).

## Limits

- Not signed with an Apple Developer ID (ad-hoc signature only): the first time, right-click the app → Open, or
  System Settings ▸ Privacy & Security ▸ Open Anyway.
- About 380 MB installed, 160 MB as a `.dmg`.
