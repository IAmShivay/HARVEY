"""US brand filter: keep only US D2C product brands after profiling.

Broad searches return agencies, Shopify builders, SaaS, payment processors,
listicles and non-US sites alongside real brands. This reads each company's
own homepage and removes it unless it is a store that sells products, shows
US signals and is not a service business. Enabled by icp.us_brand_filter.

A company that has been emailed or has a conversation is never removed.
"""

import asyncio
import json
import logging
import re
from datetime import datetime

import httpx

logger = logging.getLogger("harvey.brand_filter")

SETTING_LAST_RUN = "brand_filter_last"

FETCH_TIMEOUT_SECONDS = 20
MAX_CONCURRENT_FETCHES = 8
MAX_PAGE_CHARS = 400_000
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

MIN_STORE_HITS = 2
MIN_US_HITS = 1
MAX_SERVICE_HITS = 1
MAX_REPORTED_DOMAINS = 50

BLOCKED_TLD_SUFFIXES = (".gov", ".edu", ".org", ".ai", ".io", ".dev",
                        ".co.uk", ".com.au", ".com.br", ".it", ".pl", ".lv",
                        ".ch", ".de", ".fr", ".in", ".ph", ".pk", ".id")
BLOCKED_HOST_PREFIXES = ("journals.", "careers.", "jobs.", "blog.", "news.")

STORE_PATTERNS = [
    r"add to cart", r"add to bag", r"shop now", r"/cart\b", r"/products/",
    r"cdn\.shopify\.com", r"shopify\.theme", r"woocommerce", r"bigcommerce",
    r"\bcheckout\b", r"\bfree shipping\b", r"\bbestsellers?\b",
]
US_PATTERNS = [
    r"\bUSD\b", r"united states", r"\bmade in (the )?usa\b", r"\bUSA\b",
    r"ships? (free )?(within|across|to) the (US|U\.S\.|United States)",
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|"
    r"MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|"
    r"WA|WV|WI|WY)\s+\d{5}\b",
]
SERVICE_PATTERNS = [
    r"\bagency\b", r"shopify (experts?|partners?|developers?|agency)",
    r"\bweb (design|development) (services|company)\b", r"\bour clients\b",
    r"\bcase stud(y|ies)\b", r"\bbook a demo\b", r"\brequest a demo\b",
    r"\bschedule a demo\b", r"\bstart (your )?free trial\b", r"\bpricing plans?\b",
    r"\bmerchant services\b", r"\bpayment processing\b", r"\bhire (us|our)\b",
    r"\bmarketing (services|solutions)\b", r"\bsaas\b", r"\bapi docs\b",
    r"\bmarket research\b", r"\bjob (openings|board)\b", r"\bwholesale only\b",
    r"\bprivate label manufactur", r"\bcontract manufactur",
]
LISTICLE_NAME_PATTERN = re.compile(
    r"\b(best|top \d+|\d+ best|largest|raises|brands to watch|list)\b", re.I)


NAME_SEPARATORS = re.compile(r"\s+[|–—:•·]\s+|\s+-\s+")
NON_TEXT_CHARS = re.compile(r"[^\w\s&'.,+-]", re.UNICODE)
NAME_SUFFIXES = re.compile(
    r"(\s*[®™]|[\s,]+(official site|official store|shop|store|inc|llc)\.?)\s*$", re.I)
MIN_WORDS_TO_SHORTEN = 4
NAME_PREFIXES = re.compile(r"^(about|welcome to|shop)\s+", re.I)
DOMAIN_FILLER = ("shop", "get", "try", "the", "store", "us", "usa")


def _domain_root(domain: str) -> str:
    root = (domain or "").lower().removeprefix("www.").removeprefix("store.").split(".")[0]
    for filler in DOMAIN_FILLER:
        if root.startswith(filler) and len(root) > len(filler) + 2:
            root = root.removeprefix(filler)
        if root.endswith(filler) and len(root) > len(filler) + 2:
            root = root.removesuffix(filler)
    return re.sub(r"[^a-z0-9]", "", root)


def clean_name(name: str, domain: str = "") -> str:
    """A page title made fit for an email: "Ceptics Travel Plug Adapters 🔌
    Connecting the World" on ceptics.com → "Ceptics"."""
    head = NAME_SEPARATORS.split(name or "")[0]
    head = re.split(r"[\U0001F000-\U0001FFFF☀-➿]", head)[0]
    head = NAME_PREFIXES.sub("", NAME_SUFFIXES.sub("", NON_TEXT_CHARS.sub("", head)))
    head = re.sub(r"\s{2,}", " ", head).strip(" -,.")
    root = _domain_root(domain)
    words = head.split()
    if len(words) < MIN_WORDS_TO_SHORTEN:
        return head or (name or "").strip()
    for i in range(1, len(words)):
        joined = re.sub(r"[^a-z0-9]", "", "".join(words[:i]).lower())
        if root and joined == root:
            return " ".join(words[:i])
    return head or (name or "").strip()


def enabled(config) -> bool:
    return bool(getattr(getattr(config, "icp", None), "us_brand_filter", False))


