"""Tests for LinkedIn public-page and guest-job parsing."""

from __future__ import annotations

import json as jsonlib

import pytest

from social_cli import linkedin
from social_cli.http import FetchError
from tests.conftest import FakeResponse


def _html_with_ld(ld_obj: object, *, head: str = "", body: str = "") -> str:
    return (
        "<html><head>"
        f"{head}"
        f'<script type="application/ld+json">{jsonlib.dumps(ld_obj)}</script>'
        "</head><body>"
        f"{body}"
        "</body></html>"
    )


def test_profile_parses_person_json_ld_and_counts(patch_get):
    seen = {}
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Person",
                "name": "Ada Lovelace",
                "url": "https://www.linkedin.com/in/ada/",
                "jobTitle": "Computing pioneer",
                "description": "Analytical engine notes.",
                "image": {"url": "https://img/ada.jpg"},
                "address": {"addressLocality": "London", "addressCountry": "UK"},
                "worksFor": {"name": "Analytical Engines Ltd", "url": "https://company/ae"},
                "alumniOf": [{"name": "University of London"}],
                "sameAs": ["https://example.com/ada"],
            }
        ],
    }
    html = _html_with_ld(
        ld,
        head='<meta property="og:image" content="https://img/fallback.jpg">',
        body="<main>14,321 followers 500+ connections</main>",
    )

    def factory(url, kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers") or {}
        return FakeResponse(text=html)

    patch_get(linkedin, factory)
    out = linkedin.profile("https://www.linkedin.com/in/ada/?trk=public_profile")
    assert seen["url"] == "https://www.linkedin.com/in/ada/?trk=public_profile"
    assert seen["headers"]["Accept-Language"] == "en-US,en;q=0.9"
    assert out["type"] == "person"
    assert out["slug"] == "ada"
    assert out["name"] == "Ada Lovelace"
    assert out["headline"] == "Computing pioneer"
    assert out["current_company"] == "Analytical Engines Ltd"
    assert out["works_for"][0]["url"] == "https://company/ae"
    assert out["education"][0]["name"] == "University of London"
    assert out["location"] == "London, UK"
    assert out["followers_text"] == "14,321 followers"
    assert out["connections_text"] == "500+ connections"
    assert out["image"] == "https://img/ada.jpg"


def test_company_parses_business_metadata_and_labeled_fields(patch_get):
    ld = {
        "@type": "Organization",
        "name": "OpenAI",
        "url": "https://www.linkedin.com/company/openai/",
        "description": "AI research and deployment company.",
        "logo": {"url": "https://img/openai.png"},
        "sameAs": ["https://openai.com/"],
    }
    body = (
        "Website https://openai.com/ "
        "Industry Software Development "
        "Company size 501-1,000 employees "
        "Headquarters San Francisco, CA "
        "Type Privately Held "
        "Founded 2015 "
        "Specialties artificial intelligence, research "
        "1,234,567 followers Jobs"
    )
    patch_get(linkedin, lambda url, kwargs: FakeResponse(text=_html_with_ld(ld, body=body)))
    out = linkedin.company("@openai/")
    assert out["type"] == "organization"
    assert out["slug"] == "openai"
    assert out["name"] == "OpenAI"
    assert out["description"] == "AI research and deployment company."
    assert out["website"] == "https://openai.com/"
    assert out["industry"] == "Software Development"
    assert out["company_size"] == "501-1,000 employees"
    assert out["headquarters"] == "San Francisco, CA"
    assert out["company_type"] == "Privately Held"
    assert out["founded"] == "2015"
    assert out["specialties"] == "artificial intelligence, research"
    assert out["followers_text"] == "1,234,567 followers"
    assert out["jobs_url"] == "https://www.linkedin.com/company/openai/jobs/"
    assert out["posts_url"] == "https://www.linkedin.com/company/openai/posts/"


def test_business_alias_calls_company(patch_get):
    patch_get(
        linkedin,
        lambda url, kwargs: FakeResponse(text=_html_with_ld({"@type": "Organization", "name": "Acme"})),
    )
    assert linkedin.business("acme")["name"] == "Acme"


def test_company_jobs_parses_company_page_main_job_cards(patch_get):
    seen = {}
    html = """
    <html>
      <head><title>LinkedIn Jobs | LinkedIn</title></head>
      <body>
        <ul>
          <li>
            <div class="base-main-card main-job-card" data-entity-urn="urn:li:jobPosting:4425">
              <a class="base-card__full-link" href="https://ca.linkedin.com/jobs/view/sales-lead-at-linkedin-4425?trk=org-job-results">
                <span class="sr-only">Sales Lead</span>
              </a>
              <img class="hue-web-entity__image" data-delayed-url="https://img/linkedin.png">
              <h3 class="base-main-card__title base-main-card__title--link">Sales Lead</h3>
              <h4 class="base-main-card__subtitle">
                <a href="/company/linkedin?trk=org-job-results">LinkedIn</a>
              </h4>
              <span class="main-job-card__location">Toronto, Ontario, Canada</span>
              <time class="main-job-card__listdate--new" datetime="2026-06-06">22 hours ago</time>
            </div>
          </li>
        </ul>
      </body>
    </html>
    """

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=html)

    patch_get(linkedin, factory)
    out = linkedin.company_jobs("https://www.linkedin.com/company/linkedin/?trk=public")
    assert seen["url"] == "https://www.linkedin.com/company/linkedin/jobs/"
    assert out["type"] == "company_jobs"
    assert out["slug"] == "linkedin"
    assert out["company"] == "LinkedIn Jobs"
    assert out["count"] == 1
    assert out["jobs"][0] == {
        "id": "4425",
        "url": "https://www.linkedin.com/jobs/view/sales-lead-at-linkedin-4425",
        "title": "Sales Lead",
        "company": "LinkedIn",
        "company_url": "https://www.linkedin.com/company/linkedin",
        "location": "Toronto, Ontario, Canada",
        "listed_at": "2026-06-06",
        "listed_text": "22 hours ago",
        "salary": None,
        "image": "https://img/linkedin.png",
    }


