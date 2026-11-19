"""Claude-powered steps: read collateral, suggest brands and domains, and write the site content."""
import base64
import io
import json
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel

from . import settings

_client = None


def client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _parse(system: str, content, schema, effort: str = "medium", max_tokens: int = 16000):
    resp = client().beta.messages.parse(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("The response was cut off (too long). Try asking for fewer pages.")
    if resp.parsed_output is None:
        raise RuntimeError("Claude did not return usable output.")
    return resp.parsed_output


def _image_block(path: Path):
    img = Image.open(path)
    img = img.convert("RGB")
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buf.getvalue()).decode()}}


def _pdf_block(path: Path):
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(path.read_bytes()).decode()}}


# ---------- Collateral analysis ----------

class CollateralFindings(BaseModel):
    business_name: str
    tagline: str
    industry: str
    services: list[str]
    phone: str
    email: str
    address: str
    hours: str
    website_or_socials: list[str]
    selling_points: list[str]
    brand_colors_seen: list[str]
    style_notes: str
    logo_description: str
    other_text_worth_using: str


def analyze_collateral(files: list[tuple[Path, str]], interview: dict) -> dict:
    content = []
    for path, kind in files[:12]:
        content.append(_pdf_block(path) if kind == "pdf" else _image_block(path))
    content.append({"type": "text", "text": (
        "These are scans of a small business's marketing collateral (flyers, cards, brochures, signage). "
        "Extract everything useful for building their website. Use an empty string or empty list when "
        "something is not shown; never invent contact details. brand_colors_seen are hex codes of the "
        "brand colors you can see (not paper or photo colors). style_notes describe the visual style "
        "(e.g. rustic, clinical, playful) in one or two sentences.\n\nInterview notes so far:\n"
        + json.dumps(interview, indent=1))})
    return _parse("You read marketing materials carefully and accurately.", content, CollateralFindings).model_dump()


# ---------- Brand suggestions ----------

FontKey = Literal["modern", "classic", "friendly", "bold", "elegant", "technical", "warm"]
IconKey = Literal["none", "circle", "leaf", "house", "drop", "star", "shield", "bolt", "monogram"]


class PaletteOption(BaseModel):
    name: str
    rationale: str
    primary: str
    secondary: str
    accent: str
    dark: str
    light: str
    fonts: FontKey


class LogoConcept(BaseModel):
    display_name: str
    tagline: str
    icon: IconKey
    rationale: str


class BrandSuggestions(BaseModel):
    palettes: list[PaletteOption]
    logo_concepts: list[LogoConcept]


def suggest_brand(interview: dict, findings: dict, extracted_colors: list[str]) -> dict:
    text = (
        "Suggest a brand direction for this small business's new website.\n"
        "Return exactly 3 palette options and 3 logo concepts.\n"
        "Palettes: hex codes; primary must have at least 4.5:1 contrast with white text; light is a near-white "
        "page background; dark is a near-black text color. If the business already uses colors (listed below), "
        "make the first option a refined version of their existing colors.\n"
        "Logo concepts are simple wordmarks: a display name (short), an optional short tagline (max 5 words), "
        "and an icon from the allowed list that fits the trade.\n\n"
        f"Interview:\n{json.dumps(interview, indent=1)}\n\n"
        f"Collateral findings:\n{json.dumps(findings or {}, indent=1)}\n\n"
        f"Colors extracted from their scans: {', '.join(extracted_colors) or 'none'}"
    )
    return _parse("You are a brand designer for small local businesses.", [{"type": "text", "text": text}],
                  BrandSuggestions).model_dump()


# ---------- Domain suggestions ----------

class DomainIdeas(BaseModel):
    domains: list[str]


def suggest_domains(interview: dict, findings: dict) -> list[str]:
    text = (
        "Suggest 24 domain names for this small business. Mix .com (at least half), plus fitting options like "
        ".net, .co, .biz, .pro, .us or industry TLDs (.law, .dental, .plumbing, .salon etc. when they fit). "
        "Prefer short, easy to spell and say aloud, no hyphens unless needed, include the town or trade "
        "where it helps. Lowercase, no protocol, no www.\n\n"
        f"Interview:\n{json.dumps(interview, indent=1)}\n\nCollateral findings:\n{json.dumps(findings or {}, indent=1)}"
    )
    out = _parse("You name small businesses' websites.", [{"type": "text", "text": text}], DomainIdeas, effort="low")
    return out.domains


# ---------- Site generation ----------

SectionType = Literal["hero", "text", "features", "services", "stats", "testimonials", "faq",
                      "gallery", "team", "cta", "contact", "hours"]


class Item(BaseModel):
    title: str
    text: str
    icon: str  # a single emoji, or empty
    detail: str  # price, role, stat value, or empty
    image_asset_id: int  # 0 when none


class Section(BaseModel):
    type: SectionType
    heading: str
    subheading: str
    body: str  # paragraphs separated by blank lines
    items: list[Item]
    cta_label: str
    cta_page: str  # slug of a page in this site, or empty
    image_asset_id: int  # 0 when none


class Page(BaseModel):
    slug: str  # "home" for the homepage
    nav_label: str
    title: str
    meta_description: str
    sections: list[Section]


class ContactInfo(BaseModel):
    phone: str
    email: str
    address: str
    hours: list[str]
    service_area: str
    social_links: list[str]


class Site(BaseModel):
    business_name: str
    tagline: str
    contact: ContactInfo
    pages: list[Page]
    footer_blurb: str


SITE_SYSTEM = """You write complete, ready-to-publish small-business websites as structured content.
Rules:
- Write real, specific, warm copy in the customer's voice. No lorem ipsum, no "[Your text here]" except where noted below.
- Never invent facts that a customer would be embarrassed by: licenses, awards, years in business, prices, certifications,
  or customer reviews. If testimonials are wanted but none were provided, add a testimonials section whose items say
  "Customer testimonial coming soon" so the builder can fill them in, or leave that section out.
- Only use contact details that were provided. Leave fields empty otherwise.
- The first page must have slug "home". Other slugs are short lowercase words with hyphens (about, services, contact...).
- Every page should have 3-7 sections. The home page starts with a hero. Include a contact page with a contact section
  (the site renders a working form there).
- cta_page must be one of the site's page slugs (or empty).
- image_asset_id may only reference the asset ids listed as available images; otherwise 0.
- icon is one emoji that fits, or empty."""


def generate_site(interview: dict, brand: dict, findings: dict, image_assets: list[dict],
                  current_site: dict | None, instructions: str) -> dict:
    parts = [
        f"Interview with the business owner:\n{json.dumps(interview, indent=1)}",
        f"Facts read from their marketing collateral:\n{json.dumps(findings or {}, indent=1)}",
        f"Brand: {json.dumps({k: brand.get(k) for k in ('primary', 'secondary', 'accent', 'fonts')})}",
        "Available images (asset id: file name): " + (", ".join(f"{a['id']}: {a['original_name']}" for a in image_assets) or "none"),
    ]
    if current_site:
        parts.append("Current version of the site (revise it rather than starting over):\n" + json.dumps(current_site))
    if instructions:
        parts.append("Builder's instructions for this version:\n" + instructions)
    else:
        parts.append("Write the full website now.")
    site = _parse(SITE_SYSTEM, [{"type": "text", "text": "\n\n".join(parts)}], Site, effort="medium", max_tokens=20000)
    return site.model_dump()
