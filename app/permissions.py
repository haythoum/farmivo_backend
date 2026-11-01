"""Roles and the permission policy, enforced for every farm request in ``deps.get_ctx``.

Roles, from most to least powerful: owner > manager > worker > viewer.

The policy is one function, :func:`required_role`, that maps an HTTP method and path to the lowest role
allowed to call it. Keeping it in one place means a new route is protected automatically and the whole
policy can be read (and tested) at a glance. See docs/ROLES_AND_MEMBERS.md for the matrix.
"""
from __future__ import annotations

ROLES = ("owner", "manager", "worker", "viewer")
RANK = {"owner": 4, "manager": 3, "worker": 2, "viewer": 1}

# Paths (relative to /v1) that only managers and the owner may use, whatever the method.
_MANAGER_PREFIXES = ("/transactions", "/finance", "/reports/financial", "/farm/members", "/farm/invite-code")


def at_least(role: str | None, minimum: str) -> bool:
    """True if ``role`` is ``minimum`` or a more powerful role."""
    return RANK.get(role or "", 0) >= RANK[minimum]


def can_see_finance(role: str | None) -> bool:
    """Finance (transactions, totals, financial report, dashboard finance) is for managers and the owner."""
    return at_least(role, "manager")


def required_role(method: str, path: str) -> str:
    """Lowest role allowed to call ``method path`` (path with or without the /v1 prefix).

    - owner only: transferring ownership
    - manager+: finance, financial report, members and invite code, farm settings (PATCH /farm), any DELETE
      of farm records (except notifications)
    - worker+: creating and editing records (POST/PATCH), deleting notifications
    - viewer+: reading (GET) everything else, marking notifications read
    """
    p = path[3:] if path.startswith("/v1/") else path
    method = method.upper()
    if p.startswith("/farm/transfer-ownership"):
        return "owner"
    if p.startswith(_MANAGER_PREFIXES):
        return "manager"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "viewer"
    if p.startswith("/notifications"):
        if p.endswith("/read") or p.endswith("/read-all"):
            return "viewer"
        return "worker"  # deleting a notification from the farm's list
    if p == "/farm":
        return "manager"  # PATCH /farm: farm settings
    if method == "DELETE":
        return "manager"
    return "worker"
