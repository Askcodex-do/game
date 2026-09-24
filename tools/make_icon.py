"""Generate the application icon and Windows version resource.

The icon is generated rather than checked in as a binary blob, which keeps the
repository free of opaque assets and means the artwork is reviewable as code.
Running this produces:

    assets/icon.ico    - multi-resolution Windows icon (16..256 px)
    assets/version.txt - PyInstaller version-resource definition

Both are consumed by covert_strike.spec.
"""

import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")

# --------------------------------------------------------------------- art --

def _smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def render_icon(size):
    """Render one square frame of the icon at the given pixel size.

    The motif is a rifle scope reticle over a dark night sky, which reads
    clearly even down at 16x16 where a literal logo would turn to mush.
    """
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = cy = (size - 1) / 2.0
    # Normalised radius, 1.0 at the edge of the circle.
    radius = 0.465 * size
    dx = xx - cx
    dy = yy - cy
    dist = np.sqrt(dx * dx + dy * dy)
    r = dist / radius

    # Start from a vertical night gradient inside the round bezel.
    v = (yy / max(1.0, size - 1.0))
    bg = np.zeros((size, size, 3), np.float32)
    bg[..., 0] = 12 + 26 * v      # dusk sky top -> slightly warmer bottom
    bg[..., 1] = 20 + 34 * v
    bg[..., 2] = 30 + 46 * v

    # A few stars, deterministic per size so every render is identical.
    rng = np.random.default_rng(20240924)
    stars = np.zeros((size, size), np.float32)
    for _ in range(max(6, size // 3)):
        sx = int(rng.integers(0, size))
        sy = int(rng.integers(0, size))
        if (sx - cx) ** 2 + (sy - cy) ** 2 < (radius * 0.9) ** 2:
            stars[sy, sx] = 1.0
    stars = _smoothstep(0.35, 1.0, stars)
    bg += stars[..., None] * 130.0

    # Reticle: bright ring plus four ticks and a centre dot.
    ring = _smoothstep(0.0, 1.0, 1.0 - np.abs(r - 0.62) / 0.075) * 1.35
    cross = (np.abs(dx) < size * 0.012) & (dist < radius * 0.92)
    cross |= (np.abs(dy) < size * 0.012) & (dist < radius * 0.92)
    # Break the crosshair in the middle so the centre dot stands alone.
    cross &= dist > size * 0.09
    tick = np.zeros((size, size), np.float32)
    tick[cross] = 1.0
    dot = _smoothstep(0.0, 1.0, 1.0 - dist / (size * 0.045))

    cyan = np.array([120, 226, 236], np.float32)
    amber = np.array([240, 190, 96], np.float32)

    img = bg.copy()
    img += ring[..., None] * cyan * 0.85
    img += tick[..., None] * amber * 0.95
    img += dot[..., None] * amber * 1.1

    # Round bezel: everything outside the circle fades to transparent.
    edge = _smoothstep(0.965, 1.0, r)
    body = 1.0 - edge
    # Dark bezel rim.
    rim = _smoothstep(0.0, 1.0, 1.0 - np.abs(r - 0.94) / 0.06)
    img = img * (1.0 - rim[..., None] * 0.75) + np.array([28, 34, 42], np.float32) * (rim[..., None] * 0.75)

    alpha = np.clip(body * 255.0, 0, 255)
    return np.clip(img, 0, 255).astype(np.uint8), alpha.astype(np.uint8)


# --------------------------------------------------------------------- ico --

def _bmp_bytes(rgb, alpha, size):
    """Encode one icon frame as a 32-bit BGRA DIB (ICO's "BMP" format).

    Includes the doubled height, the AND mask and the bottom-up row order that
    the ICO container requires. Getting this wrong produces an icon Windows
    silently ignores, so it is spelled out explicitly.
    """
    header = struct.pack("<IiiHHIIiiII",
                         40,          # biSize
                         size,        # biWidth
                         size * 2,    # biHeight: colour + mask
                         1,           # biPlanes
                         32,          # biBitCount
                         0,           # biCompression = BI_RGB
                         size * size * 4,  # biSizeImage
                         0, 0, 0, 0)
    # Bottom-up BGRA.
    bgra = np.empty((size, size, 4), np.uint8)
    bgra[..., 0] = rgb[..., 2]
    bgra[..., 1] = rgb[..., 1]
    bgra[..., 2] = rgb[..., 0]
    bgra[..., 3] = alpha
    pixels = bgra[::-1].tobytes()
    # AND mask: 1 bit per pixel, rows padded to 4 bytes. Zero alpha => bit set.
    mask_row_bytes = ((size + 31) // 32) * 4
    mask = bytearray()
    opaque = alpha >= 128
    for row in range(size - 1, -1, -1):
        bits = bytearray(mask_row_bytes)
        for col in range(size):
            if not opaque[row, col]:
                bits[col // 8] |= 0x80 >> (col % 8)
        mask += bits
    return header + pixels + bytes(mask)


def write_ico(path, sizes=(16, 32, 48, 64, 128, 256)):
    frames = []
    for size in sizes:
        rgb, alpha = render_icon(size)
        frames.append((size, _bmp_bytes(rgb, alpha, size)))

    out = struct.pack("<HHH", 0, 1, len(frames))  # reserved, type=icon, count
    offset = 6 + 16 * len(frames)
    directory = b""
    for size, data in frames:
        dim = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(out + directory + b"".join(d for _, d in frames))


# --------------------------------------------------------------- version ----

VERSION_RC = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Covert Strike'),
        StringStruct('FileDescription', 'Covert Strike: Stage One'),
        StringStruct('FileVersion', '1.0.0.0'),
        StringStruct('InternalName', 'CovertStrike'),
        StringStruct('LegalCopyright', 'Original work. No third-party assets.'),
        StringStruct('OriginalFilename', 'CovertStrike.exe'),
        StringStruct('ProductName', 'Covert Strike: Stage One'),
        StringStruct('ProductVersion', '1.0.0.0')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    os.makedirs(ASSETS, exist_ok=True)
    ico = os.path.join(ASSETS, "icon.ico")
    write_ico(ico)
    ver = os.path.join(ASSETS, "version.txt")
    with open(ver, "w", newline="\n") as fh:
        fh.write(VERSION_RC)
    print(f"wrote {ico} ({os.path.getsize(ico)} bytes)")
    print(f"wrote {ver}")


if __name__ == "__main__":
    main()
