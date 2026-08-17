#!/usr/bin/env python3
"""Canonical, security-focused Nginx route renderer for emby-relay-panel.

The renderer deliberately does not resolve an upstream name while serving a
request.  Callers must resolve and validate every address first, then pass the
resulting public IP addresses in ``RouteSpec.upstream_ips``.  This keeps DNS
changes from silently turning an existing route into an internal-network
proxy.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit


RENDERER_VERSION = 3
DEFAULT_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SAFE_LOG_FORMAT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SAFE_ABSOLUTE_PATH = re.compile(r"^/[A-Za-z0-9._/@+:-]+(?:/[A-Za-z0-9._/@+:-]+)*$")

REQUEST_HEADERS_TO_DROP = (
    "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Port", "X-Forwarded-Proto",
    "X-Real-IP", "Forwarded", "Via", "CF-Connecting-IP", "CF-IPCountry", "CF-Ray",
    "CF-Visitor", "CDN-Loop", "True-Client-IP", "Client-IP", "Fastly-Client-IP",
    "Proxy-Client-IP", "WL-Proxy-Client-IP", "X-Client-IP", "X-Cluster-Client-IP",
    "X-Originating-IP", "X-Remote-Addr", "X-Remote-IP", "X-Original-Forwarded-For",
    "X-Envoy-External-Address", "X-Appengine-User-IP", "Fly-Client-IP",
    "X-Vercel-Forwarded-For", "Proxy-Authorization", "Proxy-Connection", "Keep-Alive",
    "TE", "Trailer", "Sec-WebSocket-Origin",
)

RESPONSE_HEADERS_TO_DROP = (
    "Alt-Svc", "CF-Cache-Status", "CF-Ray", "NEL", "Report-To", "Server",
    "Speculation-Rules", "Via", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version",
    "X-Backend-Server", "X-Cache", "X-Cache-Hits", "X-Runtime", "X-Served-By", "X-Timer",
    # A response from an untrusted sibling route must not clear parent-domain cookies/storage.
    "Clear-Site-Data",
)


class RendererError(ValueError):
    """Raised when a route cannot be rendered without weakening the policy."""


@dataclass(frozen=True)
class ParsedOrigin:
    scheme: str
    hostname: str
    port: int
    authority: str
    value: str


@dataclass(frozen=True)
class RedirectSpec:
    """Optional fixed-host media redirect relay.

    ``token`` must be random and independent from administrator credentials.
    The redirect host is pinned to the already validated ``upstream_ips``.
    """

    hostname: str
    upstream_ips: tuple[str, ...]
    token: str
    port: int = 443
    ca_bundle: str | None = None


@dataclass(frozen=True)
class RouteSpec:
    origin: str
    public_host: str
    upstream_ips: tuple[str, ...]
    tls_cert_file: str
    tls_key_file: str
    public_https_port: int = 443
    internal_https_port: int = 443
    ca_bundle: str = DEFAULT_CA_BUNDLE
    allow_insecure_http: bool = False
    traffic_log_path: str | None = None
    traffic_log_format: str = "unirelay_traffic"
    error_log_path: str = "/var/log/unirelay-route-error.log"
    redirect: RedirectSpec | None = None
    connect_timeout_seconds: int = 10
    stream_timeout_seconds: int = 3600


def _validated_dns_name(value: str, field: str) -> str:
    hostname = value.lower().rstrip(".")
    if not hostname or len(hostname) > 253:
        raise RendererError(f"{field} is not a valid DNS hostname")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RendererError(f"{field} is not a valid DNS hostname") from exc
    if len(hostname) > 253:
        raise RendererError(f"{field} is not a valid DNS hostname")
    labels = hostname.split(".")
    if any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise RendererError(f"{field} is not a valid DNS hostname")
    return hostname


def _validated_origin_host(value: str) -> str:
    candidate = value.rstrip(".")
    try:
        return ipaddress.ip_address(candidate.strip("[]")).compressed
    except ValueError:
        return _validated_dns_name(candidate, "origin hostname")


def _authority(hostname: str, port: int, default_port: int) -> str:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        rendered_host = hostname
    else:
        rendered_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return rendered_host if port == default_port else f"{rendered_host}:{port}"


def parse_origin(value: str, *, allow_insecure_http: bool = False) -> ParsedOrigin:
    raw = value.strip()
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise RendererError("origin contains a control character")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise RendererError("origin contains an invalid port") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise RendererError("origin must be an absolute HTTP(S) origin")
    if scheme != "https" and not allow_insecure_http:
        raise RendererError("insecure HTTP origins are disabled")
    if parsed.username is not None or parsed.password is not None:
        raise RendererError("origin userinfo is not allowed")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RendererError("origin must not contain a path, query, or fragment")
    hostname = _validated_origin_host(parsed.hostname)
    default_port = 443 if scheme == "https" else 80
    port = port or default_port
    if not 1 <= port <= 65535:
        raise RendererError("origin port is outside 1-65535")
    authority = _authority(hostname, port, default_port)
    return ParsedOrigin(scheme, hostname, port, authority, f"{scheme}://{authority}")


def normalize_origin(value: str, *, allow_insecure_http: bool = False) -> str:
    return parse_origin(value, allow_insecure_http=allow_insecure_http).value


def normalize_public_host(value: str) -> str:
    """Return a canonical DNS server name suitable for ``server_name``."""
    return _validated_dns_name(str(value).strip().rstrip("."), "public host")


def _validated_public_ips(values: Iterable[str], field: str = "upstream") -> tuple[str, ...]:
    result: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for raw in values:
        try:
            address = ipaddress.ip_address(str(raw).strip().strip("[]"))
        except ValueError as exc:
            raise RendererError(f"{field} contains an invalid IP address") from exc
        if not address.is_global:
            raise RendererError(f"{field} address {address.compressed} is not globally routable")
        result.add(address)
    if not result:
        raise RendererError(f"{field} has no validated public IP address")
    if len(result) > 8:
        raise RendererError(f"{field} has more than 8 addresses")
    ordered = sorted(result, key=lambda item: (item.version, int(item)))
    return tuple(item.compressed for item in ordered)


def resolve_public_upstream_ips(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve once and fail closed if any answer is not globally routable."""
    normalized_host = _validated_origin_host(hostname)
    try:
        direct = ipaddress.ip_address(normalized_host)
    except ValueError:
        direct = None
    if direct is not None:
        return _validated_public_ips((direct.compressed,))
    try:
        answers = socket.getaddrinfo(normalized_host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise RendererError(f"cannot resolve upstream hostname {normalized_host}") from exc
    addresses = tuple(str(answer[4][0]).split("%", 1)[0] for answer in answers)
    return _validated_public_ips(addresses)


def _validated_path(value: str, field: str) -> str:
    if not _SAFE_ABSOLUTE_PATH.fullmatch(value):
        raise RendererError(f"{field} must be a safe absolute path")
    return value


def _validated_port(value: int, field: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise RendererError(f"{field} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RendererError(f"{field} is outside 1-65535")
    return port


def _validated_timeout(value: int, field: str, maximum: int) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise RendererError(f"{field} must be an integer") from exc
    if not 1 <= timeout <= maximum:
        raise RendererError(f"{field} is outside the supported range")
    return timeout


def _nginx_string(value: str) -> str:
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise RendererError("Nginx value contains a control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _upstream_address(address: str, port: int) -> str:
    parsed = ipaddress.ip_address(address)
    host = f"[{parsed.compressed}]" if parsed.version == 6 else parsed.compressed
    return f"{host}:{port}"


def _public_origin_pattern(public_host: str, public_port: int) -> str:
    base = re.escape(f"https://{public_host}")
    return base + (r"(?::443)?" if public_port == 443 else re.escape(f":{public_port}"))


def _backend_lines(name: str, addresses: tuple[str, ...], port: int) -> list[str]:
    lines = [f"upstream {name} {{"]
    lines.extend(
        f"    server {_upstream_address(address, port)} max_fails=2 fail_timeout=10s;"
        for address in addresses
    )
    lines.extend(("    keepalive 64;", "}", ""))
    return lines


def _proxy_security_lines(
    *,
    origin: ParsedOrigin,
    backend_name: str,
    origin_ok_variable: str,
    mapped_origin_variable: str,
    mapped_referer_variable: str,
    upgrade_variable: str,
    connection_variable: str,
    ca_bundle: str,
    next_upstream_tries: int,
    connect_timeout: int,
    stream_timeout: int,
) -> list[str]:
    lines = [
        f"        if ({origin_ok_variable} = 0) {{ return 403; }}",
        f"        proxy_pass {origin.scheme}://{backend_name};",
        "        proxy_http_version 1.1;",
        f"        proxy_set_header Host {_nginx_string(origin.authority)};",
    ]
    if origin.scheme == "https":
        lines.extend((
            "        proxy_ssl_server_name on;",
            f"        proxy_ssl_name {_nginx_string(origin.hostname)};",
            "        proxy_ssl_protocols TLSv1.2 TLSv1.3;",
            "        proxy_ssl_session_reuse on;",
            "        proxy_ssl_verify on;",
            "        proxy_ssl_verify_depth 5;",
            f"        proxy_ssl_trusted_certificate {_nginx_string(ca_bundle)};",
        ))
    lines.extend((
        f"        proxy_set_header Upgrade {upgrade_variable};",
        f"        proxy_set_header Connection {connection_variable};",
        "        proxy_set_header Range $http_range;",
        "        proxy_set_header If-Range $http_if_range;",
        "        proxy_set_header Accept-Encoding $http_accept_encoding;",
    ))
    lines.extend(f"        proxy_set_header {name} \"\";" for name in REQUEST_HEADERS_TO_DROP)
    lines.extend((
        f"        proxy_set_header Origin {mapped_origin_variable};",
        f"        proxy_set_header Referer {mapped_referer_variable};",
    ))
    lines.extend(f"        proxy_hide_header {name};" for name in RESPONSE_HEADERS_TO_DROP)
    lines.extend((
        "        proxy_cookie_domain ~(?i)^\\.?.+$ $host;",
        "        proxy_buffering off;",
        "        proxy_request_buffering off;",
        "        proxy_max_temp_file_size 0;",
        "        proxy_force_ranges on;",
        "        proxy_socket_keepalive on;",
        f"        proxy_connect_timeout {connect_timeout}s;",
        f"        proxy_read_timeout {stream_timeout}s;",
        f"        proxy_send_timeout {stream_timeout}s;",
        f"        send_timeout {stream_timeout}s;",
        "        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;",
        f"        proxy_next_upstream_tries {next_upstream_tries};",
        "        proxy_next_upstream_timeout 20s;",
    ))
    return lines


def render_route(spec: RouteSpec) -> str:
    origin = parse_origin(spec.origin, allow_insecure_http=spec.allow_insecure_http)
    public_host = normalize_public_host(spec.public_host)
    public_port = _validated_port(spec.public_https_port, "public HTTPS port")
    internal_port = _validated_port(spec.internal_https_port, "internal HTTPS port")
    if internal_port == 80:
        raise RendererError("internal HTTPS port cannot be 80 because HTTP redirect uses that listener")
    cert_file = _validated_path(spec.tls_cert_file, "TLS certificate")
    key_file = _validated_path(spec.tls_key_file, "TLS private key")
    ca_bundle = _validated_path(spec.ca_bundle, "CA bundle")
    error_log = _validated_path(spec.error_log_path, "error log")
    upstream_ips = _validated_public_ips(spec.upstream_ips)
    connect_timeout = _validated_timeout(spec.connect_timeout_seconds, "connect timeout", 120)
    stream_timeout = _validated_timeout(spec.stream_timeout_seconds, "stream timeout", 86400)
    if spec.traffic_log_path is not None:
        traffic_log = _validated_path(spec.traffic_log_path, "traffic log")
        if not _SAFE_LOG_FORMAT.fullmatch(spec.traffic_log_format):
            raise RendererError("traffic log format name is invalid")
    else:
        traffic_log = None

    suffix = hashlib.sha256(public_host.encode("ascii")).hexdigest()[:12]
    backend_name = f"unirelay_backend_{suffix}"
    upgrade_variable = f"$unirelay_upgrade_{suffix}"
    connection_variable = f"$unirelay_connection_{suffix}"
    origin_ok_variable = f"$unirelay_origin_ok_{suffix}"
    mapped_origin_variable = f"$unirelay_origin_{suffix}"
    mapped_referer_variable = f"$unirelay_referer_{suffix}"
    referer_capture = f"unirelay_ref_{suffix}"
    public_origin = f"https://{public_host}" if public_port == 443 else f"https://{public_host}:{public_port}"
    public_pattern = _public_origin_pattern(public_host, public_port)

    lines = [
        f"# generated by emby-relay-panel renderer v{RENDERER_VERSION} for {origin.value}",
        f"# emby-relay-panel-renderer-version: {RENDERER_VERSION}",
        f"map $http_upgrade {upgrade_variable} {{",
        "    default \"\";",
        "    ~*^websocket$ websocket;",
        "}",
        "",
        f"map {upgrade_variable} {connection_variable} {{",
        "    default \"\";",
        "    websocket upgrade;",
        "}",
        "",
        f"map $http_origin {origin_ok_variable} {{",
        "    default 0;",
        "    \"\" 1;",
        f"    ~*^{public_pattern}$ 1;",
        "}",
        "",
        f"map $http_origin {mapped_origin_variable} {{",
        "    default \"\";",
        "    \"\" \"\";",
        f"    ~*^{public_pattern}$ {_nginx_string(origin.value)};",
        "}",
        "",
        f"map $http_referer {mapped_referer_variable} {{",
        "    default \"\";",
        "    \"\" \"\";",
        f"    ~*^{public_pattern}(?<{referer_capture}>/.*)?$ {_nginx_string(origin.value + '$' + referer_capture)};",
        "}",
        "",
    ]
    lines.extend(_backend_lines(backend_name, upstream_ips, origin.port))

    redirect_origin = None
    redirect_backend_name = ""
    redirect_prefix = ""
    redirect_ips: tuple[str, ...] = ()
    redirect_ca = ca_bundle
    if spec.redirect is not None:
        redirect_host = _validated_dns_name(spec.redirect.hostname, "redirect hostname")
        redirect_port = _validated_port(spec.redirect.port, "redirect port")
        redirect_ips = _validated_public_ips(spec.redirect.upstream_ips, "redirect upstream")
        if not _SAFE_TOKEN.fullmatch(spec.redirect.token):
            raise RendererError("redirect token must be a random URL-safe value of 16-128 characters")
        if spec.redirect.ca_bundle is not None:
            redirect_ca = _validated_path(spec.redirect.ca_bundle, "redirect CA bundle")
        redirect_authority = _authority(redirect_host, redirect_port, 443)
        redirect_origin = ParsedOrigin("https", redirect_host, redirect_port, redirect_authority, f"https://{redirect_authority}")
        redirect_backend_name = f"unirelay_redirect_{suffix}"
        redirect_prefix = f"/_unirelay_follow_{spec.redirect.token}"
        lines.extend(_backend_lines(redirect_backend_name, redirect_ips, redirect_port))

    lines.extend((
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name {public_host};",
        "    access_log off;",
        f"    return 308 {public_origin}$request_uri;",
        "}",
        "",
        "server {",
        f"    listen {internal_port} ssl;",
        f"    listen [::]:{internal_port} ssl;",
        f"    server_name {public_host};",
        f"    ssl_certificate {_nginx_string(cert_file)};",
        f"    ssl_certificate_key {_nginx_string(key_file)};",
        "    ssl_protocols TLSv1.2 TLSv1.3;",
        "    server_tokens off;",
        "    add_header Strict-Transport-Security \"max-age=31536000\" always;",
    ))
    if traffic_log is None:
        lines.append("    access_log off;")
    else:
        lines.append(
            f"    access_log {_nginx_string(traffic_log)} {spec.traffic_log_format} buffer=64k flush=5s;"
        )
    lines.extend((
        f"    error_log {_nginx_string(error_log)} crit;",
        "",
        "    location / {",
    ))
    lines.extend(_proxy_security_lines(
        origin=origin,
        backend_name=backend_name,
        origin_ok_variable=origin_ok_variable,
        mapped_origin_variable=mapped_origin_variable,
        mapped_referer_variable=mapped_referer_variable,
        upgrade_variable=upgrade_variable,
        connection_variable=connection_variable,
        ca_bundle=ca_bundle,
        next_upstream_tries=len(upstream_ips),
        connect_timeout=connect_timeout,
        stream_timeout=stream_timeout,
    ))
    lines.extend((
        f"        proxy_redirect {_nginx_string(origin.value)} {_nginx_string(public_origin)};",
        f"        proxy_redirect ~*^//{re.escape(origin.authority)}(/.*)$ {public_origin}$1;",
    ))
    for address in upstream_ips:
        pinned_origin = f"{origin.scheme}://{_authority(address, origin.port, 443 if origin.scheme == 'https' else 80)}"
        lines.append(f"        proxy_redirect {_nginx_string(pinned_origin)} {_nginx_string(public_origin)};")
    if redirect_origin is not None:
        lines.append(
            f"        proxy_redirect ~*^https?://{re.escape(redirect_origin.authority)}(/.*)$ "
            f"{public_origin}{redirect_prefix}$1;"
        )
    lines.extend(("    }",))

    if redirect_origin is not None:
        escaped_prefix = re.escape(redirect_prefix)
        lines.extend((
            "",
            f"    location = {redirect_prefix} {{ return 404; }}",
            f"    location ^~ {redirect_prefix}/ {{",
            f"        rewrite ^{escaped_prefix}(/.*)$ $1 break;",
        ))
        lines.extend(_proxy_security_lines(
            origin=redirect_origin,
            backend_name=redirect_backend_name,
            origin_ok_variable=origin_ok_variable,
            mapped_origin_variable=mapped_origin_variable,
            mapped_referer_variable=mapped_referer_variable,
            upgrade_variable=upgrade_variable,
            connection_variable=connection_variable,
            ca_bundle=redirect_ca,
            next_upstream_tries=len(redirect_ips),
            connect_timeout=connect_timeout,
            stream_timeout=stream_timeout,
        ))
        lines.extend((
            f"        proxy_redirect {_nginx_string(redirect_origin.value)} "
            f"{_nginx_string(public_origin + redirect_prefix)};",
            f"        proxy_redirect ~*^//{re.escape(redirect_origin.authority)}(/.*)$ "
            f"{public_origin}{redirect_prefix}$1;",
            "    }",
        ))

    lines.extend(("}", ""))
    return "\n".join(lines)
