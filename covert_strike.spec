# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Covert Strike: Stage One.

Everything the game needs is generated at runtime (textures, sprites, sound
effects and music are all synthesised procedurally), so there are no data files
to bundle. The result is a single self-contained CovertStrike.exe with a real
Windows icon and version resource.

The icon and version info in assets/ are produced by tools/make_icon.py. They
are regenerated here if missing so a clean checkout still builds. Building on
a platform where that tool cannot run (a non-Windows host without a display)
falls back to an icon-less build rather than failing.

Build with:
    python -m PyInstaller covert_strike.spec --noconfirm --clean
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

import subprocess
import sys
from pathlib import Path

project_root = Path(SPECPATH)
assets = project_root / "assets"
icon_path = assets / "icon.ico"
version_path = assets / "version.txt"

# Generate the icon and version resource if they are not present yet.
if not icon_path.exists() or not version_path.exists():
    try:
        subprocess.check_call(
            [sys.executable, str(project_root / "tools" / "make_icon.py")])
    except Exception as exc:  # pragma: no cover - host dependent
        print(f"warning: could not generate assets ({exc}); building without icon")

# PyInstaller wants str paths, and only on platforms that support them.
exe_icon = str(icon_path) if icon_path.exists() else None
exe_version = str(version_path) if version_path.exists() else None

block_cipher = None

# numpy 2.x ships its own shared libraries and, when frozen, fails with
# "cannot load module more than once per process" unless those libraries are
# collected as binaries rather than left to the static import analysis. numpy
# 1.26.4 (pinned in requirements.txt) does not have the problem, but collecting
# the libraries explicitly keeps the bundle correct either way and is required
# on Windows for the OpenBLAS/MKL DLLs.
numpy_binaries = collect_dynamic_libs("numpy")

# Only exclude things that are genuinely unused. Cutting broader stdlib chunks
# (email, xml, secrets and friends) breaks transitive imports inside numpy, so
# the list stays deliberately small.
excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "lib2to3",
    "distutils", "setuptools", "pip", "PyInstaller",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=numpy_binaries,
    datas=[],
    hiddenimports=[
        # numpy's Cython extensions import these at runtime, which the static
        # analyser cannot see.
        "numpy.random", "numpy.random.bit_generator", "secrets", "hmac",
        "random", "hashlib", "base64",
        # Sub-packages are imported dynamically enough that PyInstaller's
        # static analysis can miss a couple of them.
        "src.audio.mixer",
        "src.audio.music",
        "src.audio.registry",
        "src.audio.sfx",
        "src.audio.synth",
        "src.engine.hud",
        "src.engine.particles",
        "src.engine.raycaster",
        "src.engine.sprites",
        "src.engine.textures",
        "src.game.enemies",
        "src.game.level",
        "src.game.mission",
        "src.game.objectives",
        "src.game.player",
        "src.game.security_cameras",
        "src.game.vehicles",
        "src.game.weapons",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CovertStrike",
    version=exe_version,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can trip some AV engines; size is fine without it.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # windowed game; nothing should pop up a console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)
