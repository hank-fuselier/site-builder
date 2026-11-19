"""Turns a customer's site JSON + brand into HTML pages (served live, or exported as static files)."""
import html
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import brand as brandlib
from .settings import BUILDER_NAME

env = Environment(loader=FileSystemLoader(str(__import__("pathlib").Path(__file__).parent / "templates")),
                  autoescape=select_autoescape(["html"]))


def paragraphs(text: str) -> Markup:
    if not text:
        return Markup("")
    out = []
    for p in re.split(r"\n\s*\n", text.strip()):
        p = html.escape(p.strip()).replace("\n", "<br>")
        p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        out.append(f"<p>{p}</p>")
    return Markup("\n".join(out))


env.filters["paras"] = paragraphs


def tel(s: str) -> str:
    return re.sub(r"[^0-9+]", "", s or "")


env.filters["tel"] = tel


def find_page(site: dict, slug: str):
    for p in site.get("pages", []):
        if p.get("slug") == slug:
            return p
    return None


def render_page(customer: dict, page_slug: str, *, mode: str = "live", base: str = "/",
                asset_url=None, message: str = "") -> str | None:
    """mode: live (served by app), export (static files with relative links)."""
    site = customer.get("site")
    if not site:
        return None
    page = find_page(site, page_slug or "home")
    if page is None:
        return None
    b = customer.get("brand") or {}

    def page_url(slug):
        if not slug:
            return None
        if mode == "export":
            return "index.html" if slug == "home" else f"{slug}.html"
        return base if slug == "home" else f"{base}{slug}"

    if asset_url is None:
        asset_url = lambda aid: f"/assets/{aid}"  # noqa: E731

    logo_html = None
    if b.get("logo_asset_id"):
        logo_html = Markup(f'<img src="{asset_url(b["logo_asset_id"])}" alt="{html.escape(site.get("business_name", ""))} logo">')
    elif b.get("logo_svg"):
        logo_html = Markup(b["logo_svg"])

    tpl = env.get_template("site/page.html")
    return tpl.render(
        site=site, page=page, theme=brandlib.theme_vars(b), fonts_url=brandlib.google_fonts_url(b),
        page_url=page_url, asset_url=asset_url, logo_html=logo_html, mode=mode, base=base,
        form_action=(f"{base}contact-submit" if mode == "live" else None),
        message=message, builder_name=BUILDER_NAME, customer=customer,
    )