def _count_hits(patterns: list[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I))


def judge(name: str, domain: str, html: str | None, blocked_by: str = "") -> tuple[bool, str]:
    """(keep, reason) for one company."""
    if blocked_by:
        return False, f"on do_not_contact ({blocked_by})"
    if domain.endswith(BLOCKED_TLD_SUFFIXES):
        return False, "non-US or non-store domain ending"
    if domain.startswith(BLOCKED_HOST_PREFIXES):
        return False, "not a storefront host"
    if LISTICLE_NAME_PATTERN.search(name or ""):
        return False, "article or list page, not a brand"
    if html is None:
        return False, "site did not load"
    store = _count_hits(STORE_PATTERNS, html)
    us = _count_hits(US_PATTERNS, html)
    service = _count_hits(SERVICE_PATTERNS, html)
    if service > MAX_SERVICE_HITS:
        return False, f"service business ({service} service signals)"
    if store < MIN_STORE_HITS:
        return False, f"no storefront ({store} store signals)"
    if us < MIN_US_HITS:
        return False, "no US signals"
    return True, f"store {store}, US {us}, service {service}"


async def _fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> str | None:
    async with sem:
        try:
            r = await client.get(url)
            if r.status_code >= 400:
                return None
            return r.text[:MAX_PAGE_CHARS]
        except httpx.HTTPError:
            return None


async def _load_companies(db, company_ids: list[str] | None) -> list[tuple]:
    sql = ("select id, coalesce(name,''), domain, coalesce(website,'') from companies "
           "where domain is not null and domain != ''")
    params: list = []
    if company_ids is not None:
        if not company_ids:
            return []
        sql += f" and id in ({','.join('?' * len(company_ids))})"
        params = list(company_ids)
    async with db.execute(sql, params) as cur:
        return await cur.fetchall()


async def _contacted(db, company_id: str) -> bool:
    async with db.execute(
        "select 1 from prospects p where p.company_id = ? and ("
        " exists (select 1 from outbox o where o.prospect_id = p.id and o.status = 'sent')"
        " or exists (select 1 from conversations c where c.prospect_id = p.id)) limit 1",
        (company_id,)) as cur:
        return await cur.fetchone() is not None


async def _remove(db, company_id: str) -> None:
    async with db.execute("select id from prospects where company_id = ?", (company_id,)) as cur:
        prospect_ids = [r[0] for r in await cur.fetchall()]
    for pid in prospect_ids:
        await db.execute("delete from outbox where prospect_id = ? and status != 'sent'", (pid,))
    await db.execute("delete from observations where company_id = ?", (company_id,))
    await db.execute("delete from prospects where company_id = ?", (company_id,))
    await db.execute("delete from companies where id = ?", (company_id,))


async def filter_companies(state, config, company_ids: list[str] | None = None,
                           dry_run: bool = False) -> dict:
    """Judge companies (all when company_ids is None) and remove the misfits.

    Returns {"checked", "kept", "removed", "removed_domains", "results"}.
    """
    from harvey.config import live_do_not_contact
    from harvey.gate import do_not_contact_domain_match

    entries = live_do_not_contact(config) if config is not None else []
    async with state._connect() as db:
        rows = await _load_companies(db, company_ids)
    if not rows:
        return {"checked": 0, "kept": 0, "removed": 0, "removed_domains": [], "results": []}

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS,
                                 headers={"User-Agent": USER_AGENT}) as client:
        pages = await asyncio.gather(*(
            _fetch(client, sem, website or f"https://{domain}")
            for _, _, domain, website in rows))

    results = []
    for (cid, name, domain, _), html in zip(rows, pages):
        keep, reason = judge(name, domain, html, do_not_contact_domain_match(domain, entries))
        results.append({"id": cid, "domain": domain, "name": name,
                        "keep": keep, "reason": reason})

    removed = []
    async with state._connect() as db:
        for r in results:
            if r["keep"]:
                cleaned = clean_name(r["name"], r["domain"])
                if cleaned != r["name"] and not dry_run:
                    await db.execute("update companies set name = ? where id = ?",
                                     (cleaned, r["id"]))
                    await db.execute("update prospects set company = ? where company_id = ?",
                                     (cleaned, r["id"]))
                continue
            if await _contacted(db, r["id"]):
                r["keep"], r["reason"] = True, "kept: already contacted"
                continue
            if not dry_run:
                await _remove(db, r["id"])
            removed.append(r["domain"])
        await db.commit()

    summary = {
        "checked": len(results),
        "kept": len(results) - len(removed),
        "removed": len(removed),
        "removed_domains": sorted(removed)[:MAX_REPORTED_DOMAINS],
        "at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
    }
    if not dry_run:
        await state.set_setting(SETTING_LAST_RUN, json.dumps(summary))
    logger.info("brand filter: checked %d, kept %d, removed %d",
                summary["checked"], summary["kept"], summary["removed"])
    return {**summary, "results": results}


async def last_run(state) -> dict:
    raw = await state.get_setting(SETTING_LAST_RUN, "")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}