def test_company_jobs_respects_limit(patch_get):
    html = "".join(
        f"""
        <li>
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/role-{i}">
            role
          </a>
          <h3 class="base-main-card__title">Role {i}</h3>
        </li>
        """
        for i in range(1, 4)
    )
    patch_get(linkedin, lambda url, kwargs: FakeResponse(text=html))
    out = linkedin.company_jobs("acme", limit=2)
    assert out["count"] == 2
    assert [job["id"] for job in out["jobs"]] == ["1", "2"]


def test_company_posts_extracts_public_post_links(patch_get):
    html = """
    <html>
      <head><title>OpenAI Posts | LinkedIn</title></head>
      <body>
        <a href="/feed/update/urn:li:activity:123?trk=updates">Launch update</a>
        <a href="https://www.linkedin.com/posts/openai_activity-456?utm_source=share">Research note</a>
        <a href="https://www.linkedin.com/posts/openai_activity-456?duplicate=true">Duplicate</a>
        <a href="https://example.com/posts/not-linkedin">Ignore</a>
      </body>
    </html>
    """
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=html)

    patch_get(linkedin, factory)
    out = linkedin.company_posts("@openai/", limit=10)
    assert seen["url"] == "https://www.linkedin.com/company/openai/posts/"
    assert out["type"] == "company_posts"
    assert out["company"] == "OpenAI Posts"
    assert out["count"] == 2
    assert out["posts"] == [
        {
            "type": "post",
            "title": "Launch update",
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:123",
        },
        {
            "type": "post",
            "title": "Research note",
            "url": "https://www.linkedin.com/posts/openai_activity-456",
        },
    ]


