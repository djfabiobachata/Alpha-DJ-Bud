"""Draws the Alpha DJ Bud icon (PNG + macOS .icns)."""
import io, math, struct, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1024
CAM = ["#3ff2c0", "#6ff57b", "#a6f25a", "#e5e05a", "#ffb35a", "#ff8a6b",
       "#ff6f9e", "#f07fdc", "#c48bff", "#9aa6ff", "#6fc6ff", "#4fe6f0"]

def icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # rounded-square body with vertical gradient
    body = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(body)
    for y in range(S):
        t = y / S
        c = (int(36 - 22 * t), int(26 - 18 * t), int(52 - 36 * t), 255)
        d.line([(0, y), (S, y)], fill=c)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([60, 60, S - 60, S - 60], radius=200, fill=255)
    img.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # purple rim
    d.rounded_rectangle([60, 60, S - 60, S - 60], radius=200, outline="#5b2d9e", width=14)
    cx = cy = S // 2
    # Camelot ring
    r_out, r_in = 380, 290
    for i in range(12):
        a0 = -90 - 15 + i * 30 + 1.5
        a1 = a0 + 27
        d.pieslice([cx - r_out, cy - r_out, cx + r_out, cy + r_out], a0, a1, fill=CAM[i])
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill="#0b0a10")
    # inner purple ring + green glow core
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - 250, cy - 250, cx + 250, cy + 250], outline=(155, 92, 255, 255), width=18)
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(glow)
    d.ellipse([cx - 250, cy - 250, cx + 250, cy + 250], outline="#9b5cff", width=10)
    # alpha letter
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", 360)
    txt = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    td.text((cx, cy - 10), "α", font=font, fill=(61, 255, 143, 255), anchor="mm")
    halo = txt.filter(ImageFilter.GaussianBlur(22))
    img.alpha_composite(halo)
    img.alpha_composite(txt)
    return img

def icns(img, path):
    chunks = b""
    for typ, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        buf = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(buf, "PNG")
        data = buf.getvalue()
        chunks += typ + struct.pack(">I", len(data) + 8) + data
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "assets"
    im = icon()
    im.save(f"{out}/icon.png")
    im.resize((256, 256), Image.LANCZOS).save(f"{out}/icon-256.png")
    icns(im, f"{out}/AppIcon.icns")
