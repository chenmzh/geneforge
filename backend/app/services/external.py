"""External database / API registry with an SSRF-guarded server-side proxy.

Two integration styles are supported:

* ``link``  — a URL template rendered in the browser (deep links to NCBI, AddGene...)
* ``rest``  — fetched server-side by GeneForge so results can be imported directly;
              only hosts on ``EXTERNAL_PROXY_ALLOWLIST`` may be contacted, private
              address space is rejected, and responses are size limited.
"""
from __future__ import annotations

import ipaddress
import socket
from string import Formatter
from typing import Any
from urllib.parse import quote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.exceptions import ExternalServiceError, NotFoundError, ValidationError
from ..models import ExternalResource, User

DEFAULT_RESOURCES: list[dict[str, Any]] = [
    {
        "name": "NCBI Nucleotide (link)",
        "kind": "link",
        "description": "Open an accession in the NCBI Nucleotide web viewer",
        "url_template": "https://www.ncbi.nlm.nih.gov/nuccore/{accession}",
        "allow_proxy": False,
    },
    {
        "name": "NCBI efetch GenBank",
        "kind": "rest",
        "description": "Fetch a GenBank record by accession and import it directly",
        "url_template": (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            "?db={db}&id={accession}&rettype=gbwithparts&retmode=text"
        ),
        "query_defaults": {"db": "nuccore"},
        "allow_proxy": True,
    },
    {
        "name": "NCBI BLAST (link)",
        "kind": "blast",
        "description": "Send a sequence to NCBI BLAST in a new tab",
        "url_template": "https://blast.ncbi.nlm.nih.gov/Blast.cgi?PAGE_TYPE=BlastSearch&PROGRAM=blastn&QUERY={sequence}",
        "allow_proxy": False,
    },
    {
        "name": "UniProt (rest)",
        "kind": "rest",
        "description": "Fetch a protein record from UniProt as FASTA",
        "url_template": "https://rest.uniprot.org/uniprotkb/{accession}.fasta",
        "allow_proxy": True,
    },
    {
        "name": "Ensembl sequence (rest)",
        "kind": "rest",
        "description": "Fetch a sequence region from Ensembl REST as FASTA",
        "url_template": "https://rest.ensembl.org/sequence/id/{id}?content-type=text/x-fasta",
        "allow_proxy": True,
    },
    {
        "name": "AddGene plasmid (link)",
        "kind": "link",
        "description": "Open an AddGene plasmid page",
        "url_template": "https://www.addgene.org/{plasmid_id}/",
        "allow_proxy": False,
    },
]


def seed_defaults(db: Session, *, created_by: User | None = None) -> int:
    created = 0
    for entry in DEFAULT_RESOURCES:
        exists = db.scalars(select(ExternalResource).where(ExternalResource.name == entry["name"])).first()
        if exists:
            continue
        db.add(
            ExternalResource(
                name=entry["name"],
                kind=entry["kind"],
                description=entry.get("description"),
                url_template=entry["url_template"],
                query_defaults=entry.get("query_defaults", {}),
                allow_proxy=entry.get("allow_proxy", False),
                created_by_id=created_by.id if created_by else None,
            )
        )
        created += 1
    db.flush()
    return created


def list_resources(db: Session, *, enabled_only: bool = True) -> list[ExternalResource]:
    stmt = select(ExternalResource).order_by(ExternalResource.name)
    if enabled_only:
        stmt = stmt.where(ExternalResource.is_enabled.is_(True))
    return list(db.scalars(stmt))


def get_resource(db: Session, resource_id: str) -> ExternalResource:
    resource = db.get(ExternalResource, resource_id)
    if not resource:
        resource = db.scalars(select(ExternalResource).where(ExternalResource.name == resource_id)).first()
    if not resource:
        raise NotFoundError("External resource not found")
    return resource


def template_fields(url_template: str) -> list[str]:
    return [name for _, name, _, _ in Formatter().parse(url_template) if name]


def render_url(resource: ExternalResource, params: dict[str, Any]) -> str:
    merged = {**(resource.query_defaults or {}), **params}
    missing = [f for f in template_fields(resource.url_template) if f not in merged]
    if missing:
        raise ValidationError(f"Missing template parameters: {', '.join(missing)}")
    quoted = {k: quote(str(v), safe="") for k, v in merged.items()}
    return resource.url_template.format(**quoted)


def _assert_public_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("Only http(s) URLs may be proxied")
    host = parsed.hostname or ""
    allowlist = settings.external_proxy_allowlist
    if allowlist and not any(host == allowed or host.endswith("." + allowed) for allowed in allowlist):
        raise ValidationError(
            f"Host '{host}' is not in EXTERNAL_PROXY_ALLOWLIST; add it in the deployment configuration"
        )
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ExternalServiceError(f"Cannot resolve host '{host}': {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValidationError(f"Refusing to proxy to a private address ({ip})")
    return host


def fetch(resource: ExternalResource, params: dict[str, Any], *, max_bytes: int = 16 * 1024 * 1024) -> tuple[str, str]:
    """Fetch a remote record. Returns (text, resolved_url)."""
    if not settings.external_proxy_enabled:
        raise ValidationError("Server-side proxying is disabled (EXTERNAL_PROXY_ENABLED=false)")
    if not resource.allow_proxy:
        raise ValidationError(f"Resource '{resource.name}' is not allowed to be proxied")
    url = render_url(resource, params)
    _assert_public_host(url)

    import httpx

    headers = {"User-Agent": f"GeneForge/{settings.app_version}", **(resource.headers or {})}
    try:
        with httpx.Client(timeout=settings.external_proxy_timeout_seconds, follow_redirects=False) as client:
            response = client.request(resource.method or "GET", url, headers=headers)
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Upstream request failed: {exc}") from exc
    if response.status_code >= 400:
        raise ExternalServiceError(
            f"Upstream returned HTTP {response.status_code}", detail=response.text[:500]
        )
    content = response.content[:max_bytes]
    return content.decode("utf-8", "replace"), url


def fetch_url(url: str, *, max_bytes: int = 16 * 1024 * 1024) -> str:
    """Fetch an arbitrary allow-listed URL (used by 'import from URL')."""
    if not settings.external_proxy_enabled:
        raise ValidationError("Server-side fetching is disabled (EXTERNAL_PROXY_ENABLED=false)")
    _assert_public_host(url)

    import httpx

    try:
        with httpx.Client(timeout=settings.external_proxy_timeout_seconds, follow_redirects=False) as client:
            response = client.get(url, headers={"User-Agent": f"GeneForge/{settings.app_version}"})
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Upstream request failed: {exc}") from exc
    if response.status_code >= 400:
        raise ExternalServiceError(f"Upstream returned HTTP {response.status_code}")
    return response.content[:max_bytes].decode("utf-8", "replace")
