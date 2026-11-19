"""Domain availability via RDAP (the modern WHOIS). 404 from the registry's RDAP server = not registered."""
import asyncio
import re
import socket
import time

import httpx

_bootstrap = {"at": 0, "map": {}}
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


async def _servers(client: httpx.AsyncClient) -> dict:
    if time.time() - _bootstrap["at"] < 86400 and _bootstrap["map"]:
        return _bootstrap["map"]
    try:
        r = await client.get("https://data.iana.org/rdap/dns.json", timeout=15)
        m = {}
        for tlds, urls in r.json()["services"]:
            for t in tlds:
                m[t.lower()] = urls[0].rstrip("/") + "/"
        _bootstrap.update(at=time.time(), map=m)
    except Exception:
        pass
    return _bootstrap["map"]


async def check_one(client: httpx.AsyncClient, domain: str) -> dict:
    domain = domain.strip().lower()
    if not DOMAIN_RE.match(domain):
        return {"domain": domain, "status": "invalid"}
    tld = domain.rsplit(".", 1)[1]
    servers = await _servers(client)
    base = servers.get(tld, "https://rdap.org/")
    try:
        r = await client.get(f"{base}domain/{domain}", timeout=12, follow_redirects=True,
                             headers={"Accept": "application/rdap+json"})
        if r.status_code == 404:
            return {"domain": domain, "status": "available"}
        if r.status_code == 200:
            return {"domain": domain, "status": "taken"}
    except Exception:
        pass
    # Fallback: if it resolves in DNS it's certainly taken; otherwise unknown.
    try:
        await asyncio.get_running_loop().run_in_executor(None, socket.gethostbyname, domain)
        return {"domain": domain, "status": "taken"}
    except Exception:
        return {"domain": domain, "status": "unknown"}


async def check_many(domains: list[str]) -> list[dict]:
    seen = list(dict.fromkeys(d.strip().lower() for d in domains if d.strip()))
    async with httpx.AsyncClient(headers={"User-Agent": "site-builder/1.0"}) as client:
        sem = asyncio.Semaphore(6)

        async def run(d):
            async with sem:
                return await check_one(client, d)

        return await asyncio.gather(*(run(d) for d in seen))
