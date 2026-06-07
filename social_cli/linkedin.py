"""LinkedIn lookups via public logged-out web surfaces.

LinkedIn does not expose a public unauthenticated API for profile, company,
post, or search data. This module mirrors the rest of the package: fetch the
logged-out public pages and parse OpenGraph metadata, JSON-LD, and the guest
jobs endpoints when LinkedIn serves them.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from .http import FetchError, get

BASE_URL = "https://www.linkedin.com"
PROFILE_URL = f"{BASE_URL}/in/{{slug}}/"
COMPANY_URL = f"{BASE_URL}/company/{{slug}}/"
SCHOOL_URL = f"{BASE_URL}/school/{{slug}}/"
POST_URL = f"{BASE_URL}/feed/update/{{urn}}/"
JOB_URL = f"{BASE_URL}/jobs/view/{{job_id}}/"
JOB_POSTING_API = f"{BASE_URL}/jobs-guest/jobs/api/jobPosting/{{job_id}}"
JOB_SEARCH_API = f"{BASE_URL}/jobs-guest/jobs/api/seeMoreJobPostings/search"
SEARCH_URL = f"{BASE_URL}/search/results/{{kind}}/"

_META_TAG_RE = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"([A-Za-z_:.-]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
_LD_RE = re.compile(
    r"<script[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(r"<a\s+[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TIME_RE = re.compile(r"<time\b[^>]*datetime=(['\"])(.*?)\1[^>]*>(.*?)</time>", re.IGNORECASE | re.DOTALL)
_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")

_SEARCH_KINDS = {
    "all": "all",
    "people": "people",
    "profiles": "people",
    "companies": "companies",
    "businesses": "companies",
    "business": "companies",
    "schools": "schools",
    "posts": "content",
    "content": "content",
    "jobs": "jobs",
}


def _linkedin_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def _attrs(tag: str) -> dict[str, str]:
    return {k.lower(): html.unescape(v) for k, _, v in _ATTR_RE.findall(tag)}


def _parse_meta(text: str) -> dict[str, str]:
    metas: dict[str, str] = {}
    for tag in _META_TAG_RE.findall(text):
        attrs = _attrs(tag)
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        value = attrs.get("content")
        if key and value and key.lower() not in metas:
            metas[key.lower()] = html.unescape(value)
    return metas


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _strip_linkedin_suffix(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    for suffix in (" | LinkedIn", " on LinkedIn", " LinkedIn"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or None


def _title(text: str) -> str | None:
    match = _TITLE_RE.search(text)
    return _strip_linkedin_suffix(match.group(1)) if match else None


def _json_ld_objects(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        out.append(node)
        graph = node.get("@graph")
        if graph is not None:
            walk(graph)

    for raw in _LD_RE.findall(text):
        try:
            parsed = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        walk(parsed)
    return out


def _has_type(obj: dict[str, Any], wanted: set[str]) -> bool:
    raw = obj.get("@type") or obj.get("type")
    types = raw if isinstance(raw, list) else [raw]
    return any(str(t).rsplit("/", 1)[-1] in wanted for t in types if t)


def _first_ld(text: str, *types: str) -> dict[str, Any]:
    wanted = set(types)
    for obj in _json_ld_objects(text):
        if _has_type(obj, wanted):
            return obj
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _entity_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _clean_text(value.get("name") or value.get("legalName"))
    return _clean_text(value)


def _entity_url(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("url") or value.get("@id")
    return None


def _external_url(value: Any) -> str | None:
    url = value if isinstance(value, str) else None
    if not url or "linkedin.com" in urlparse(url).netloc.lower():
        return None
    return url


def _entities(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in _as_list(value):
        name = _entity_name(item)
        url = _entity_url(item)
        if not name and not url:
            continue
        entry: dict[str, str] = {}
        if name:
            entry["name"] = name
        if url:
            entry["url"] = url
        out.append(entry)
    return out


def _image_url(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("url") or value.get("contentUrl")
    if isinstance(value, list):
        for item in value:
            url = _image_url(item)
            if url:
                return url
        return None
    return value if isinstance(value, str) else None


def _slug_or_url(value: str, path: str, template: str) -> tuple[str, str]:
    raw = value.strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        slug = ""
        if path in parts:
            idx = parts.index(path)
            if idx + 1 < len(parts):
                slug = parts[idx + 1]
        if not slug and parts:
            slug = parts[-1]
        return slug, raw
    slug = raw.lstrip("@").strip("/")
    if path and slug.startswith(f"{path}/"):
        slug = slug.split("/", 1)[1].strip("/")
    return slug, template.format(slug=slug)


def _job_id_or_url(value: str) -> tuple[str, str]:
    raw = value.strip()
    match = _JOB_ID_RE.search(raw)
    if match:
        job_id = match.group(1)
    else:
        job_id = re.sub(r"\D", "", raw)
    if not job_id:
        raise ValueError("Could not find a LinkedIn job id.")
    return job_id, JOB_URL.format(job_id=job_id)


def _post_url(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http"):
        return raw
    if raw.startswith("urn:li:"):
        return POST_URL.format(urn=raw)
    if raw.isdigit():
        return POST_URL.format(urn=f"urn:li:activity:{raw}")
    return urljoin(BASE_URL + "/", raw.lstrip("/"))


def _page_text(text: str) -> str:
    return _clean_text(text) or ""


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return _clean_text(match.group(0)) if match else None


def _labeled_value(page_text: str, label: str, stops: list[str]) -> str | None:
    stop_pattern = "|".join(re.escape(s) for s in stops if s != label)
    match = re.search(
        rf"\b{re.escape(label)}\b\s*(.+?)"
        rf"(?=\s+[\d][\d,.\s]*(?:K|M|B)?\+?\s+followers\b|\b(?:{stop_pattern})\b|$)",
        page_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return _clean_text(match.group(1))


def _address(value: Any) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if not isinstance(value, dict):
        return None
    parts = [
        value.get("streetAddress"),
        value.get("addressLocality"),
        value.get("addressRegion"),
        value.get("postalCode"),
        value.get("addressCountry"),
    ]
    return _clean_text(", ".join(str(p) for p in parts if p))


def _html_description(text: str, metas: dict[str, str], ld: dict[str, Any]) -> str | None:
    return (
        _clean_text(ld.get("description"))
        or _clean_text(metas.get("og:description"))
        or _clean_text(metas.get("description"))
    )


def profile(username: str) -> dict[str, Any]:
    """Fetch a public LinkedIn person profile by slug or URL."""
    slug, url = _slug_or_url(username, "in", PROFILE_URL)
    resp = get(url, headers=_linkedin_headers())
    metas = _parse_meta(resp.text)
    person = _first_ld(resp.text, "Person")
    page_text = _page_text(resp.text)
    title = _title(resp.text) or _strip_linkedin_suffix(metas.get("og:title"))
    works_for = _entities(person.get("worksFor"))
    alumni_of = _entities(person.get("alumniOf"))
    return {
        "type": "person",
        "slug": slug,
        "url": person.get("url") or metas.get("og:url") or url,
        "name": _clean_text(person.get("name")) or title,
        "headline": _clean_text(person.get("jobTitle")),
        "description": _html_description(resp.text, metas, person),
        "image": _image_url(person.get("image")) or metas.get("og:image"),
        "location": _address(person.get("address")),
        "followers_text": _first_match(page_text, r"[\d][\d,.\s]*(?:K|M|B)?\+?\s+followers"),
        "connections_text": _first_match(page_text, r"[\d][\d,.\s]*(?:K|M|B)?\+?\s+connections"),
        "current_company": works_for[0]["name"] if works_for else None,
        "works_for": works_for,
        "education": alumni_of,
        "same_as": person.get("sameAs") or [],
        "source": "public_profile",
        "note": "LinkedIn only exposes limited logged-out profile data.",
    }


def company(company_name: str) -> dict[str, Any]:
    """Fetch a public LinkedIn company/business page by slug or URL."""
    slug, url = _slug_or_url(company_name, "company", COMPANY_URL)
    resp = get(url, headers=_linkedin_headers())
    metas = _parse_meta(resp.text)
    org = _first_ld(resp.text, "Organization", "Corporation", "LocalBusiness")
    page_text = _page_text(resp.text)
    stops = [
        "Website",
        "Industry",
        "Company size",
        "Headquarters",
        "Type",
        "Founded",
        "Specialties",
        "Locations",
        "Employees at",
        "Updates",
        "Jobs",
    ]
    return {
        "type": "organization",
        "slug": slug,
        "url": org.get("url") or metas.get("og:url") or url,
        "name": _clean_text(org.get("name") or org.get("legalName")) or _title(resp.text),
        "description": _html_description(resp.text, metas, org),
        "image": _image_url(org.get("logo") or org.get("image")) or metas.get("og:image"),
        "website": _external_url(org.get("url")) or _labeled_value(page_text, "Website", stops),
        "industry": _clean_text(org.get("industry")) or _labeled_value(page_text, "Industry", stops),
        "company_size": _clean_text(org.get("numberOfEmployees")) or _labeled_value(page_text, "Company size", stops),
        "headquarters": _address(org.get("address")) or _labeled_value(page_text, "Headquarters", stops),
        "company_type": _labeled_value(page_text, "Type", stops),
        "founded": _clean_text(org.get("foundingDate")) or _labeled_value(page_text, "Founded", stops),
        "specialties": _labeled_value(page_text, "Specialties", stops),
        "followers_text": _first_match(page_text, r"[\d][\d,.\s]*(?:K|M|B)?\+?\s+followers"),
        "jobs_url": url.rstrip("/") + "/jobs/",
        "posts_url": url.rstrip("/") + "/posts/",
        "same_as": org.get("sameAs") or [],
        "source": "public_company",
        "note": "LinkedIn company pages expose limited logged-out business data.",
    }


def business(company_name: str) -> dict[str, Any]:
    """Alias for company(), matching common LinkedIn business-page language."""
    return company(company_name)


def school(school_name: str) -> dict[str, Any]:
    """Fetch a public LinkedIn school page by slug or URL."""
    slug, url = _slug_or_url(school_name, "school", SCHOOL_URL)
    resp = get(url, headers=_linkedin_headers())
    metas = _parse_meta(resp.text)
    org = _first_ld(
        resp.text,
        "EducationalOrganization",
        "CollegeOrUniversity",
        "Organization",
    )
    page_text = _page_text(resp.text)
    stops = ["Website", "Industry", "Company size", "Headquarters", "Type", "Founded", "Alumni", "Updates", "Jobs"]
    return {
        "type": "school",
        "slug": slug,
        "url": org.get("url") or metas.get("og:url") or url,
        "name": _clean_text(org.get("name")) or _title(resp.text),
        "description": _html_description(resp.text, metas, org),
        "image": _image_url(org.get("logo") or org.get("image")) or metas.get("og:image"),
        "website": _external_url(org.get("url")) or _labeled_value(page_text, "Website", stops),
        "location": _address(org.get("address")) or _labeled_value(page_text, "Headquarters", stops),
        "alumni_text": _first_match(page_text, r"[\d][\d,.\s]*(?:K|M|B)?\+?\s+alumni"),
        "followers_text": _first_match(page_text, r"[\d][\d,.\s]*(?:K|M|B)?\+?\s+followers"),
        "source": "public_school",
        "note": "LinkedIn school pages expose limited logged-out data.",
    }


def post(url_or_urn: str) -> dict[str, Any]:
    """Fetch a LinkedIn feed post/update by full URL, URN, or activity id."""
    url = _post_url(url_or_urn)
    resp = get(url, headers=_linkedin_headers())
    metas = _parse_meta(resp.text)
    item = _first_ld(resp.text, "SocialMediaPosting", "Article", "CreativeWork")
    author = item.get("author") or item.get("creator") or {}
    return {
        "type": "post",
        "url": item.get("url") or metas.get("og:url") or url,
        "title": _clean_text(item.get("headline")) or _strip_linkedin_suffix(metas.get("og:title")),
        "text": _clean_text(item.get("articleBody") or item.get("text")) or _clean_text(metas.get("og:description")),
        "author": {
            "name": _entity_name(author),
            "url": _entity_url(author),
        },
        "published_time": item.get("datePublished") or metas.get("article:published_time"),
        "updated_time": item.get("dateModified") or metas.get("article:modified_time"),
        "image": _image_url(item.get("image")) or metas.get("og:image"),
        "video": _image_url(item.get("video")) or metas.get("og:video"),
        "source": "public_post",
        "note": "Reactions and comments are not exposed to logged-out visitors.",
    }


def _job_locations(value: Any) -> list[str]:
    locations: list[str] = []
    for loc in _as_list(value):
        if isinstance(loc, dict):
            address = _address(loc.get("address") or loc)
            if address:
                locations.append(address)
        else:
            text = _clean_text(loc)
            if text:
                locations.append(text)
    return locations


def _criteria(text: str) -> dict[str, str]:
    criteria: dict[str, str] = {}
    pattern = re.compile(
        r"<span[^>]*class=['\"][^'\"]*description__job-criteria-subheader[^'\"]*['\"][^>]*>"
        r"(.*?)</span>\s*"
        r"<span[^>]*class=['\"][^'\"]*description__job-criteria-text[^'\"]*['\"][^>]*>"
        r"(.*?)</span>",
        re.IGNORECASE | re.DOTALL,
    )
    for label, value in pattern.findall(text):
        key = (_clean_text(label) or "").lower().replace(" ", "_")
        cleaned = _clean_text(value)
        if key and cleaned:
            criteria[key] = cleaned
    return criteria


def job(job_id_or_url: str) -> dict[str, Any]:
    """Fetch a LinkedIn job by numeric id or /jobs/view/... URL."""
    job_id, canonical_url = _job_id_or_url(job_id_or_url)
    api_url = JOB_POSTING_API.format(job_id=job_id)
    try:
        resp = get(api_url, headers=_linkedin_headers())
        source = api_url
    except FetchError:
        resp = get(canonical_url, headers=_linkedin_headers())
        source = canonical_url
    metas = _parse_meta(resp.text)
    posting = _first_ld(resp.text, "JobPosting")
    org = posting.get("hiringOrganization") or {}
    criteria = _criteria(resp.text)
    return {
        "type": "job",
        "id": job_id,
        "url": posting.get("url") or metas.get("og:url") or canonical_url,
        "title": _clean_text(posting.get("title")) or _strip_linkedin_suffix(metas.get("og:title")),
        "company": _entity_name(org),
        "company_url": _entity_url(org),
        "company_logo": _image_url(org.get("logo")) if isinstance(org, dict) else None,
        "locations": _job_locations(posting.get("jobLocation")),
        "workplace_type": criteria.get("workplace_type"),
        "employment_type": _clean_text(posting.get("employmentType")) or criteria.get("employment_type"),
        "seniority_level": criteria.get("seniority_level"),
        "job_function": criteria.get("job_function"),
        "industries": criteria.get("industries"),
        "date_posted": posting.get("datePosted"),
        "valid_through": posting.get("validThrough"),
        "description": _clean_text(posting.get("description")) or _clean_text(metas.get("og:description")),
        "applicant_location_requirements": _entities(posting.get("applicantLocationRequirements")),
        "direct_apply": posting.get("directApply"),
        "source": source,
    }


def _tag_text(card: str, tag: str, class_fragment: str) -> str | None:
    match = re.search(
        rf"<{tag}[^>]*class=['\"][^'\"]*{re.escape(class_fragment)}[^'\"]*['\"][^>]*>(.*?)</{tag}>",
        card,
        re.IGNORECASE | re.DOTALL,
    )
    return _clean_text(match.group(1)) if match else None


def _attr_from_tag(card: str, tag: str, class_fragment: str, attr: str) -> str | None:
    match = re.search(
        rf"<{tag}[^>]*class=['\"][^'\"]*{re.escape(class_fragment)}[^'\"]*['\"][^>]*>",
        card,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _attrs(match.group(0)).get(attr)


def _extract_job_cards(text: str) -> list[dict[str, Any]]:
    cards = re.split(r"<li\b", text, flags=re.IGNORECASE)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        if "/jobs/view/" not in card:
            continue
        href_match = re.search(r"href=(['\"])(https?://[^'\"]*/jobs/view/[^'\"]+)\1", card)
        if not href_match:
            continue
        url = html.unescape(href_match.group(2)).split("?", 1)[0]
        job_id_match = _JOB_ID_RE.search(url)
        key = job_id_match.group(1) if job_id_match else url
        if key in seen:
            continue
        seen.add(key)
        time_match = _TIME_RE.search(card)
        company_link = re.search(
            r"<h4[^>]*class=['\"][^'\"]*base-search-card__subtitle[^'\"]*['\"][^>]*>.*?"
            r"<a[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>",
            card,
            re.IGNORECASE | re.DOTALL,
        )
        out.append(
            {
                "id": key,
                "url": url,
                "title": _tag_text(card, "h3", "base-search-card__title"),
                "company": _clean_text(company_link.group(3)) if company_link else _tag_text(card, "h4", "base-search-card__subtitle"),
                "company_url": html.unescape(company_link.group(2)).split("?", 1)[0] if company_link else None,
                "location": _tag_text(card, "span", "job-search-card__location"),
                "listed_at": html.unescape(time_match.group(2)) if time_match else None,
                "listed_text": _clean_text(time_match.group(3)) if time_match else None,
                "salary": _tag_text(card, "span", "job-search-card__salary-info"),
                "image": _attr_from_tag(card, "img", "artdeco-entity-image", "data-delayed-url")
                or _attr_from_tag(card, "img", "artdeco-entity-image", "src"),
            }
        )
    return out


def jobs(
    keywords: str,
    *,
    location: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search LinkedIn public guest job cards."""
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    start = 0
    while len(collected) < limit:
        params: dict[str, Any] = {"keywords": keywords, "start": start}
        if location:
            params["location"] = location
        resp = get(JOB_SEARCH_API, params=params, headers=_linkedin_headers())
        cards = _extract_job_cards(resp.text)
        if not cards:
            break
        added = 0
        for item in cards:
            key = item.get("id") or item.get("url")
            if key in seen:
                continue
            seen.add(str(key))
            collected.append(item)
            added += 1
            if len(collected) >= limit:
                break
        if added == 0:
            break
        start += 25
    return {
        "query": keywords,
        "location": location,
        "source": JOB_SEARCH_API,
        "count": len(collected),
        "jobs": collected[:limit],
    }


