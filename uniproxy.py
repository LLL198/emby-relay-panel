#!/usr/bin/env python3
import asyncio
import base64
import hashlib
import html
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
from urllib.parse import parse_qs, urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web


TOKEN = os.environ["PROXY_TOKEN"].strip("/")
COOKIE_NAME = "_uniproxy_origin"
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8787"))
DEFAULT_TARGET_ORIGIN = os.environ.get("DEFAULT_TARGET_ORIGIN", "").rstrip("/")
PROXY_DOMAIN_SUFFIX = os.environ.get("PROXY_DOMAIN_SUFFIX", "sh.996878.xyz").lower().strip(".")
PUBLIC_HTTPS_PORT = int(os.environ.get("PUBLIC_HTTPS_PORT", "443"))
PUBLIC_HTTP_PORT = int(os.environ.get("PUBLIC_HTTP_PORT", "80"))
GENERATED_NGINX_DIR = os.environ.get("GENERATED_NGINX_DIR", "/etc/nginx/conf.d")
TLS_CERT_FILE = os.environ.get("TLS_CERT_FILE", "/etc/letsencrypt/live/sh.996878.xyz/fullchain.pem")
TLS_KEY_FILE = os.environ.get("TLS_KEY_FILE", "/etc/letsencrypt/live/sh.996878.xyz/privkey.pem")
SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
SAFE_SLUG_RE = re.compile(r"[^a-z0-9-]+")
SAFE_REDIRECT_TARGETS = {
    "video.emos.best": "proxy.emosstore.sbs",
}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
REQUEST_HEADERS_TO_DROP = {
    "client-ip",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cf-ray",
    "cf-visitor",
    "cdn-loop",
    "fastly-client-ip",
    "forwarded",
    "proxy-client-ip",
    "true-client-ip",
    "via",
    "wl-proxy-client-ip",
    "x-client-ip",
    "x-cluster-client-ip",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
    "x-originating-ip",
    "x-remote-addr",
    "x-remote-ip",
    "x-real-ip",
}
RESPONSE_HEADERS_TO_DROP = {
    "alt-svc",
    "cf-cache-status",
    "cf-ray",
    "date",
    "nel",
    "report-to",
    "server",
    "speculation-rules",
    "via",
    "x-aspnet-version",
    "x-aspnetmvc-version",
    "x-backend-server",
    "x-cache",
    "x-cache-hits",
    "x-powered-by",
    "x-runtime",
    "x-served-by",
    "x-timer",
}

NGINX_REQUEST_HEADERS_TO_DROP = (
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Port",
    "X-Forwarded-Proto",
    "X-Real-IP",
    "Forwarded",
    "Via",
    "CF-Connecting-IP",
    "CF-IPCountry",
    "CF-Ray",
    "CF-Visitor",
    "CDN-Loop",
    "True-Client-IP",
    "Client-IP",
    "Fastly-Client-IP",
    "Proxy-Client-IP",
    "WL-Proxy-Client-IP",
    "X-Client-IP",
    "X-Cluster-Client-IP",
    "X-Originating-IP",
    "X-Remote-Addr",
    "X-Remote-IP",
)

NGINX_RESPONSE_HEADERS_TO_DROP = (
    "Alt-Svc",
    "CF-Cache-Status",
    "CF-Ray",
    "NEL",
    "Report-To",
    "Server",
    "Speculation-Rules",
    "Via",
    "X-Powered-By",
    "X-AspNet-Version",
    "X-AspNetMvc-Version",
    "X-Backend-Server",
    "X-Cache",
    "X-Cache-Hits",
    "X-Runtime",
    "X-Served-By",
    "X-Timer",
)


