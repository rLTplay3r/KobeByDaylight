# Changelog

Every new feature or fix raises the last number of the version in
`dbd_overlay/__init__.py` (0.0.12 -> 0.0.13).

## 0.0.21
- Timer matched frame by frame to the reference edits: bigger (digits ~9% of the screen
  height, hairline font, darker box), and the beat kick is as hard as in the video: the digits
  snap ~12% left and up out of the box, hang there smeared for a moment, spring back with a
  small overshoot. Only the digits move, the box stays.

## 0.0.20
- Killer POV: blinding the killer with the flashlight shows the blinded killer's view in the
  top-right corner with a "KILLER POV →" label, like in the edit. Detected while the right mouse
  button (flashlight) is held, from the white burst in the middle of the screen.
- Dancing Kobe from `dancing/` (black background made transparent while playing, empty margins
  cropped): at random moments and from the Dance button.
- Kobe going "shh" (hiding in a locker): Hide button for now, no detection yet.
- New toggles (Kobe dance, Killer POV on blind), Dance frequency, Dance and Killer POV sizes,
  and Dance / Hide / POV trial buttons.

## 0.0.19
- Fixed regular stutter on Windows while the overlay runs: the check whether the game is
  running now happens on a background thread and only reads process names on Windows
  (reading every process's command line took hundreds of milliseconds there).

## 0.0.18
- Prepared for the public GitHub repository: `.gitignore`, MIT license, README with download,
  usage and build-from-source instructions for Linux and Windows.
- Music is no longer part of the source; the build bundles whatever is in `Music/`.
- Removed `packaging/build.sh` and `packaging/build_windows_wine.sh` (replaced by the builder).

## 0.0.17
- The builder is also a standalone Linux executable with a window: `KBD-Builder` in the project folder.
  It finds the project next to itself (or asks once and remembers), and creates its build
  environment from the system Python on the first build.

## 0.0.16
- Kobe by Daylight Builder (`./build-tool.sh`): app that builds the Linux and Windows executables
  on Linux, sets up its own environments, raises the version and writes CHANGELOG notes.
- pynput is installed without its evdev dependency, so builds don't need a C compiler.

## 0.0.15
- Panel window is more compact: at most 600 px tall, the rest scrolls.
- First Windows executable build.

## 0.0.14
- Panel restyled after the DBD store screen: borderless window with torn edges, dried blood
  splatter with drips, status text on a blood smear, buttons painted as brush strokes.
- Built-in minimize and close buttons in the top-right corner; drag the window by any empty spot.

## 0.0.13
- Scale sliders are locked until "Edit scale" is clicked; the preview only starts from that button.
- Sliders ignore the mouse wheel, so scrolling the panel never changes a value.
- Kobe pop-up moved near the left edge of the screen and made bigger (0.6 of the screen height), like in the video.
- "Reset sizes" sets exactly 100% (was 99%).

## 0.0.12
- Scale for each on-screen element (timer, Kobe, speech bubble), 50-200%.
- Scale mode ("Edit layout"): shows the timer and Kobe on screen as a live preview while sizes change.
- New app icon (`KBD_icon.jpg`) for the tray, window, panel header and Windows executable.
- Version scheme changed to 0.0.x.

## 0.0.11
- Frequency sliders for Kobe pop-ups and random sounds (average time between them; real timing varies ±40%).
- Version numbers: shown in the panel, window title, tray tooltip and `--version`.
- Credits in the panel footer.

## 0.0.10
- Panel redesigned in the Dead by Daylight style: dark fog, blood red accents, Oswald caps,
  perk-diamond toggles, diamond sliders, status diamond. Tray menu restyled to match.

## 0.0.9
- Tray icon status dot: red = game not running, yellow = in game, green = in a match, gray = stopped.

## 0.0.8
- Pop-ups use a random sprite from `kobe-sprites/`; the bubble attaches to the head automatically.
- Random extra Kobe sounds during matches (every sound except "MAN" and "What Can I Say").
- The first Kobe comes at a random moment after spawn.

## 0.0.7
- Automatic match detection from the screen, like Fog Companion: looks for the perk rhombus HUD.
- Works at any resolution, aspect ratio (16:9, 21:9, 4:3) and HUD scale.
- Overlay follows the game's monitor, sizes everything from the screen height, sharp on HiDPI.
- "Save HUD capture" for tuning the detection.

## 0.0.6
- Timer jerks on the music's beat with an RGB split, like in the video.
- Recognizes the Epic/Heroic and Windows Store versions, natively or under Proton.
- F8 starts or ends a match by hand. Log-based detection removed (the game log is encrypted).
- Warns when started inside a Flatpak sandbox.

## 0.0.5
- Single-file executables: Linux build, `build.bat` for Windows, GitHub Actions for both.
- Assets next to the executable override the bundled ones.

## 0.0.4
- Tray app with control panel: start/stop, effect toggles, music and sound volume.
- Click-through overlay: stopwatch, Kobe pop-up with speech bubble and "What can I say".
- "Man" on Space, music during matches, `--simulate` test match.
