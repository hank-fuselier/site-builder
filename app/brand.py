"""Color extraction from scanned collateral, palette helpers, and simple text-logo (wordmark) generation."""
import colorsys
import html
from pathlib import Path

from PIL import Image

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

FONT_PAIRS = {
    "modern": {"label": "Modern (Inter / Inter)", "heading": "Inter", "body": "Inter"},
    "classic": {"label": "Classic (Playfair Display / Source Sans 3)", "heading": "Playfair Display", "body": "Source Sans 3"},
    "friendly": {"label": "Friendly (Poppins / Nunito)", "heading": "Poppins", "body": "Nunito"},
    "bold": {"label": "Bold (Oswald / Open Sans)", "heading": "Oswald", "body": "Open Sans"},
    "elegant": {"label": "Elegant (Cormorant Garamond / Lato)", "heading": "Cormorant Garamond", "body": "Lato"},
    "technical": {"label": "Technical (Space Grotesk / IBM Plex Sans)", "heading": "Space Grotesk", "body": "IBM Plex Sans"},
    "warm": {"label": "Warm (Merriweather / Work Sans)", "heading": "Merriweather", "body": "Work Sans"},
}

DEFAULT_BRAND = {
    "primary": "#1f4e79",
    "secondary": "#2e86ab",
    "accent": "#f2a541",
    "dark": "#1b1f24",
    "light": "#f7f8fa",
    "fonts": "modern",
    "logo_asset_id": None,
    "logo_svg": None,
}


def render_pdf_first_page(pdf_path: Path, out_path: Path) -> bool:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        page = pdf[0]
        img = page.render(scale=1.5).to_pil()
        img.convert("RGB").save(out_path, "PNG")
        return True
    except Exception:
        return False


def hex_of(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(max(0, min(255, v))) for v in rgb[:3]])


def rgb_of(hexstr: str):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def extract_colors(image_path: Path, count: int = 8) -> list[dict]:
    """Return dominant colors (most common first), skipping near-white paper and near-duplicates."""
    try:
        img = Image.open(image_path)
    except Exception:
        return []
    img = img.convert("RGBA")
    img.thumbnail((300, 300))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    q = img.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    out = []
    for c, idx in counts:
        rgb = tuple(pal[idx * 3 : idx * 3 + 3])
        h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in rgb])
        if l > 0.93 or c / total < 0.01:  # paper white, or anti-aliasing specks
            continue
        if any(_dist(rgb, rgb_of(o["hex"])) < 40 for o in out):
            continue
        out.append({"hex": hex_of(rgb), "share": round(c / total, 3), "saturation": round(s, 2), "lightness": round(l, 2)})
        if len(out) >= count:
            break
    return out


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def luminance(hexstr):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb_of(hexstr)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(bg: str) -> str:
    return "#ffffff" if contrast(bg, "#ffffff") >= contrast(bg, "#111111") else "#111111"


def shade(hexstr: str, factor: float) -> str:
    """factor < 1 darkens, > 1 lightens (in HLS lightness)."""
    r, g, b = [v / 255 for v in rgb_of(hexstr)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0, min(1, l * factor if factor < 1 else l + (1 - l) * (factor - 1)))
    return hex_of([v * 255 for v in colorsys.hls_to_rgb(h, l, s)])


def palette_from_extracted(colors: list[dict]) -> dict:
    """Pick a sensible primary/secondary/accent from extracted swatches."""
    if not colors:
        return {}
    vivid = sorted([c for c in colors if c["saturation"] > 0.25 and 0.15 < c["lightness"] < 0.8], key=lambda c: -c["share"])
    darks = [c for c in colors if c["lightness"] < 0.25]
    picks = {}
    if vivid:
        picks["primary"] = vivid[0]["hex"]
    if len(vivid) > 1:
        picks["secondary"] = vivid[1]["hex"]
    if len(vivid) > 2:
        picks["accent"] = vivid[2]["hex"]
    if darks:
        picks["dark"] = darks[0]["hex"]
    return picks


