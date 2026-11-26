"""Generates macOS-shaped (transparent rounded corners) assets/app_icon.png and assets/SoulsLights.icns."""
import io
import os
import struct
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO_PATH = os.path.join(ROOT, "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
PNG_PATH = os.path.join(ASSETS_DIR, "app_icon.png")
ICNS_PATH = os.path.join(ASSETS_DIR, "SoulsLights.icns")


def _apply_macos_icon_mask(src_rgba: Image.Image, size: int = 1024) -> Image.Image:
    """Applies macOS rounded-corner Dock shape (~9% margin, ~22% corner radius) at 2x supersampling."""
    base = src_rgba.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    pad = int(round(size * 0.085))
    inner = size - 2 * pad
    resized_inner = base.resize((inner, inner), Image.Resampling.LANCZOS)

    sc = 2
    mask_2x = Image.new("L", (inner * sc, inner * sc), 0)
    rad = int(round(inner * 0.22 * sc))
    ImageDraw.Draw(mask_2x).rounded_rectangle(
        [0, 0, inner * sc - 1, inner * sc - 1], radius=rad, fill=255
    )
    mask = mask_2x.resize((inner, inner), Image.Resampling.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(resized_inner, (pad, pad), mask)
    return out


def build_icns_from_rgba(src_img: Image.Image, out_icns: str):
    chunks = []
    specs = (
        (b"icp4", 16),
        (b"icp5", 32),
        (b"ic11", 32),
        (b"ic12", 64),
        (b"ic07", 128),
        (b"ic13", 256),
        (b"ic08", 256),
        (b"ic14", 512),
        (b"ic09", 512),
        (b"ic10", 1024),
    )
    for tag, px in specs:
        im = src_img.resize((px, px), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        chunks.append(tag + struct.pack(">I", 8 + len(data)) + data)

    body = b"".join(chunks)
    header = b"icns" + struct.pack(">I", 8 + len(body))
    with open(out_icns, "wb") as f:
        f.write(header + body)


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    ico = Image.open(ICO_PATH)
    best = ico.convert("RGBA")
    if hasattr(ico, "n_frames") and ico.n_frames > 1:
        best_area = best.width * best.height
        for idx in range(ico.n_frames):
            ico.seek(idx)
            fr = ico.convert("RGBA")
            if fr.width * fr.height > best_area:
                best = fr
                best_area = fr.width * fr.height

    mac_1024 = _apply_macos_icon_mask(best, 1024)
    png_512 = mac_1024.resize((512, 512), Image.Resampling.LANCZOS)
    png_512.save(PNG_PATH, format="PNG")
    build_icns_from_rgba(mac_1024, ICNS_PATH)
    print(f"Generated PNG ({os.path.getsize(PNG_PATH)} bytes): {PNG_PATH}")
    print(f"Generated ICNS ({os.path.getsize(ICNS_PATH)} bytes): {ICNS_PATH}")


if __name__ == "__main__":
    main()
