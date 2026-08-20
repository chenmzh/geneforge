"""Shared field types.

``Email`` deliberately does not use ``pydantic.EmailStr``: the underlying
``email-validator`` library rejects special-use domains such as ``.local`` and
``.internal``, which are exactly what on-premise lab deployments use (our own
default administrator is ``admin@geneforge.local``).  This validator is strict
about syntax but agnostic about deliverability.
"""
from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

_LOCAL_PART = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_EMAIL_RE = re.compile(rf"^{_LOCAL_PART}@{_LABEL}(?:\.{_LABEL})*$")


def validate_email_address(value: str) -> str:
    value = value.strip()
    if len(value) > 254:
        raise ValueError("Email address is too long")
    if not _EMAIL_RE.match(value):
        raise ValueError("Not a valid email address")
    local, _, domain = value.rpartition("@")
    if len(local) > 64:
        raise ValueError("Email local part is too long")
    if ".." in value:
        raise ValueError("Email address contains consecutive dots")
    return f"{local}@{domain.lower()}"


Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=254),
    AfterValidator(validate_email_address),
]