def test_school_parses_educational_page(patch_get):
    ld = {
        "@type": "CollegeOrUniversity",
        "name": "Example University",
        "description": "A public university.",
        "logo": "https://img/school.png",
        "address": {
            "addressLocality": "Cambridge",
            "addressRegion": "MA",
            "addressCountry": "US",
        },
    }
    body = "123,456 alumni 98,765 followers"
    patch_get(linkedin, lambda url, kwargs: FakeResponse(text=_html_with_ld(ld, body=body)))
    out = linkedin.school("example-university")
    assert out["type"] == "school"
    assert out["name"] == "Example University"
    assert out["location"] == "Cambridge, MA, US"
    assert out["alumni_text"] == "123,456 alumni"
    assert out["followers_text"] == "98,765 followers"


def test_post_accepts_activity_id_and_parses_social_posting(patch_get):
    seen = {}
    ld = {
        "@type": "SocialMediaPosting",
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:123/",
        "headline": "Launch update",
        "articleBody": "We shipped it.",
        "datePublished": "2026-06-01T12:00:00Z",
        "author": {"name": "OpenAI", "url": "https://www.linkedin.com/company/openai/"},
        "image": {"url": "https://img/post.jpg"},
    }

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=_html_with_ld(ld))

    patch_get(linkedin, factory)
    out = linkedin.post("123")
    assert seen["url"] == "https://www.linkedin.com/feed/update/urn:li:activity:123/"
    assert out["type"] == "post"
    assert out["title"] == "Launch update"
    assert out["text"] == "We shipped it."
    assert out["author"] == {
        "name": "OpenAI",
        "url": "https://www.linkedin.com/company/openai/",
    }
    assert out["published_time"] == "2026-06-01T12:00:00Z"
    assert out["image"] == "https://img/post.jpg"


def test_job_uses_guest_endpoint_and_parses_criteria(patch_get):
    seen = {}
    ld = {
        "@type": "JobPosting",
        "title": "Founding Engineer",
        "url": "https://www.linkedin.com/jobs/view/12345/",
        "description": "<p>Build product.</p>",
        "datePosted": "2026-06-01",
        "validThrough": "2026-07-01",
        "employmentType": "FULL_TIME",
        "directApply": True,
        "hiringOrganization": {
            "name": "OpenAI",
            "url": "https://www.linkedin.com/company/openai/",
            "logo": "https://img/logo.png",
        },
        "jobLocation": [
            {"address": {"addressLocality": "San Francisco", "addressRegion": "CA", "addressCountry": "US"}},
            {"address": {"addressLocality": "Remote", "addressCountry": "US"}},
        ],
    }
    criteria = (
        '<span class="description__job-criteria-subheader">Seniority level</span>'
        '<span class="description__job-criteria-text">Mid-Senior level</span>'
        '<span class="description__job-criteria-subheader">Job function</span>'
        '<span class="description__job-criteria-text">Engineering</span>'
        '<span class="description__job-criteria-subheader">Industries</span>'
        '<span class="description__job-criteria-text">Software Development</span>'
    )

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=_html_with_ld(ld, body=criteria))

    patch_get(linkedin, factory)
    out = linkedin.job("https://www.linkedin.com/jobs/view/12345/?refId=x")
    assert seen["url"] == "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/12345"
    assert out["id"] == "12345"
    assert out["title"] == "Founding Engineer"
    assert out["company"] == "OpenAI"
    assert out["company_logo"] == "https://img/logo.png"
    assert out["locations"] == ["San Francisco, CA, US", "Remote, US"]
    assert out["employment_type"] == "FULL_TIME"
    assert out["seniority_level"] == "Mid-Senior level"
    assert out["job_function"] == "Engineering"
    assert out["industries"] == "Software Development"
    assert out["direct_apply"] is True
    assert out["description"] == "Build product."


