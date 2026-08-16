"""Safe, renderer-friendly origin resolution.

The reverse proxy must never use a user-controlled hostname as an unchecked
runtime DNS target.  This module resolves every address first, rejects the
entire answer set if any address is unsafe, and returns only canonical IP
addresses that a renderer can pin in an upstream block.

The resolver is injectable so callers can use a platform-specific resolver and
tests can model DNS rebinding without touching real DNS.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlsplit


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], Iterable[str | IPAddress]]

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Keep this explicit as well as consulting ``ipaddress``.  Classification of a
# few IANA special-purpose ranges has changed between supported Python patch
# releases, while the proxy must fail closed consistently on every distro.
_SPECIAL_USE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/96",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/32",
        "2001:2::/48",
        "2001:10::/28",
        "2001:20::/28",
        "2001:db8::/32",
        "3fff::/20",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


class OriginSecurityError(ValueError):
    """An origin cannot be used without crossing a security boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalise_hostname(value: str) -> str:
    host = str(value).strip().rstrip(".")
    if not host or "%" in host:
        raise ValueError("invalid hostname")

    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        pass

    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid hostname") from exc
    if len(ascii_host) > 253:
        raise ValueError("hostname is too long")
    labels = ascii_host.split(".")
    if any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise ValueError("invalid hostname")
    return ascii_host


def _normalise_domain(value: str) -> str:
    domain = _normalise_hostname(value)
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError("an owned domain must be a DNS name")


def _normalise_policy_address(value: str | IPAddress) -> str:
    text = str(value)
    if "%" in text:
        raise ValueError("scoped addresses are not allowed in policy")
    return ipaddress.ip_address(text).compressed.lower()


@dataclass(frozen=True, slots=True)
class OriginSecurityPolicy:
    """Names and addresses that an origin is never allowed to reach.

    ``owned_domains`` rejects both the zone itself and every subdomain.  It
    should contain the panel domain and every generated proxy/node zone.
    ``protected_hosts`` is for exact hostnames outside those zones.
    ``node_addresses`` and ``proxy_addresses`` stop aliases from resolving back
    to this deployment and creating a proxy loop.
    """

    owned_domains: tuple[str, ...] = ()
    protected_hosts: tuple[str, ...] = ()
    node_addresses: tuple[str | IPAddress, ...] = ()
    proxy_addresses: tuple[str | IPAddress, ...] = ()
    allowed_schemes: tuple[str, ...] = ("https",)
    max_addresses: int = 32
    max_resolver_answers: int = 256

    def __post_init__(self) -> None:
        try:
            domains = tuple(sorted({_normalise_domain(item) for item in self.owned_domains}))
            hosts = tuple(sorted({_normalise_hostname(item) for item in self.protected_hosts}))
            node_addresses = tuple(sorted({_normalise_policy_address(item) for item in self.node_addresses}))
            proxy_addresses = tuple(sorted({_normalise_policy_address(item) for item in self.proxy_addresses}))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid origin security policy") from exc

        schemes = tuple(dict.fromkeys(str(item).lower() for item in self.allowed_schemes))
        if not schemes or any(item not in {"http", "https"} for item in schemes):
            raise ValueError("allowed_schemes must contain http and/or https")
        if not 1 <= int(self.max_addresses) <= 256:
            raise ValueError("max_addresses must be between 1 and 256")
        if not int(self.max_addresses) <= int(self.max_resolver_answers) <= 4096:
            raise ValueError("max_resolver_answers must be between max_addresses and 4096")

        object.__setattr__(self, "owned_domains", domains)
        object.__setattr__(self, "protected_hosts", hosts)
        object.__setattr__(self, "node_addresses", node_addresses)
        object.__setattr__(self, "proxy_addresses", proxy_addresses)
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "max_addresses", int(self.max_addresses))
        object.__setattr__(self, "max_resolver_answers", int(self.max_resolver_answers))


@dataclass(frozen=True, slots=True)
class SafeOriginResolution:
    """A fully validated origin and the IPs a proxy renderer may use."""

    origin: str
    scheme: str
    hostname: str
    port: int
    authority: str
    addresses: tuple[str, ...]

    @property
    def upstream_endpoints(self) -> tuple[str, ...]:
        endpoints = []
        for address in self.addresses:
            parsed = ipaddress.ip_address(address)
            host = f"[{parsed.compressed}]" if parsed.version == 6 else parsed.compressed
            endpoints.append(f"{host}:{self.port}")
        return tuple(endpoints)

    def renderer_context(self) -> dict[str, object]:
        """Return a JSON-serialisable, configuration-renderer-safe payload."""

        return {
            "origin": self.origin,
            "scheme": self.scheme,
            "hostname": self.hostname,
            "authority": self.authority,
            "port": self.port,
            "addresses": self.addresses,
            "upstream_endpoints": self.upstream_endpoints,
            "host_header": self.authority,
            "tls_server_name": self.hostname,
        }


def system_resolver(hostname: str) -> tuple[str, ...]:
    """Resolve all A/AAAA answers exposed by the system resolver."""

    results = socket.getaddrinfo(
        hostname,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(item[4][0] for item in results)


def is_global_unicast(address: str | IPAddress) -> bool:
    """Return true only for an ordinary globally routable unicast address."""

    try:
        text = str(address)
        if "%" in text:
            return False
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return False

    if any(parsed.version == network.version and parsed in network for network in _SPECIAL_USE_NETWORKS):
        return False

    return bool(
        parsed.is_global
        and not parsed.is_private
        and not parsed.is_loopback
        and not parsed.is_link_local
        and not parsed.is_multicast
        and not parsed.is_reserved
        and not parsed.is_unspecified
    )


def _host_is_protected(hostname: str, policy: OriginSecurityPolicy) -> bool:
    if hostname in policy.protected_hosts:
        return True
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in policy.owned_domains
    )