def _result_type(url: str) -> str:
    path = urlparse(url).path
    if "/in/" in path:
        return "person"
    if "/company/" in path:
        return "company"
    if "/school/" in path:
        return "school"
    if "/jobs/view/" in path:
        return "job"
    if "/feed/update/" in path or "/posts/" in path:
        return "post"
    return "link"


def _extract_search_results(text: str, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, href, label_html in _ANCHOR_RE.findall(text):
        url = html.unescape(href)
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)
        if "linkedin.com" not in url:
            continue
        if not any(part in url for part in ("/in/", "/company/", "/school/", "/feed/update/", "/jobs/view/", "/posts/")):
            continue
        url = url.split("?", 1)[0]
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "type": _result_type(url),
                "title": _clean_text(label_html) or url,
                "url": url,
            }
        )
        if len(out) >= limit:
            break
    return out


def search(
    query: str,
    *,
    kind: str = "all",
    limit: int = 10,
    location: str | None = None,
) -> dict[str, Any]:
    """Search public LinkedIn result pages.

    For kind="jobs", this uses the public guest jobs endpoint. Other kinds
    parse logged-out search result pages and may be thin when LinkedIn gates
    the page behind sign-in.
    """
    normalized = _SEARCH_KINDS.get(kind.lower())
    if not normalized:
        allowed = ", ".join(sorted(_SEARCH_KINDS))
        raise ValueError(f"Unknown LinkedIn search type {kind!r}; expected one of: {allowed}")
    if normalized == "jobs":
        data = jobs(query, location=location, limit=limit)
        return {
            "query": query,
            "type": "jobs",
            "source": data["source"],
            "count": data["count"],
            "results": data["jobs"],
        }
    url = SEARCH_URL.format(kind=normalized)
    resp = get(url, params={"keywords": query}, headers=_linkedin_headers())
    results = _extract_search_results(resp.text, limit)
    return {
        "query": query,
        "type": normalized,
        "source": f"{url}?keywords={quote_plus(query)}",
        "count": len(results),
        "results": results,
        "note": "Logged-out LinkedIn search results may be incomplete or sign-in gated.",
    }