def test_job_falls_back_to_public_view_page_when_guest_endpoint_blocks(patch_get):
    calls = []
    ld = {"@type": "JobPosting", "title": "Fallback Job"}

    def factory(url, kwargs):
        calls.append(url)
        if "jobs-guest" in url:
            raise FetchError(url, 999, "blocked")
        return FakeResponse(text=_html_with_ld(ld))

    patch_get(linkedin, factory)
    out = linkedin.job("98765")
    assert calls == [
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/98765",
        "https://www.linkedin.com/jobs/view/98765/",
    ]
    assert out["title"] == "Fallback Job"
    assert out["source"] == "https://www.linkedin.com/jobs/view/98765/"


def test_jobs_search_parses_guest_cards_and_respects_limit(patch_get):
    seen = {}
    html = """
    <ul>
      <li>
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/111?trk=public_jobs_topcard-title">
          <span class="sr-only">Ignore duplicate title</span>
        </a>
        <img class="artdeco-entity-image" data-delayed-url="https://img/company.png">
        <h3 class="base-search-card__title">Staff Engineer</h3>
        <h4 class="base-search-card__subtitle"><a href="https://www.linkedin.com/company/acme?trk=x">Acme</a></h4>
        <span class="job-search-card__location">New York, NY</span>
        <time datetime="2026-06-02">1 day ago</time>
        <span class="job-search-card__salary-info">$200K/yr</span>
      </li>
      <li>
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/222"></a>
        <h3 class="base-search-card__title">Product Engineer</h3>
        <h4 class="base-search-card__subtitle">Beta Inc</h4>
        <span class="job-search-card__location">Remote</span>
      </li>
    </ul>
    """

    def factory(url, kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params") or {}
        return FakeResponse(text=html)

    patch_get(linkedin, factory)
    out = linkedin.jobs("engineer", location="Remote", limit=1)
    assert seen["url"] == "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    assert seen["params"] == {"keywords": "engineer", "start": 0, "location": "Remote"}
    assert out["count"] == 1
    assert out["jobs"][0]["id"] == "111"
    assert out["jobs"][0]["url"] == "https://www.linkedin.com/jobs/view/111"
    assert out["jobs"][0]["title"] == "Staff Engineer"
    assert out["jobs"][0]["company"] == "Acme"
    assert out["jobs"][0]["company_url"] == "https://www.linkedin.com/company/acme"
    assert out["jobs"][0]["location"] == "New York, NY"
    assert out["jobs"][0]["listed_at"] == "2026-06-02"
    assert out["jobs"][0]["salary"] == "$200K/yr"
    assert out["jobs"][0]["image"] == "https://img/company.png"


def test_generic_search_categorizes_public_linkedin_results(patch_get):
    html = """
    <a href="https://www.linkedin.com/in/ada/?trk=search">Ada Lovelace</a>
    <a href="https://www.linkedin.com/company/openai/">OpenAI</a>
    <a href="https://www.linkedin.com/school/example/">Example University</a>
    <a href="https://www.linkedin.com/feed/update/urn:li:activity:123/">Post</a>
    <a href="https://example.com/not-linkedin">Other</a>
    <a href="https://www.linkedin.com/in/ada/?trk=duplicate">Ada duplicate</a>
    """
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params") or {}
        return FakeResponse(text=html)

    patch_get(linkedin, factory)
    out = linkedin.search("openai founders", kind="people", limit=10)
    assert seen["url"] == "https://www.linkedin.com/search/results/people/"
    assert seen["params"] == {"keywords": "openai founders"}
    assert out["source"] == "https://www.linkedin.com/search/results/people/?keywords=openai+founders"
    assert out["count"] == 4
    assert [r["type"] for r in out["results"]] == ["person", "company", "school", "post"]
    assert out["results"][0] == {
        "type": "person",
        "title": "Ada Lovelace",
        "url": "https://www.linkedin.com/in/ada/",
    }


def test_search_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unknown LinkedIn search type"):
        linkedin.search("x", kind="aliens")
