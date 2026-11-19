import io
import json
import secrets
import threading
import traceback
import uuid
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from . import ai, db, domains, render
from . import brand as brandlib
from . import settings

app = FastAPI(title="Site Builder", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
security = HTTPBasic()
db.init()

JOBS: dict[int, dict] = {}  # customer id -> {"kind", "status", "error"}


def admin(creds: HTTPBasicCredentials = Depends(security)):
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(503, "Set ADMIN_PASSWORD in the environment before using the admin area.")
    ok = secrets.compare_digest(creds.username, settings.ADMIN_USER) and secrets.compare_digest(
        creds.password, settings.ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return creds.username


def tpl(name, request, **ctx):
    t = render.env.get_template(f"admin/{name}")
    return HTMLResponse(t.render(request=request, ai_enabled=settings.AI_ENABLED, base_url=settings.PUBLIC_BASE_URL, **ctx))


def must_customer(cid):
    c = db.get_customer(cid)
    if not c:
        raise HTTPException(404)
    return c


def back(cid, anchor=""):
    return RedirectResponse(f"/admin/c/{cid}{'#' + anchor if anchor else ''}", status_code=303)


def run_job(cid: int, kind: str, fn):
    if JOBS.get(cid, {}).get("status") == "running":
        return

    def work():
        try:
            fn()
            JOBS[cid] = {"kind": kind, "status": "done", "error": ""}
        except Exception as e:  # surface the error to the admin page
            traceback.print_exc()
            JOBS[cid] = {"kind": kind, "status": "error", "error": str(e)[:500]}

    JOBS[cid] = {"kind": kind, "status": "running", "error": ""}
    threading.Thread(target=work, daemon=True).start()


def preview_url(c):
    return f"{settings.PUBLIC_BASE_URL}/s/{c['slug']}/"


render.env.globals["preview_url"] = preview_url
render.env.globals["font_pairs"] = brandlib.FONT_PAIRS
render.env.globals["icons"] = list(brandlib.ICONS)


# ---------------- Admin ----------------

@app.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(admin)):
    return tpl("dashboard.html", request, customers=db.list_customers())


@app.post("/admin/new")
def new_customer(name: str = Form(...), user=Depends(admin)):
    c = db.create_customer(name.strip(), {"business_name": name.strip()})
    db.update_customer(c["id"], brand=dict(brandlib.DEFAULT_BRAND))
    return back(c["id"], "interview")


INTERVIEW_FIELDS = [
    ("business_name", "Business name", "input"), ("owner_name", "Owner / contact person", "input"),
    ("industry", "Industry / trade", "input"), ("location", "City / location", "input"),
    ("service_area", "Service area", "input"),
    ("description", "What does the business do? (in the owner's words)", "textarea"),
    ("services", "Services or products (one per line, prices if they want them shown)", "textarea"),
    ("audience", "Ideal customers", "textarea"),
    ("differentiators", "Why choose them? (experience, guarantees, story)", "textarea"),
    ("tone", "Tone (e.g. friendly, premium, no-nonsense)", "input"),
    ("pages_wanted", "Pages wanted (e.g. Home, About, Services, Gallery, FAQ, Contact)", "input"),
    ("testimonials", "Real customer testimonials (with names if allowed)", "textarea"),
    ("phone", "Phone", "input"), ("email", "Email", "input"), ("address", "Address", "input"),
    ("hours", "Hours", "textarea"), ("socials", "Social media links", "textarea"),
    ("existing_domain", "Domain they already own (blank if none)", "input"),
    ("colors_pref", "Color likes / dislikes", "input"),
    ("sites_liked", "Websites they like", "textarea"),
    ("notes", "Other notes", "textarea"),
]
render.env.globals["interview_fields"] = INTERVIEW_FIELDS


@app.get("/admin/c/{cid}", response_class=HTMLResponse)
def customer_page(cid: int, request: Request, user=Depends(admin)):
    c = must_customer(cid)
    assets = db.list_assets(cid)
    all_colors = []
    for a in assets:
        for col in a["colors"]:
            if col["hex"] not in [x["hex"] for x in all_colors]:
                all_colors.append(col)
    sugg = c["suggestions"] or {}
    logo_previews = []
    for lc in (sugg.get("brand") or {}).get("logo_concepts", []):
        b = c["brand"] or {}
        font = brandlib.FONT_PAIRS.get(b.get("fonts") or "modern")["heading"]
        logo_previews.append(brandlib.wordmark_svg(lc["display_name"], lc["tagline"], b.get("primary", "#1f4e79"),
                                                   b.get("secondary", "#2e86ab"), font, lc["icon"]))
    return tpl("customer.html", request, c=c, assets=assets, colors=all_colors, sugg=sugg,
               logo_previews=logo_previews, job=JOBS.get(cid), versions=db.list_versions(cid),
               leads=db.list_leads(cid), site_json=json.dumps(c["site"], indent=2) if c["site"] else "",
               theme=brandlib.theme_vars(c["brand"] or {}))


@app.get("/admin/c/{cid}/job")
def job_status(cid: int, user=Depends(admin)):
    return JSONResponse(JOBS.get(cid) or {})


@app.post("/admin/c/{cid}/interview")
async def save_interview(cid: int, request: Request, user=Depends(admin)):
    c = must_customer(cid)
    form = await request.form()
    interview = {k: (form.get(k) or "").strip() for k, _, _ in INTERVIEW_FIELDS}
    fields = {"interview": interview}
    if interview["business_name"]:
        fields["name"] = interview["business_name"]
    dom = db.normalize_domain(interview["existing_domain"])
    if dom:
        fields["domain"] = dom
    db.update_customer(cid, **fields)
    return back(cid, "collateral")


@app.post("/admin/c/{cid}/upload")
async def upload(cid: int, files: list[UploadFile] = File(...), user=Depends(admin)):
    must_customer(cid)
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in brandlib.IMAGE_EXT | {".pdf", ".svg"}:
            continue
        stored = f"{cid}_{uuid.uuid4().hex[:10]}{ext}"
        dest = settings.UPLOAD_DIR / stored
        dest.write_bytes(await f.read())
        colors, kind = [], "image"
        if ext == ".pdf":
            kind = "pdf"
            png = dest.with_suffix(".preview.png")
            if brandlib.render_pdf_first_page(dest, png):
                colors = brandlib.extract_colors(png)
        elif ext == ".svg":
            kind = "svg"
        else:
            colors = brandlib.extract_colors(dest)
        db.add_asset(cid, stored, f.filename or stored, kind, colors)
    return back(cid, "collateral")


@app.post("/admin/c/{cid}/asset/{aid}/delete")
def delete_asset(cid: int, aid: int, user=Depends(admin)):
    a = db.get_asset(aid)
    if a and a["customer_id"] == cid:
        for p in (settings.UPLOAD_DIR / a["filename"], (settings.UPLOAD_DIR / a["filename"]).with_suffix(".preview.png")):
            p.unlink(missing_ok=True)
        db.delete_asset(aid)
    return back(cid, "collateral")


def _image_assets(cid):
    return [a for a in db.list_assets(cid) if a["kind"] in ("image", "svg")]


@app.post("/admin/c/{cid}/analyze")
def analyze(cid: int, user=Depends(admin)):
    c = must_customer(cid)

    def work():
        files = [(settings.UPLOAD_DIR / a["filename"], a["kind"]) for a in db.list_assets(cid) if a["kind"] in ("image", "pdf")]
        if not files:
            raise RuntimeError("Upload some collateral scans first.")
        findings = ai.analyze_collateral(files, c["interview"])
        s = db.get_customer(cid)["suggestions"] or {}
        s["findings"] = findings
        # Fill blank interview fields from what was read off the collateral.
        iv = dict(db.get_customer(cid)["interview"])
        for key, fkey in [("business_name", "business_name"), ("phone", "phone"), ("email", "email"),
                          ("address", "address"), ("hours", "hours"), ("industry", "industry")]:
            if not iv.get(key) and findings.get(fkey):
                iv[key] = findings[fkey]
        if not iv.get("services") and findings.get("services"):
            iv["services"] = "\n".join(findings["services"])
        db.update_customer(cid, suggestions=s, interview=iv)

    run_job(cid, "Reading collateral", work)
    return back(cid, "collateral")


@app.post("/admin/c/{cid}/brand")
async def save_brand(cid: int, request: Request, user=Depends(admin)):
    c = must_customer(cid)
    form = await request.form()
    b = dict(c["brand"] or brandlib.DEFAULT_BRAND)
    for k in ("primary", "secondary", "accent", "dark", "light", "fonts"):
        if form.get(k):
            b[k] = form.get(k)
    logo = form.get("logo_asset_id")
    if logo is not None:
        b["logo_asset_id"] = int(logo) if logo and logo != "0" else None
    db.update_customer(cid, brand=b)
    return back(cid, "brand")


@app.post("/admin/c/{cid}/brand/from-scans")
def brand_from_scans(cid: int, user=Depends(admin)):
    c = must_customer(cid)
    colors = []
    for a in db.list_assets(cid):
        colors += a["colors"]
    colors.sort(key=lambda x: -x["share"])
    picks = brandlib.palette_from_extracted(colors)
    db.update_customer(cid, brand={**(c["brand"] or {}), **picks})
    return back(cid, "brand")


@app.post("/admin/c/{cid}/brand/suggest")
def brand_suggest(cid: int, user=Depends(admin)):
    c = must_customer(cid)

    def work():
        colors = [col["hex"] for a in db.list_assets(cid) for col in a["colors"]][:12]
        s = db.get_customer(cid)["suggestions"] or {}
        s["brand"] = ai.suggest_brand(c["interview"], s.get("findings"), colors)
        db.update_customer(cid, suggestions=s)

    run_job(cid, "Suggesting colors and logos", work)
    return back(cid, "brand")


@app.post("/admin/c/{cid}/brand/palette/{i}")
def apply_palette(cid: int, i: int, user=Depends(admin)):
    c = must_customer(cid)
    p = c["suggestions"]["brand"]["palettes"][i]
    b = {**(c["brand"] or {}), **{k: p[k] for k in ("primary", "secondary", "accent", "dark", "light", "fonts")}}
    db.update_customer(cid, brand=b)
    return back(cid, "brand")


@app.post("/admin/c/{cid}/brand/logo/{i}")
def apply_logo(cid: int, i: int, user=Depends(admin)):
    c = must_customer(cid)
    lc = c["suggestions"]["brand"]["logo_concepts"][i]
    b = dict(c["brand"] or {})
    font = brandlib.FONT_PAIRS.get(b.get("fonts") or "modern")["heading"]
    b["logo_svg"] = brandlib.wordmark_svg(lc["display_name"], lc["tagline"], b.get("primary", "#1f4e79"),
                                          b.get("secondary", "#2e86ab"), font, lc["icon"])
    b["logo_asset_id"] = None
    db.update_customer(cid, brand=b)
    return back(cid, "brand")


@app.post("/admin/c/{cid}/brand/logo-text")
def custom_logo(cid: int, name: str = Form(...), tagline: str = Form(""), icon: str = Form("monogram"),
                user=Depends(admin)):
    c = must_customer(cid)
    b = dict(c["brand"] or {})
    font = brandlib.FONT_PAIRS.get(b.get("fonts") or "modern")["heading"]
    b["logo_svg"] = brandlib.wordmark_svg(name, tagline, b.get("primary", "#1f4e79"), b.get("secondary", "#2e86ab"), font, icon)
    b["logo_asset_id"] = None
    db.update_customer(cid, brand=b)
    return back(cid, "brand")


@app.post("/admin/c/{cid}/domains/suggest")
def domains_suggest(cid: int, user=Depends(admin)):
    c = must_customer(cid)

    def work():
        import asyncio
        s = db.get_customer(cid)["suggestions"] or {}
        names = ai.suggest_domains(c["interview"], s.get("findings"))
        s["domains"] = asyncio.run(domains.check_many(names))
        db.update_customer(cid, suggestions=s)

    run_job(cid, "Finding available domain names", work)
    return back(cid, "domain")


@app.post("/admin/c/{cid}/domains/check")
async def domains_check(cid: int, names: str = Form(...), user=Depends(admin)):
    c = must_customer(cid)
    res = await domains.check_many(names.replace(",", "\n").splitlines())
    s = c["suggestions"] or {}
    s["domains"] = res + [d for d in s.get("domains", []) if d["domain"] not in {r["domain"] for r in res}]
    db.update_customer(cid, suggestions=s)
    return back(cid, "domain")


@app.post("/admin/c/{cid}/domain")
def set_domain(cid: int, domain: str = Form(""), user=Depends(admin)):
    must_customer(cid)
    d = db.normalize_domain(domain)
    other = db.get_customer_by_domain(d) if d else None
    if other and other["id"] != cid:
        raise HTTPException(400, f"{d} is already assigned to {other['name']}.")
    db.update_customer(cid, domain=d)
    return back(cid, "domain")


@app.post("/admin/c/{cid}/generate")
def generate(cid: int, instructions: str = Form(""), fresh: str = Form(""), user=Depends(admin)):
    c = must_customer(cid)

    def work():
        cur = db.get_customer(cid)
        site = ai.generate_site(cur["interview"], cur["brand"] or {}, (cur["suggestions"] or {}).get("findings"),
                                _image_assets(cid), None if fresh else cur["site"], instructions.strip())
        db.update_customer(cid, site=site)
        db.save_version(cid, site, instructions.strip()[:200] or ("Fresh draft" if fresh or not cur["site"] else "Revision"))

    run_job(cid, "Writing the website", work)
    return back(cid, "site")


@app.post("/admin/c/{cid}/site-json")
def save_site_json(cid: int, site_json: str = Form(...), user=Depends(admin)):
    must_customer(cid)
    try:
        site = ai.Site.model_validate_json(site_json).model_dump()
    except Exception as e:
        raise HTTPException(400, f"That JSON doesn't match the site format: {e}")
    db.update_customer(cid, site=site)
    db.save_version(cid, site, "Manual edit")
    return back(cid, "site")


@app.post("/admin/c/{cid}/version/{vid}/restore")
def restore_version(cid: int, vid: int, user=Depends(admin)):
    v = db.get_version(vid)
    if not v or v["customer_id"] != cid:
        raise HTTPException(404)
    db.update_customer(cid, site=v["site"])
    return back(cid, "site")


@app.post("/admin/c/{cid}/publish")
def toggle_publish(cid: int, user=Depends(admin)):
    c = must_customer(cid)
    db.update_customer(cid, published=0 if c["published"] else 1)
    return back(cid, "site")


@app.post("/admin/c/{cid}/delete")
def delete_customer(cid: int, confirm: str = Form(""), user=Depends(admin)):
    c = must_customer(cid)
    if confirm.strip() != c["slug"]:
        raise HTTPException(400, "Type the customer's slug to confirm deletion.")
    for a in db.list_assets(cid):
        (settings.UPLOAD_DIR / a["filename"]).unlink(missing_ok=True)
    db.delete_customer(cid)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/c/{cid}/export.zip")
def export_zip(cid: int, user=Depends(admin)):
    c = must_customer(cid)
    if not c["site"]:
        raise HTTPException(400, "Generate the site first.")
    buf = io.BytesIO()
    used = set()

    def asset_url(aid):
        a = db.get_asset(aid)
        if not a:
            return ""
        used.add(a["filename"])
        return f"assets/{a['filename']}"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in c["site"]["pages"]:
            html_ = render.render_page(c, p["slug"], mode="export", asset_url=asset_url)
            z.writestr("index.html" if p["slug"] == "home" else f"{p['slug']}.html", html_)
        for fn in used:
            z.write(settings.UPLOAD_DIR / fn, f"assets/{fn}")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{c["slug"]}-site.zip"'})


# ---------------- Public ----------------

@app.get("/assets/{aid}")
def asset(aid: int):
    a = db.get_asset(aid)
    if not a:
        raise HTTPException(404)
    return FileResponse(settings.UPLOAD_DIR / a["filename"])


@app.get("/assets/{aid}/preview")
def asset_preview(aid: int, user=Depends(admin)):
    a = db.get_asset(aid)
    if not a:
        raise HTTPException(404)
    p = settings.UPLOAD_DIR / a["filename"]
    if a["kind"] == "pdf":
        p = p.with_suffix(".preview.png")
    return FileResponse(p)


@app.get("/internal/allow-domain")
def allow_domain(domain: str = ""):
    """Caddy's on-demand TLS asks here before getting a certificate, so only customer domains get one."""
    d = db.normalize_domain(domain)
    if d and (db.get_customer_by_domain(d)):
        return Response("ok")
    raise HTTPException(404)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _serve(c, page_slug, base, message=""):
    if not c or not c["published"] or not c["site"]:
        return HTMLResponse("<h1>Site not found</h1>", status_code=404)
    out = render.render_page(c, page_slug, base=base, message=message)
    if out is None:
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    return HTMLResponse(out)


async def _contact(request: Request, c, base):
    if not c or not c["site"]:
        raise HTTPException(404)
    form = await request.form()
    if form.get("website"):  # honeypot field for bots
        return RedirectResponse(base, status_code=303)
    db.add_lead(c["id"], form.get("name", "")[:200], form.get("email", "")[:200], form.get("phone", "")[:50],
                form.get("message", "")[:5000])
    page = form.get("page") or "contact"
    return RedirectResponse(f"{base}{'' if page == 'home' else page}?sent=1", status_code=303)


@app.get("/s/{slug}/", response_class=HTMLResponse)
@app.get("/s/{slug}/{page}", response_class=HTMLResponse)
def preview(slug: str, request: Request, page: str = "home"):
    msg = "Thanks! Your message was sent." if request.query_params.get("sent") else ""
    return _serve(db.get_customer_by_slug(slug), page, f"/s/{slug}/", msg)


@app.get("/s/{slug}")
def preview_redirect(slug: str):
    return RedirectResponse(f"/s/{slug}/", status_code=308)


@app.post("/s/{slug}/contact-submit")
async def preview_contact(slug: str, request: Request):
    return await _contact(request, db.get_customer_by_slug(slug), f"/s/{slug}/")


# Custom domains: whatever Host header matches a customer domain serves that site at the root.
@app.post("/contact-submit")
async def domain_contact(request: Request):
    return await _contact(request, db.get_customer_by_domain(request.headers.get("host", "")), "/")


@app.get("/", response_class=HTMLResponse)
@app.get("/{page}", response_class=HTMLResponse)
def root(request: Request, page: str = "home"):
    c = db.get_customer_by_domain(request.headers.get("host", ""))
    if c:
        msg = "Thanks! Your message was sent." if request.query_params.get("sent") else ""
        return _serve(c, page, "/", msg)
    if page == "home":
        return RedirectResponse("/admin", status_code=303)
    raise HTTPException(404)