def sign_origin(origin: str) -> str:
    sig = hmac.new(TOKEN.encode(), origin.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(origin.encode()).decode().rstrip("=") + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def unsign_origin(value: str) -> str | None:
    try:
        raw_origin, raw_sig = value.split(".", 1)
        origin = base64.urlsafe_b64decode(raw_origin + "=" * (-len(raw_origin) % 4)).decode()
        sig = base64.urlsafe_b64decode(raw_sig + "=" * (-len(raw_sig) % 4))
    except Exception:
        return None

    expected = hmac.new(TOKEN.encode(), origin.encode(), hashlib.sha256).digest()
    return origin if hmac.compare_digest(sig, expected) else None


def is_global_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    addrs = {item[4][0] for item in infos}
    if not addrs:
        return False
    return all(ipaddress.ip_address(addr).is_global for addr in addrs)


def clean_headers(headers, target):
    outgoing = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in REQUEST_HEADERS_TO_DROP or lower == "host":
            continue
        outgoing[key] = value

    host = target.hostname or ""
    if target.port:
        host = f"{host}:{target.port}"
    outgoing["Host"] = host
    return outgoing


def encode_origin(origin: str) -> str:
    encoded = base64.b32encode(origin.encode()).decode().lower().rstrip("=")
    return f"u-{encoded}"


def decode_origin(label: str) -> str | None:
    if not label.startswith("u-"):
        return None
    raw = label[2:].upper()
    try:
        return base64.b32decode(raw + "=" * (-len(raw) % 8)).decode()
    except Exception:
        return None


def friendly_origin_from_label(label: str) -> str | None:
    if label.startswith("u-") or "--" not in label:
        return None
    host = label.replace("--", ".")
    if not host or host.startswith(".") or host.endswith("."):
        return None
    return "https://" + host


def proxied_origin_from_host(host_header: str) -> str | None:
    host = host_header.split(":", 1)[0].lower().strip(".")
    suffix = "." + PROXY_DOMAIN_SUFFIX
    if not host.endswith(suffix):
        return None

    label = host[: -len(suffix)]
    if "." in label or not label:
        return None
    return decode_origin(label) or friendly_origin_from_label(label)


def proxied_host_for_origin(origin: str) -> str:
    return f"{encode_origin(origin)}.{PROXY_DOMAIN_SUFFIX}"


def normalized_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("bad origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("userinfo is not allowed")

    hostname = parsed.hostname.lower().rstrip(".")
    if not SAFE_HOST_RE.match(hostname):
        raise ValueError("bad host")
    port = parsed.port
    if port and not (1 <= port <= 65535):
        raise ValueError("bad port")

    default_port = 443 if scheme == "https" else 80
    netloc = hostname if not port or port == default_port else f"{hostname}:{port}"
    return f"{scheme}://{netloc}"


def slug_from_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    host = (parsed.hostname or "emby").lower()
    parts = [part for part in host.split(".") if part and part not in {"www", "emby", "jellyfin"}]
    base = parts[0] if parts else host.split(".")[0]
    base = SAFE_SLUG_RE.sub("-", base).strip("-") or "emby"
    if len(base) < 3:
        base = "emby-" + base
    return base[:24].strip("-") or "emby"


def public_urls_for_host(host: str):
    https_authority = host if PUBLIC_HTTPS_PORT == 443 else f"{host}:{PUBLIC_HTTPS_PORT}"
    http_authority = host if PUBLIC_HTTP_PORT == 80 else f"{host}:{PUBLIC_HTTP_PORT}"
    return (
        f"https://{https_authority}/",
        f"http://{http_authority}/",
        host,
    )


def public_urls_for_origin(origin: str):
    return public_urls_for_host(proxied_host_for_origin(origin))


def nginx_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_nginx_mapping(origin: str, host: str) -> str:
    parsed = urlsplit(origin)
    upstream_host = parsed.hostname or ""
    upstream_authority = parsed.netloc
    variable_suffix = hashlib.sha256(host.encode()).hexdigest()[:12]
    connection_variable = f"$uniproxy_connection_{variable_suffix}"
    upstream_variable = f"$uniproxy_upstream_{variable_suffix}"
    redirect_token = hmac.new(
        TOKEN.encode(), f"redirect:{host}".encode(), hashlib.sha256,
    ).hexdigest()[:24]
    redirect_prefix = f"/_uniproxy_follow_{redirect_token}"
    follow_uri = f"uniproxy_uri_{variable_suffix}"
    redirect_target = SAFE_REDIRECT_TARGETS.get(upstream_host.lower(), upstream_host)
    redirect_upstream = f"uniproxy_redirect_upstream_{variable_suffix}"
    public_authority = host if PUBLIC_HTTPS_PORT == 443 else f"{host}:{PUBLIC_HTTPS_PORT}"
    public_origin = f"https://{public_authority}"
    cleared_headers = "\n".join(f"        proxy_set_header {name} '';" for name in NGINX_REQUEST_HEADERS_TO_DROP)
    hidden_headers = "\n".join(f"        proxy_hide_header {name};" for name in NGINX_RESPONSE_HEADERS_TO_DROP)
    return f"""# generated by uniproxy for {origin}
map $http_upgrade {connection_variable} {{
    default upgrade;
    '' '';
}}

server {{
    listen 80;
    server_name {host};
    access_log off;
    return 301 {public_origin}$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {host};
    ssl_certificate \"{nginx_quote(TLS_CERT_FILE)}\";
    ssl_certificate_key \"{nginx_quote(TLS_KEY_FILE)}\";
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    access_log off;
    error_log /var/log/uniproxy-route-error.log crit;

    location / {{
        resolver 1.1.1.1 8.8.8.8 223.5.5.5 ipv6=off valid=300s;
        resolver_timeout 5s;
        set {upstream_variable} \"{nginx_quote(origin)}\";
        proxy_pass {upstream_variable}$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host \"{nginx_quote(upstream_authority)}\";
        proxy_ssl_server_name on;
        proxy_ssl_name \"{nginx_quote(upstream_host)}\";
        proxy_ssl_protocols TLSv1.2 TLSv1.3;
        proxy_ssl_session_reuse on;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection {connection_variable};
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_set_header Accept-Encoding $http_accept_encoding;
{cleared_headers}
        proxy_set_header Origin \"{nginx_quote(origin)}\";
        proxy_set_header Referer \"{nginx_quote(origin + '/')}\";
        proxy_redirect https://{upstream_authority} {public_origin};
        proxy_redirect http://{upstream_authority} {public_origin};
        proxy_redirect ~^https?://{re.escape(redirect_target)}(/.*)$ {public_origin}{redirect_prefix}$1;
{hidden_headers}
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_max_temp_file_size 0;
        proxy_force_ranges on;
        proxy_socket_keepalive on;
        proxy_connect_timeout 10s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        send_timeout 3600s;
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 20s;
    }}

    location ~ \"^{redirect_prefix}(?<{follow_uri}>/.*)$\" {{
        resolver 1.1.1.1 8.8.8.8 223.5.5.5 ipv6=off valid=300s;
        resolver_timeout 5s;
        set ${redirect_upstream} https://{redirect_target};
        proxy_pass ${redirect_upstream}${follow_uri}$is_args$args;
        proxy_http_version 1.1;
        proxy_set_header Host {redirect_target};
        proxy_ssl_server_name on;
        proxy_ssl_name {redirect_target};
        proxy_ssl_protocols TLSv1.2 TLSv1.3;
        proxy_ssl_session_reuse on;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection {connection_variable};
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_set_header Accept-Encoding $http_accept_encoding;
{cleared_headers}
        proxy_set_header Origin \"{nginx_quote(origin)}\";
        proxy_set_header Referer \"{nginx_quote(origin + '/')}\";
        proxy_redirect off;
{hidden_headers}
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_max_temp_file_size 0;
        proxy_force_ranges on;
        proxy_socket_keepalive on;
        proxy_connect_timeout 10s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        send_timeout 3600s;
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 20s;
    }}
}}
"""


def ensure_nginx_mapping(origin: str) -> str:
    os.makedirs(GENERATED_NGINX_DIR, exist_ok=True)
    slug = slug_from_origin(origin)
    host = ""
    filename = ""
    for index in range(1, 1000):
        candidate_slug = slug if index == 1 else f"{slug}{index}"
        candidate_host = f"{candidate_slug}.{PROXY_DOMAIN_SUFFIX}"
        candidate_filename = os.path.join(GENERATED_NGINX_DIR, candidate_host + ".conf")
        if not os.path.exists(candidate_filename):
            host = candidate_host
            filename = candidate_filename
            break
        with open(candidate_filename, "r", encoding="utf-8", errors="ignore") as existing:
            if f"# generated by uniproxy for {origin}\n" in existing.read(300):
                host = candidate_host
                filename = candidate_filename
                break
    if not host or not host.endswith("." + PROXY_DOMAIN_SUFFIX):
        raise ValueError("unable to allocate proxy host")

    tmp_filename = filename + ".tmp"
    content = render_nginx_mapping(origin, host)

    with open(tmp_filename, "w", encoding="utf-8") as file:
        file.write(content)
    os.replace(tmp_filename, filename)

    validate = subprocess.run(["/usr/sbin/nginx", "-t", "-c", "/etc/nginx/nginx.conf"], capture_output=True, text=True)
    if validate.returncode != 0:
        try:
            os.remove(filename)
        except FileNotFoundError:
            pass
        raise RuntimeError(validate.stderr or validate.stdout or "nginx validate failed")

    reload_cmd = subprocess.run(["/bin/systemctl", "reload", "nginx"], capture_output=True, text=True)
    if reload_cmd.returncode != 0:
        raise RuntimeError(reload_cmd.stderr or reload_cmd.stdout or "nginx reload failed")
    return host


def curl_check(name: str, url: str, resolve_host: str | None = None) -> dict:
    command = [
        "/usr/bin/curl",
        "-L",
        "-sS",
        "-o",
        "/dev/null",
        "-A",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "--connect-timeout",
        "8",
        "--max-time",
        "20",
        "-w",
        "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download} %{speed_download}",
    ]
    if resolve_host:
        command.extend(["--resolve", f"{resolve_host}:443:127.0.0.1"])
    command.append(url)

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "summary": "超时", "detail": "超过 25 秒未完成"}

    output = (result.stdout or "").strip().split()
    if result.returncode != 0 or len(output) < 8:
        detail = (result.stderr or result.stdout or "curl failed").strip()
        return {"name": name, "ok": False, "summary": "失败", "detail": detail[:240]}

    code, lookup, connect, appconnect, start, total, size, speed = output[:8]
    total_f = float(total)
    start_f = float(start)
    code_i = int(code)
    ok = 200 <= code_i < 400 and total_f < 5
    if code_i == 403:
        summary = "403，疑似上游 WAF/CF 拦截"
    elif total_f >= 5:
        summary = "偏慢"
    elif ok:
        summary = "正常"
    else:
        summary = f"HTTP {code}"

    return {
        "name": name,
        "ok": ok,
        "summary": summary,
        "detail": f"code={code} 首包={start_f:.3f}s 总耗时={total_f:.3f}s 大小={size}B 速度={speed}B/s DNS={float(lookup):.3f}s TCP={float(connect):.3f}s TLS={float(appconnect):.3f}s",
    }


def run_mapping_checks(origin: str, host: str) -> list[dict]:
    upstream = origin.rstrip("/")
    proxy = f"https://{host}"
    return [
        curl_check("源站 Public API", upstream + "/System/Info/Public"),
        curl_check("反代 Public API", proxy + "/System/Info/Public", resolve_host=host),
        curl_check("源站 Web 首页", upstream + "/web/index.html"),
        curl_check("反代 Web 首页", proxy + "/web/index.html", resolve_host=host),
    ]


def diagnosis_html(checks: list[dict]) -> str:
    by_name = {check["name"]: check for check in checks}
    upstream_api = by_name.get("源站 Public API", {})
    proxy_api = by_name.get("反代 Public API", {})
    upstream_web = by_name.get("源站 Web 首页", {})
    proxy_web = by_name.get("反代 Web 首页", {})

    tips = []
    if proxy_api.get("ok") and not proxy_web.get("ok") and not upstream_web.get("ok"):
        tips.append("源站 API 正常，但源站 Web 首页异常；这通常不是反代配置问题，播放器仍可尝试连接。")
    if upstream_api.get("ok") and not proxy_api.get("ok"):
        tips.append("源站 API 正常但反代 API 异常，建议重新生成或检查 Nginx 配置。")
    if proxy_api.get("summary", "").startswith("403") or proxy_web.get("summary", "").startswith("403"):
        tips.append("检测到 403，通常是上游 WAF/Cloudflare 策略；为避免改变客户端身份，代理不会伪装 User-Agent。")
    if any("偏慢" in check.get("summary", "") for check in checks):
        tips.append("检测到偏慢，优先考虑小鸡到源站线路问题，换出口节点通常比改配置有效。")
    if all(check.get("ok") for check in checks):
        tips.append("全部自检正常，可以直接把完整 HTTPS 地址发给朋友。")

    if not tips:
        tips.append("自检存在异常，请优先看源站与反代的差异：源站也异常时多半不是本机配置问题。")

    items = "".join(f"<li>{html.escape(tip)}</li>" for tip in tips)
    return f"<div class='diagnosis'><strong>诊断建议</strong><ul>{items}</ul></div>"


def checks_html(checks: list[dict]) -> str:
    rows = []
    for check in checks:
        cls = "ok" if check["ok"] else "warn"
        rows.append(
            f"<tr class='{cls}'><td>{html.escape(check['name'])}</td>"
            f"<td>{html.escape(check['summary'])}</td>"
            f"<td>{html.escape(check['detail'])}</td></tr>"
        )
    return diagnosis_html(checks) + "<table><thead><tr><th>自检项</th><th>结果</th><th>详情</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def is_base_proxy_host(request: web.Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].lower().strip(".")
    return host == PROXY_DOMAIN_SUFFIX


async def generator_response(request: web.Request):
    if request.method not in {"GET", "POST"}:
        raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST"])
    panel = request.app.get("panel")
    if not panel or not panel.enabled:
        raise web.HTTPServiceUnavailable(text="panel is unavailable")
    user = panel.require_user(request)
    if user["must_change_password"]:
        raise web.HTTPFound("/account")
    nodes = panel.frontend_nodes()
    csrf_token = str(user["csrf_secret"])
    raw_url = ""
    raw_route_note = ""
    if request.method == "POST":
        data = await request.post()
        panel._check_user_csrf(user, data)
        raw_url = str(data.get("url", "")).strip()
        raw_node_id = str(data.get("node_id", ""))
        raw_route_note = str(data.get("route_note", "")).strip()
    else:
        query = parse_qs(request.query_string)
        raw_node_id = (query.get("node_id") or [""])[0]
    try:
        selected_node_id = int(raw_node_id)
    except ValueError:
        selected_node_id = nodes[0]["id"] if nodes else 0
    if nodes and selected_node_id not in {node["id"] for node in nodes}:
        selected_node_id = nodes[0]["id"]
    result_html = ""
    if raw_url:
        try:
            origin = normalized_origin(raw_url)
            if not is_global_address(urlsplit(origin).hostname or ""):
                raise ValueError("private target")
            if not selected_node_id:
                raise ValueError("no node available")
            host, https_url = panel.create_frontend_route(origin, selected_node_id, int(user["id"]), raw_route_note)
            checks_section = "<p class='hint'>线路已下发到所选节点。可点击上方“测试延迟”从当前浏览器重新测试节点。</p>"
            result_html = f"""
            <section class="result">
                <span class="eyebrow">线路已就绪</span>
                <label>完整 HTTPS 地址</label>
                <div class="copy-field"><input readonly value="{html.escape(https_url, quote=True)}"><button type="button" class="copy-route" data-copy="{html.escape(https_url, quote=True)}">复制</button></div>
                <p class="hint">已分配节点域名：{html.escape(host)}。正在播放的连接不会因后续节点操作被中断。</p>
                {checks_section}
            </section>
            """
        except Exception as exc:
            result_html = f"<p class='error'>{html.escape(str(exc))}。示例：https://emby.example.com</p>"

    node_cards_parts = []
    for node in nodes:
        meta_label = node["code"].lower() if node["is_local"] else (node["country_name"] or node["health"])
        node_cards_parts.append(
            f"<button type='button' title='{html.escape(node['name'], quote=True)}' aria-pressed={'true' if node['id'] == selected_node_id else 'false'} class='node-card{' selected' if node['id'] == selected_node_id else ''}' data-node-id='{node['id']}'>"
            f"<span class='node-title'><span class='node-flag'>{node['flag_markup']}</span></span>"
            f"<span class='node-name'>{html.escape(node['name'])}</span>"
            f"<span class='node-meta'><small>{html.escape(meta_label)}</small><b class='latency' data-latency='{node['id']}'>待测试</b></span></button>"
        )
    node_cards = "".join(node_cards_parts) or "<p class='hint'>暂时没有可用节点。</p>"
    nodes_json = json.dumps(nodes, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    route_rows = []
    for route in panel.user_routes(int(user["id"])):
        state = "已暂停" if route["suspended_by_owner"] else ("已下发" if route["deployed"] else "部署失败")
        error = f"<br><span class='route-error'>{html.escape(route['last_error'])}</span>" if route["last_error"] else ""
        note = str(route["notes"] or "")
        note_display = html.escape(note) or "<span class='hint'>未填写</span>"
        note_editor = f"<details class='route-note-editor'><summary>编辑备注</summary><form method='post' action='/my/routes/{route['id']}/note'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><label>线路备注<input name='notes' maxlength='500' value='{html.escape(note, quote=True)}' placeholder='例如：影视库 1'></label><button>保存</button></form></details>"
        route_rows.append(
            f"<tr><td><span class='route-url'>{html.escape(route['origin'])}</span></td>"
            f"<td><span class='route-url'>{html.escape(route['public_url'])}</span><button type='button' class='copy-route' data-copy='{html.escape(route['public_url'], quote=True)}'>复制</button></td>"
            f"<td>{html.escape(route['node_name'])}</td><td>{note_display}{note_editor}</td><td>{state}{error}</td><td><form method='post' action='/my/routes/{route['id']}/delete'>"
            f"<input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='delete-route'>删除</button></form></td></tr>"
        )
    used_routes, route_quota = panel.user_route_usage(int(user["id"]))
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='hint'>你还没有创建线路。</td></tr>"
    expiry_label = panel._display_expiry(user["expires_at"])
    csp_nonce = secrets.token_urlsafe(16)

    body = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>反代</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<link rel="shortcut icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;overflow-x:hidden;color:#24334d;background:linear-gradient(145deg,#f8fbff 0%,#f4f7fe 47%,#eef7f8 100%);font-family:"PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}body:before,body:after{{content:"";position:fixed;z-index:-1;pointer-events:none;border-radius:50%;filter:blur(8px)}}body:before{{width:42vw;height:42vw;left:-15vw;top:-16vw;background:radial-gradient(circle,rgba(174,195,255,.45),rgba(174,195,255,0) 70%)}}body:after{{width:46vw;height:46vw;right:-14vw;bottom:-23vw;background:radial-gradient(circle,rgba(172,228,221,.42),rgba(172,228,221,0) 70%)}}
    main{{max-width:980px;margin:0 auto;padding:30px 24px 62px}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:55px}}.brand{{display:flex;align-items:center;gap:10px;color:#33455f;font-weight:750;letter-spacing:.04em;font-size:15px}}.brand-mark{{display:grid;place-items:center;width:34px;height:34px;border:1px solid #d9e3f7;border-radius:12px;color:#6079b7;background:linear-gradient(145deg,#fff,#edf3ff);box-shadow:0 8px 20px rgba(96,121,183,.12)}}.live{{display:flex;gap:8px;align-items:center;color:#61718a;font-size:12px;padding:8px 12px;border:1px solid rgba(192,205,226,.7);border-radius:999px;background:rgba(255,255,255,.65);box-shadow:0 5px 16px rgba(73,99,143,.06)}}.live i{{width:7px;height:7px;border-radius:50%;background:#61bd8a;box-shadow:0 0 0 4px rgba(97,189,138,.12)}}.account-actions{{display:flex;align-items:center;gap:8px}}.account-actions a{{color:#526b9f;font-size:12px;text-decoration:none}}.logout-form{{margin:0}}button.logout{{height:34px;padding:0 10px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#617595;font-size:12px}}
.hero{{max-width:710px;margin:0 auto 34px;text-align:center}}h1{{margin:9px 0 16px;color:#293b59;font-size:clamp(38px,6vw,64px);line-height:1.15;letter-spacing:-.055em;font-weight:780}}h1 span{{color:#657dbc}}.eyebrow{{display:inline-flex;align-items:center;gap:7px;color:#6682bb;font-size:13px;font-weight:700;letter-spacing:.08em}}.eyebrow:before{{content:"";width:18px;height:1px;background:#a9b9dd}}.subtitle,.hint{{color:#71809a;line-height:1.8}}.subtitle{{max-width:570px;margin:0 auto;font-size:15px}}.workspace,.result{{position:relative;overflow:hidden;margin-top:20px;padding:27px 28px;border:1px solid rgba(208,219,238,.88);border-radius:22px;background:rgba(255,255,255,.7);box-shadow:0 20px 55px rgba(75,98,142,.1);backdrop-filter:blur(18px)}}.workspace:after{{content:"";position:absolute;width:260px;height:260px;right:-145px;top:-180px;border-radius:50%;background:radial-gradient(circle,rgba(181,202,249,.25),rgba(181,202,249,0) 68%);pointer-events:none}}
.section-line{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}}.section-line h2{{margin:0;color:#405572;font-size:15px;letter-spacing:.01em}}.section-line span{{font-size:12px;color:#8795aa}}.nodes{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;max-width:540px;margin:0 auto 17px}}.node-card{{display:flex;flex-direction:column;justify-content:center;gap:5px;min-height:82px;padding:8px 10px;text-align:center;color:#18243a;border:2px solid #edf0f5;border-radius:16px;background:rgba(255,255,255,.94);cursor:pointer;transition:transform .18s,border-color .18s,box-shadow .18s,background .18s}}.node-card:hover{{transform:translateY(-2px);border-color:#cbd8ef;box-shadow:0 8px 18px rgba(87,111,157,.1)}}.node-card.selected{{border-color:#2763ff;background:#fbfdff;box-shadow:0 0 0 1px #2763ff,0 8px 18px rgba(39,99,255,.1)}}.node-title{{display:flex;align-items:center;justify-content:center;min-height:24px}}.node-flag{{display:grid;place-items:center;line-height:1}}.flag-icon{{display:block;width:30px;height:20px;border-radius:3px;box-shadow:0 1px 4px rgba(55,72,104,.22)}}.node-name{{display:block;overflow:hidden;color:#485e7d;font-size:11px;font-weight:700;line-height:1.35;white-space:nowrap;text-overflow:ellipsis}}.node-meta{{display:flex;align-items:center;justify-content:space-between;gap:8px}}.node-card small{{overflow:hidden;color:#8a96a8;font-size:10px;white-space:nowrap;text-overflow:ellipsis}}.latency{{flex:0 0 auto;color:#667b9f;font-size:10px;font-weight:700}}
    .tools{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 7px}}button{{height:47px;padding:0 20px;border:1px solid #607abc;border-radius:12px;background:linear-gradient(135deg,#6d84bd,#5873ae);box-shadow:0 10px 20px rgba(82,108,165,.2);color:#fff;font-family:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:transform .16s,box-shadow .16s}}button:hover{{transform:translateY(-1px);box-shadow:0 13px 23px rgba(82,108,165,.28)}}button.secondary{{height:38px;padding:0 13px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#617595}}button.copy-route{{height:30px;margin:6px 0 0 7px;padding:0 9px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#526b9f;font-size:11px}}.copy-field{{display:flex;gap:8px;align-items:center}}.copy-field button.copy-route{{height:42px;flex:0 0 auto;margin:6px 0 0;padding:0 14px;font-size:13px}}.route-form{{padding-top:20px;border-top:1px solid #e6ebf4}}.route-note-field{{margin-top:10px}}label{{display:block;margin:0 0 9px;color:#536882;font-size:13px;font-weight:720}}.row{{display:flex;gap:10px}}input{{width:100%;min-width:0;padding:13px 15px;outline:0;color:#30435f;border:1px solid #d8e1ef;border-radius:12px;background:#fff;font:15px inherit;transition:border-color .18s,box-shadow .18s}}input::placeholder{{color:#a5b0c1}}input:focus{{border-color:#8fa7dc;box-shadow:0 0 0 4px rgba(143,167,220,.16)}}.row button{{min-width:116px}}.hint{{margin:10px 0 0;font-size:12px}}.error{{padding:14px;border:1px solid #f2c8d0;border-radius:13px;color:#b85f6d;background:#fff5f6}}.result{{border-color:#c9daf1}}.result input{{margin-top:6px}}.result .eyebrow{{margin-bottom:15px}}.my-routes{{margin-top:20px;padding:22px 24px;border:1px solid rgba(208,219,238,.88);border-radius:20px;background:rgba(255,255,255,.7);box-shadow:0 18px 48px rgba(75,98,142,.08)}}.my-routes h2{{margin:0;color:#405572;font-size:16px}}.routes-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}.my-routes table{{width:100%;min-width:800px;margin-top:14px;border-collapse:collapse}}.my-routes th,.my-routes td{{padding:10px 7px;border-bottom:1px solid #e4ebf5;text-align:left;vertical-align:top;font-size:12px}}.route-url{{color:#315fbd;word-break:break-all}}.route-note-editor{{margin-top:5px}}.route-note-editor summary{{color:#526b9f;cursor:pointer;font-size:11px}}.route-note-editor form{{display:flex;align-items:end;gap:6px;margin-top:7px}}.route-note-editor label{{min-width:170px;margin:0;font-size:11px}}.route-note-editor input{{padding:7px 9px;font-size:12px}}.route-note-editor button{{height:32px;padding:0 9px;font-size:12px}}button.delete-route{{height:32px;padding:0 9px;border-color:#f2c8d0;background:#fff5f6;box-shadow:none;color:#b85f6d;font-size:12px}}.route-error{{color:#b85f6d}}
@media(max-width:650px){{main{{padding:20px 14px 40px}}.topbar{{margin-bottom:38px}}.brand{{font-size:14px}}.hero{{margin-bottom:25px}}.workspace,.result{{padding:19px 16px;border-radius:18px}}.section-line{{align-items:flex-start;flex-direction:column;gap:5px}}.nodes{{gap:10px}}.node-card{{min-height:78px;padding:8px 7px;border-radius:15px}}.node-title{{min-height:22px}}.flag-icon{{width:27px;height:18px}}.node-meta{{display:flex}}.node-card small,.node-name,.latency{{font-size:9px}}.row{{flex-direction:column}}.row button{{width:100%}}.tools{{align-items:flex-start;flex-direction:column}}}}
</style>
    <main><nav class="topbar"><div class="brand"><span class="brand-mark">✦</span>反代入口</div><div class="account-actions"><div class="live"><i></i>{html.escape(user['username'])} · {used_routes}/{route_quota} 条 · {html.escape(expiry_label)}</div><a href="/account">账号安全</a><form class="logout-form" method="post" action="/logout"><input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}"><button class="logout">退出</button></form></div></nav>
<header class="hero"><span class="eyebrow">媒体访问加速</span><h1>选一个合适的<br><span>播放入口。</span></h1><p class="subtitle">选择中转节点后测试延迟，再为你的媒体站点生成一个独立的访问地址。</p></header>
<section class="workspace"><div class="section-line"><h2>选择节点</h2><span>延迟由当前浏览器测量</span></div><div class="nodes" id="nodes">{node_cards}</div><div class="tools"><button type="button" class="secondary" id="test-nodes">重新测试延迟</button><span class="hint">生成后，线路会部署到当前选中的节点。</span></div>
    <form class="route-form" method="post"><input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}"><input type="hidden" name="node_id" id="node-id" value="{selected_node_id}"><label>原始网站地址</label><div class="row"><input required name="url" placeholder="https://emby.example.com" value="{html.escape(raw_url)}"><button>生成访问地址</button></div><label class="route-note-field">线路备注（可选）<input name="route_note" maxlength="500" placeholder="例如：影视库 1" value="{html.escape(raw_route_note, quote=True)}"></label><p class="hint">线路会归属到你的账号。会清理来源和代理链标识，重写安全的媒体跳转，并保持视频流式播放。</p></form></section>
    {result_html}
    <section class="my-routes"><div class="section-line"><h2>我的线路</h2><span>删除线路后会释放额度</span></div><div class="routes-scroll"><table><thead><tr><th>原线路（源站）</th><th>反代线路（访问地址）</th><th>节点</th><th>备注</th><th>状态</th><th></th></tr></thead><tbody>{my_routes_html}</tbody></table></div></section>
    </main>
    <script nonce="{csp_nonce}">
const nodes={nodes_json}; let selected={selected_node_id};
function pick(id){{selected=id;document.getElementById('node-id').value=id;document.querySelectorAll('.node-card').forEach(card=>{{const active=Number(card.dataset.nodeId)===id;card.classList.toggle('selected',active);card.setAttribute('aria-pressed',String(active));}});}}
document.querySelectorAll('.node-card').forEach(card=>card.addEventListener('click',()=>pick(Number(card.dataset.nodeId))));
async function probe(node){{const label=document.querySelector('[data-latency="'+node.id+'"]');label.textContent='测试中…';const start=performance.now();try{{await fetch(node.probe_url+'?t='+Date.now(),{{mode:'no-cors',cache:'no-store'}});label.textContent=Math.round(performance.now()-start)+' ms';}}catch(e){{label.textContent='无法连接';}}}}
function probeAll(){{nodes.forEach(probe);}} document.getElementById('test-nodes').addEventListener('click',probeAll); if(nodes.length){{probeAll();}}
async function copyText(value){{try{{if(navigator.clipboard&&window.isSecureContext){{await navigator.clipboard.writeText(value);return true;}}const field=document.createElement('textarea');field.value=value;field.readOnly=true;field.style.cssText='position:fixed;opacity:0';document.body.append(field);field.select();const copied=document.execCommand('copy');field.remove();return copied;}}catch(e){{return false;}}}}
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{{const label=button.textContent;button.textContent=(await copyText(button.dataset.copy))?'已复制':'复制失败';setTimeout(()=>button.textContent=label,1200);}}));
</script>
</html>"""
    response = web.Response(text=body, content_type="text/html")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
        f"img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'nonce-{csp_nonce}'; connect-src 'self' https:"
    )
    return response


def target_from_request(request: web.Request):
    raw_path = request.raw_path
    query = request.query_string
    path = raw_path.lstrip("/")
    origin_from_url = None
    host_origin = proxied_origin_from_host(request.headers.get("host", ""))

    if path == "__health":
        return None, None, None

    if host_origin:
        target_url = host_origin.rstrip("/") + "/" + path

    elif path == TOKEN or path.startswith(TOKEN + "/"):
        tail = path[len(TOKEN):].lstrip("/")
        if tail.startswith(("http://", "https://")):
            target_url = tail
            parsed = urlsplit(target_url)
            origin_from_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            origin = unsign_origin(request.cookies.get(COOKIE_NAME, ""))
            if not origin:
                raise web.HTTPBadRequest(text="missing target url")
            target_url = origin.rstrip("/") + "/" + tail
    elif path.startswith(("http://", "https://")):
        target_url = path
        parsed = urlsplit(target_url)
        origin_from_url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        origin = unsign_origin(request.cookies.get(COOKIE_NAME, ""))
        if origin:
            target_url = origin.rstrip("/") + "/" + path
        elif DEFAULT_TARGET_ORIGIN:
            target_url = DEFAULT_TARGET_ORIGIN + "/" + path
        else:
            raise web.HTTPUnauthorized(text="missing proxy token")

    if query:
        target_url = target_url + "?" + query

    parsed = urlsplit(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise web.HTTPBadRequest(text="target must start with http:// or https://")
    if not is_global_address(parsed.hostname):
        raise web.HTTPForbidden(text="target host is not a public internet address")

    return urlunsplit(parsed), origin_from_url, host_origin


def rewrite_location(location: str, origin: str, host_origin: str | None, request: web.Request) -> str:
    if host_origin:
        proxy_scheme = request.headers.get("x-forwarded-proto", request.scheme)
        proxy_host = request.headers.get("host", "")
        if location.startswith(("http://", "https://")):
            parsed = urlsplit(location)
            target_origin = f"{parsed.scheme}://{parsed.netloc}"
            proxy_host = request.headers.get("host", "")
            if target_origin != origin:
                proxy_host = proxied_host_for_origin(target_origin)
            return urlunsplit((proxy_scheme, proxy_host, parsed.path, parsed.query, parsed.fragment))
        return location

    if location.startswith(("http://", "https://")):
        return f"/{location}"
    if location.startswith("/"):
        return f"/{origin}{location}"
    return location


async def websocket_proxy(request: web.Request, target_url: str):
    split = urlsplit(target_url)
    ws_scheme = "wss" if split.scheme == "https" else "ws"
    ws_target = urlunsplit((ws_scheme, split.netloc, split.path, split.query, split.fragment))
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)

    headers = clean_headers(request.headers, split)
    async with request.app["session"].ws_connect(ws_target, headers=headers, max_msg_size=0) as ws_upstream:
        async def client_to_upstream():
            async for msg in ws_client:
                if msg.type == WSMsgType.TEXT:
                    await ws_upstream.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await ws_upstream.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await ws_upstream.close()

        async def upstream_to_client():
            async for msg in ws_upstream:
                if msg.type == WSMsgType.TEXT:
                    await ws_client.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await ws_client.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await ws_client.close()

        await asyncio.gather(client_to_upstream(), upstream_to_client(), return_exceptions=True)
    return ws_client


async def handle(request: web.Request):
    if request.path == "/__health":
        return web.Response(text="ok\n")
    if request.path == "/favicon.ico":
        return web.Response(status=204)

    panel = request.app.get("panel")
    if is_base_proxy_host(request) and (request.path == "/_admin" or request.path.startswith("/_admin/")) and panel is not None:
        return await panel.handle(request)
    if is_base_proxy_host(request) and request.path == "/_agent/heartbeat" and panel is not None:
        return await panel.agent_heartbeat(request)
    if is_base_proxy_host(request) and panel is not None and (
        request.path in {"/login", "/register", "/logout", "/account", "/account/password"}
        or re.fullmatch(r"/my/routes/\d+/(delete|note)", request.path)
    ):
        return await panel.handle_user(request)

    if is_base_proxy_host(request) and request.path in {"/", "/gen"}:
        return await generator_response(request)

    # Generated routes are served directly by Nginx.  This process is only the
    # UI/control plane and must never act as a generic outbound proxy.
    raise web.HTTPNotFound()

@web.middleware
async def security_headers(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' https:",
    )
    response.headers["Server"] = ""
    return response


async def create_app():
    app = web.Application(client_max_size=8 * 1024**2, middlewares=[security_headers])
    from panel import ProxyPanel
    panel = ProxyPanel(normalized_origin)
    panel.setup()
    await panel.refresh_local_location()
    app["panel"] = panel
    async def reconcile_users(application: web.Application) -> None:
        while True:
            try:
                await asyncio.to_thread(application["panel"].reconcile_inactive_users)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed remote-node cleanup remains visible on the route and is retried later.
                pass
            await asyncio.sleep(60)

    async def collect_traffic(application: web.Application) -> None:
        while True:
            try:
                await asyncio.to_thread(application["panel"].collect_traffic_usage)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A single unavailable node is retried on the next collection pass.
                pass
            await asyncio.sleep(60)

    async def start_reconciler(application: web.Application) -> None:
        application["user_reconciler"] = asyncio.create_task(reconcile_users(application))
        application["traffic_collector"] = asyncio.create_task(collect_traffic(application))

    async def stop_reconciler(application: web.Application) -> None:
        for name in ("user_reconciler", "traffic_collector"):
            task = application.get(name)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app.on_startup.append(start_reconciler)
    app.on_cleanup.append(stop_reconciler)
    app.router.add_route("*", "/{path_info:.*}", handle)

    return app


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("PROXY_TOKEN is required")
    web.run_app(create_app(), host=LISTEN_HOST, port=LISTEN_PORT)