def theme_vars(brand: dict) -> dict:
    b = {**DEFAULT_BRAND, **{k: v for k, v in brand.items() if v}}
    fonts = FONT_PAIRS.get(b["fonts"], FONT_PAIRS["modern"])
    primary = b["primary"]
    # Make sure the primary is usable for links/buttons on a light background.
    link = primary if contrast(primary, b["light"]) >= 3 else shade(primary, 0.6)
    return {
        "primary": primary,
        "primary_dark": shade(primary, 0.75),
        "primary_text": text_on(primary),
        "secondary": b["secondary"],
        "secondary_text": text_on(b["secondary"]),
        "accent": b["accent"],
        "accent_text": text_on(b["accent"]),
        "dark": b["dark"],
        "light": b["light"],
        "link": link,
        "tint": shade(primary, 1.88),
        "heading_font": fonts["heading"],
        "body_font": fonts["body"],
    }


def google_fonts_url(brand: dict) -> str:
    fonts = FONT_PAIRS.get(brand.get("fonts") or "modern", FONT_PAIRS["modern"])
    fams = []
    for f in dict.fromkeys([fonts["heading"], fonts["body"]]):
        fams.append("family=" + f.replace(" ", "+") + ":wght@400;600;700")
    return "https://fonts.googleapis.com/css2?" + "&".join(fams) + "&display=swap"


ICONS = {
    "none": "",
    "circle": '<circle cx="28" cy="32" r="20" fill="{c1}"/><circle cx="28" cy="32" r="9" fill="{c2}"/>',
    "leaf": '<path d="M10 50 C10 20 30 10 50 10 C50 34 38 52 10 50 Z" fill="{c1}"/><path d="M12 48 L40 20" stroke="{c2}" stroke-width="3"/>',
    "house": '<path d="M6 32 L28 12 L50 32 L50 54 L6 54 Z" fill="{c1}"/><rect x="22" y="38" width="12" height="16" fill="{c2}"/>',
    "drop": '<path d="M28 6 C28 6 8 30 8 40 A20 20 0 0 0 48 40 C48 30 28 6 28 6 Z" fill="{c1}"/>',
    "star": '<path d="M28 6 L34 24 L52 24 L38 35 L43 53 L28 42 L13 53 L18 35 L4 24 L22 24 Z" fill="{c1}"/>',
    "shield": '<path d="M28 6 L50 14 V30 C50 44 40 52 28 58 C16 52 6 44 6 30 V14 Z" fill="{c1}"/><path d="M18 31 L26 39 L40 23" stroke="{c2}" stroke-width="5" fill="none"/>',
    "bolt": '<path d="M32 4 L10 36 H26 L22 60 L46 26 H30 Z" fill="{c1}"/>',
    "monogram": '<rect x="4" y="8" width="48" height="48" rx="12" fill="{c1}"/><text x="28" y="44" font-size="30" text-anchor="middle" font-family="{font}" font-weight="700" fill="{c2}">{initial}</text>',
}


def wordmark_svg(name: str, tagline: str, primary: str, secondary: str, font: str, icon: str = "monogram") -> str:
    """A clean, scalable text logo for customers who have none."""
    name_e = html.escape(name)
    tag_e = html.escape(tagline or "")
    shape = ICONS.get(icon, "")
    has_icon = bool(shape)
    x = 64 if has_icon else 4
    width = x + max(len(name) * 17, len(tagline or "") * 8) + 16
    shape = shape.format(c1=primary, c2=text_on(primary) if icon == "monogram" else secondary,
                         font=html.escape(font), initial=html.escape(name[:1].upper()))
    tag = (f'<text x="{x}" y="52" font-family="{html.escape(font)}, sans-serif" font-size="13" '
           f'letter-spacing="1.5" fill="{secondary}">{tag_e.upper()}</text>') if tagline else ""
    ny = 34 if tagline else 42
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 64" height="64" role="img" aria-label="{name_e}">'
        f"{shape}"
        f'<text x="{x}" y="{ny}" font-family="{html.escape(font)}, sans-serif" font-size="28" font-weight="700" fill="{primary}">{name_e}</text>'
        f"{tag}</svg>"
    )