def validate_resolved_addresses(
    hostname: str,
    answers: Iterable[str | IPAddress],
    policy: OriginSecurityPolicy,
) -> tuple[str, ...]:
    """Validate a complete DNS answer set and return canonical, sorted IPs.

    The whole set is rejected when it contains both public and non-public
    addresses.  Silently keeping only the public subset would leave callers
    exposed to resolver ordering changes and DNS rebinding.
    """

    canonical: dict[str, IPAddress] = {}
    answer_count = 0
    for answer in answers:
        answer_count += 1
        if answer_count > policy.max_resolver_answers:
            raise OriginSecurityError("too-many-answers", "origin returned too many DNS answers")
        text = str(answer)
        if "%" in text:
            raise OriginSecurityError("invalid-address", "origin returned a scoped address")
        try:
            parsed = ipaddress.ip_address(text)
        except ValueError as exc:
            raise OriginSecurityError("invalid-address", "origin returned an invalid address") from exc
        canonical[parsed.compressed.lower()] = parsed

    if not canonical:
        raise OriginSecurityError("no-addresses", f"{hostname} did not resolve to an A or AAAA address")
    if len(canonical) > policy.max_addresses:
        raise OriginSecurityError("too-many-addresses", "origin returned too many unique addresses")

    protected = set(policy.node_addresses) | set(policy.proxy_addresses)
    protected_hits = [address for address in canonical if address in protected]
    if protected_hits:
        raise OriginSecurityError("proxy-loop", "origin resolves to this panel or one of its nodes")

    safe = [address for address, parsed in canonical.items() if is_global_unicast(parsed)]
    unsafe = [address for address, parsed in canonical.items() if not is_global_unicast(parsed)]
    if safe and unsafe:
        raise OriginSecurityError(
            "mixed-address-space",
            "origin mixes globally routable and non-global addresses",
        )
    if unsafe:
        raise OriginSecurityError("non-global-address", "origin resolves to a non-global address")

    return tuple(
        address
        for address, _ in sorted(
            canonical.items(),
            key=lambda item: (item[1].version, int(item[1])),
        )
    )


def resolve_origin_safely(
    origin: str,
    *,
    policy: OriginSecurityPolicy | None = None,
    resolver: Resolver = system_resolver,
) -> SafeOriginResolution:
    """Parse and resolve an origin into a safe, pinned renderer input."""

    selected_policy = policy or OriginSecurityPolicy()
    raw_origin = str(origin).strip()
    if not raw_origin or any(ord(character) < 32 for character in raw_origin):
        raise OriginSecurityError("invalid-origin", "origin is empty or contains control characters")

    try:
        parsed = urlsplit(raw_origin)
        port = parsed.port
    except ValueError as exc:
        raise OriginSecurityError("invalid-origin", "origin contains an invalid port or host") from exc

    scheme = parsed.scheme.lower()
    if scheme not in selected_policy.allowed_schemes:
        raise OriginSecurityError("scheme-not-allowed", "origin scheme is not allowed")
    if not parsed.netloc or not parsed.hostname:
        raise OriginSecurityError("invalid-origin", "origin must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise OriginSecurityError("userinfo-not-allowed", "origin must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise OriginSecurityError("origin-components-not-allowed", "origin must not contain a path, query, or fragment")

    try:
        hostname = _normalise_hostname(parsed.hostname)
    except ValueError as exc:
        raise OriginSecurityError("invalid-origin", "origin hostname is invalid") from exc
    if _host_is_protected(hostname, selected_policy):
        raise OriginSecurityError("owned-origin", "origin belongs to this proxy deployment")

    selected_port = port if port is not None else (443 if scheme == "https" else 80)
    if not 1 <= selected_port <= 65535:
        raise OriginSecurityError("invalid-origin", "origin port is out of range")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            answers = resolver(hostname)
            addresses = validate_resolved_addresses(hostname, answers, selected_policy)
        except OriginSecurityError:
            raise
        except (OSError, socket.gaierror, TimeoutError) as exc:
            raise OriginSecurityError("resolution-failed", "origin DNS resolution failed") from exc
        except Exception as exc:
            raise OriginSecurityError("resolution-failed", "origin resolver failed") from exc
    else:
        addresses = validate_resolved_addresses(hostname, (literal,), selected_policy)

    is_ipv6_literal = False
    try:
        is_ipv6_literal = ipaddress.ip_address(hostname).version == 6
    except ValueError:
        pass
    authority_host = f"[{hostname}]" if is_ipv6_literal else hostname
    default_port = 443 if scheme == "https" else 80
    authority = authority_host if selected_port == default_port else f"{authority_host}:{selected_port}"
    normalised_origin = f"{scheme}://{authority}"

    return SafeOriginResolution(
        origin=normalised_origin,
        scheme=scheme,
        hostname=hostname,
        port=selected_port,
        authority=authority,
        addresses=addresses,
    )


__all__ = [
    "OriginSecurityError",
    "OriginSecurityPolicy",
    "Resolver",
    "SafeOriginResolution",
    "is_global_unicast",
    "resolve_origin_safely",
    "system_resolver",
    "validate_resolved_addresses",
]
