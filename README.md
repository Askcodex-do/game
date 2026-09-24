# Covert Strike: Stage One

A single-stage stealth FPS in the spirit of the classic military-infiltration
games of the early 2000s, built as an original work from scratch in Python.

Everything in the game is generated in code: there are no image files, no audio
files, and no third-party art. Walls, floors, guards, cameras, trucks, weapon
sounds and the entire soundtrack are synthesised procedurally at start-up, so
the whole game ships as a handful of Python modules and a single executable.

> This is an original tribute, not a copy. It uses no assets, names, level
> layouts or music from any existing commercial game.

---

## The stage: Silent Depot

You insert under cover of darkness into a supply depot to sabotage a convoy
before it rolls out at dawn.

| | |
|---|---|
| **Location** | Border supply depot, night |
| **Primary objectives** | Disable the camera network, destroy the two fuelled bowsers, recover three sets of intel, eliminate the garrison colonel, then reach the extraction pad |
| **Bonus objectives** | Complete the stage without tripping a single alarm (Ghost); finish every guard (Marksman) |
| **Failure** | Operator killed |

The compound is a mix of outdoor yards, two buildings with interiors, a motor
pool, a warehouse and a command post. Seven swivelling cameras watch the open
ground, twelve guards patrol and react to sight, sound and injury, and five army
trucks - two of them fuelled bowsers - sit in the motor pool or drive patrol
routes.

## Running it

```
pip install -r requirements.txt
python main.py
```

### Command line

| Flag | Effect |
|---|---|
| `--fullscreen` | Start fullscreen (F11 toggles at any time) |
| `--no-audio` | Silence everything |
| `--low-detail` | Halves ground-casting work, for weak GPUs |
| `--scale N` | Window scale factor (default 2) |
| `--smoke N` | Headless N-frame simulation test, prints a report |

## Controls

| Key | Action |
|---|---|
| `W` `A` `S` `D` | Move |
| Mouse | Look |
| `Shift` | Sprint (burns stamina) |
| `C` / `Ctrl` | Crouch (quieter, slower) |
| `Space` | Mantle |
| Left Mouse | Fire (hold for automatic weapons) |
| Right Mouse | Scope (sniper rifle) |
| `R` | Reload |
| `1`-`6` | Select weapon |
| `Q` / Wheel | Cycle weapons |
| `G` | Throw grenade |
| `E` | Interact |
| `Tab` | Objectives and enlarged minimap |
| `M` | Mute |
| `F5` / `F9` | Quick save / quick load |
| `F3` | Debug overlay |
| `Esc` | Pause |

## Weapons

| Weapon | Character |
|---|---|
| SOCOM pistol | Quiet, accurate, generous reserve |
| Kite SMG | Fast automatic, high rate of fire |
| Breacher shotgun | Eight pellets, brutal up close, slow |
| Longview sniper | Scoped, one-shot lethal, slow bolt |
| Frag grenade | Timed fuse, bounces off walls, radial blast |

Guards are loud in numbers: noise from footsteps, gunshots and explosions
propagates and will pull patrols toward you. Staying crouched shrinks your
footstep radius considerably.

## Building the Windows executable

A real `.exe` cannot be cross-compiled from Linux, so the build runs on a
Windows runner in GitHub Actions:

**Actions -> Build Windows EXE -> Run workflow**

The workflow installs the pinned dependencies, runs the full test suite and the
headless smoke test, then builds `dist/CovertStrike.exe` with PyInstaller and
uploads it as a downloadable artifact. Pushing a tag like `v1.0.0` additionally
attaches the executable to a GitHub Release.

To build locally on Windows:

```
pip install -r requirements.txt pyinstaller==6.11.1
python -m PyInstaller covert_strike.spec --noconfirm --clean
```

The result is a single self-contained `CovertStrike.exe` - no installer, no
Python required on the target machine.

## Target platform

Tuned for Windows 8.1 / x64 with 2 GB of RAM and Python 3.10.11:

* `pygame==2.6.1` and `numpy==1.26.4` both have prebuilt CPython 3.10 wheels and
  are the last releases with clean Windows 8.1 support.
* All art is generated into small fixed-size surfaces at start-up, so the
  resident set stays modest.
* The renderer is resolution-locked at 480x270 and scaled up on presentation,
  which is what makes a software raycaster run comfortably on old hardware.
* `--low-detail` halves the ground-casting loop for the weakest GPUs.

## Verification

```
python -m pytest tests -q      # 62 functional tests
python main.py --smoke 600     # headless end-to-end simulation
```

The test suite drives real code paths rather than mocks: it shoots guards,
trips camera alarms, detonates grenades against walls, destroys the bowsers,
picks up intel and plays the whole mission to completion, then asserts on the
result. Render tests check the depth buffer, occlusion and frame timing; audio
tests synthesise every registered sound and music track and verify they are
finite and non-silent.

## How it fits together

```
main.py                entry point, menus, states, the game loop
src/config.py          tuning constants (resolution, speeds, damage)
src/utils.py           geometry and math helpers
src/audio/             procedural synthesis: synth, sfx, music, registry, mixer
src/engine/            textures, raycaster, sprites, particles, HUD
src/game/              level, player, weapons, enemies, cameras, vehicles,
                       objectives, mission
tests/                 functional test suite
covert_strike.spec     PyInstaller build definition
```

The renderer is a DDA grid raycaster. Walls are cast per column, the ground
plane is cast per row (one vectorised numpy computation per screen row), and
entities are depth-sorted billboards tested against a z-buffer so they hide
correctly behind geometry. Sprites are pre-shaded into a small lookup of
brightness levels, which is what keeps billboard drawing cheap.

The audio engine synthesises every waveform with numpy - gunshots are filtered
noise bursts with an envelope, footsteps are short transients, the alarm is a
two-tone sweep, and the music is built from generated note sequences rendered
through simple oscillator voices.

## Credits

Original work. No copyrighted assets, music, sound recordings, models, level
data or trademarks from any existing game were used or reproduced.
