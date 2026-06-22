"""
PrescpHealth Backend — Per-Tenant IP Allowlist.

Provides configurable IP restriction on a per-tenant basis. By default,
all IPs are allowed (no restriction). Tenants can configure an allowlist
through admin settings to restrict API access to specific IPs/ranges.

Use cases:
- Clinic with fixed IP range restricts access to their network only
- Hospital blocks access from outside their VPN
- Default (empty allowlist): no restriction, all IPs pass

Design Decisions:
- Permissive by default: empty allowlist = all IPs allowed
- Per-tenant: each tenant independently configures their restrictions
- Exact match: compares client IP string against allowed list
- No CIDR support yet (keep simple, add later if needed)

HIPAA NOTE:
    IP restriction is an additional access control layer. Combined with
    JWT auth and MFA, it provides defense-in-depth per the Security Rule.
"""

from __future__ import annotations

from uuid import UUID


class IPAllowlist:
    """
    Per-tenant IP allowlist for restricting API access.

    Stores a mapping of tenant_id -> set of allowed IP strings.
    Tenants with no configured allowlist allow ALL IPs (permissive default).

    Usage:
        allowlist = IPAllowlist()
        allowlist.set_allowed_ips(tenant_id, {"192.168.1.0", "10.0.0.1"})
        if not allowlist.is_allowed("203.0.113.50", tenant_id):
            raise ForbiddenError("IP not in allowlist")
    """

    def __init__(self) -> None:
        """Initialize with empty allowlist (all IPs allowed for all tenants)."""
        self._allowlists: dict[UUID, set[str]] = {}

    def is_allowed(self, ip: str, tenant_id: UUID) -> bool:
        """
        Check if an IP address is allowed for a given tenant.

        Rules:
        - If tenant has NO configured allowlist: ALL IPs are allowed
        - If tenant has an allowlist: only listed IPs pass

        Args:
            ip: The client's IP address string (e.g., "192.168.1.100").
            tenant_id: The tenant UUID to check against.

        Returns:
            bool: True if the IP is allowed, False if blocked.
        """
        allowed_ips = self._allowlists.get(tenant_id)

        # No allowlist configured = permissive (all IPs pass)
        if allowed_ips is None or len(allowed_ips) == 0:
            return True

        return ip in allowed_ips

    def set_allowed_ips(self, tenant_id: UUID, ips: set[str]) -> None:
        """
        Configure the allowed IP set for a tenant.

        Pass an empty set to remove restrictions (allow all IPs).

        Args:
            tenant_id: The tenant to configure.
            ips: Set of allowed IP address strings.
        """
        if ips:
            self._allowlists[tenant_id] = ips
        else:
            self._allowlists.pop(tenant_id, None)

    def clear_tenant(self, tenant_id: UUID) -> None:
        """
        Remove all IP restrictions for a tenant (revert to allow-all).

        Args:
            tenant_id: The tenant whose restrictions to clear.
        """
        self._allowlists.pop(tenant_id, None)

    def get_allowed_ips(self, tenant_id: UUID) -> set[str]:
        """
        Get the current allowed IPs for a tenant.

        Returns empty set if no restrictions are configured.

        Args:
            tenant_id: The tenant to query.

        Returns:
            set[str]: Set of allowed IPs, or empty set if unrestricted.
        """
        return self._allowlists.get(tenant_id, set())
