#!/usr/bin/env python3
import asyncio
import html
import json
import os
import re
import secrets
from urllib.parse import parse_qs

from aiohttp import web

from nginx_renderer import RendererError, normalize_origin as normalize_route_origin

LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8787"))
PROXY_DOMAIN_SUFFIX = os.environ.get("PROXY_DOMAIN_SUFFIX", "sh.996878.xyz").lower().strip(".")


def normalized_origin(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        return normalize_route_origin(value, allow_insecure_http=False)
    except RendererError as exc:
        raise ValueError(str(exc)) from exc


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
            if not panel.user_route_creation_enabled:
                raise ValueError("route creation is temporarily disabled")
            origin = normalized_origin(raw_url)
            if not selected_node_id:
                raise ValueError("no node available")
            host, https_url = await asyncio.to_thread(
                panel.create_frontend_route,
                origin,
                selected_node_id,
                int(user["id"]),
                raw_route_note,
            )
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
    admin_link = "<a href='/_admin'>管理后台</a>" if int(user["is_admin"] or 0) else ""
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
    <main><nav class="topbar"><div class="brand"><span class="brand-mark">✦</span>反代入口</div><div class="account-actions"><div class="live"><i></i>{html.escape(user['username'])} · {used_routes}/{route_quota} 条 · {html.escape(expiry_label)}</div>{admin_link}<a href="/account">账号安全</a><form class="logout-form" method="post" action="/logout"><input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}"><button class="logout">退出</button></form></div></nav>
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

    async def renew_node_certificates(application: web.Application) -> None:
        interval = max(3600, int(os.environ.get("CERT_RENEW_INTERVAL", "21600")))
        while True:
            try:
                await asyncio.to_thread(application["panel"].renew_node_certificates)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Renewal failures leave the previous certificate in place and
                # are retried on the next pass; operators can inspect logs.
                pass
            await asyncio.sleep(interval)

    async def start_reconciler(application: web.Application) -> None:
        application["user_reconciler"] = asyncio.create_task(reconcile_users(application))
        application["traffic_collector"] = asyncio.create_task(collect_traffic(application))
        application["certificate_renewer"] = asyncio.create_task(renew_node_certificates(application))

    async def stop_reconciler(application: web.Application) -> None:
        for name in ("user_reconciler", "traffic_collector", "certificate_renewer"):
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
    web.run_app(create_app(), host=LISTEN_HOST, port=LISTEN_PORT)
