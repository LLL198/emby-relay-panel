#!/usr/bin/env python3
"""Password-protected management panel for emby-relay-panel nodes and routes."""

import asyncio
import base64
import binascii
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import shlex
import socket
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from aiohttp import ClientSession, ClientTimeout, web
from cryptography.fernet import Fernet, InvalidToken

from auth_security import (
    HashWorkLimitExceeded,
    HashWorkLimiter,
    PasswordPolicy,
    PasswordPolicyViolation,
    PersistentAuthThrottle,
)
from nginx_renderer import RedirectSpec, RendererError, RouteSpec, render_route
from origin_security import (
    OriginSecurityError,
    OriginSecurityPolicy,
    SafeOriginResolution,
    resolve_origin_safely,
)


ADMIN_PREFIX = "/_admin"
DEFAULT_ADMIN_PASSWORD = "123456"
SAFE_HOST = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")
SAFE_NAME = re.compile(r"^[\w\u4e00-\u9fff -]{1,48}$")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
SAFE_PATH = re.compile(r"^/[A-Za-z0-9._/@+:-]+(?:/[A-Za-z0-9._/@+:-]+)*$")
SAFE_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
SAFE_USERNAME = re.compile(r"^[A-Za-z0-9._-]+$")
USER_SESSION_COOKIE = "__Host-uniproxy-session"
USER_CSRF_COOKIE = "__Host-uniproxy-csrf"
LEGACY_USER_SESSION_COOKIE = "_uniproxy_user_session"
LEGACY_USER_CSRF_COOKIE = "_uniproxy_user_csrf"
SESSION_EPHEMERAL_SECONDS = 24 * 60 * 60
SESSION_REMEMBER_SECONDS = 90 * 24 * 60 * 60
SCHEMA_VERSION = 4
ADMIN_ROUTE_PAGE_SIZE = 5
TRAFFIC_FORMAT_NAME = "uniproxy_traffic"
TRAFFIC_CONFIG_NAME = "00-uniproxy-traffic.conf"
TRAFFIC_MAX_CHUNK_BYTES = 4 * 1024 * 1024
TRAFFIC_TIMEZONE = timezone(timedelta(hours=8))
SSH_READY_ATTEMPTS = 4
SSH_READY_RETRY_SECONDS = 3

AUTH_UI_CSS = r"""
:root{
  color-scheme: light;
  --bg: #f7f7fb;
  --panel: rgba(255,255,255,.9);
  --panel-strong: #ffffff;
  --ink: #171722;
  --muted: #697084;
  --faint: #9298a8;
  --line: rgba(67,72,92,.13);
  --line-strong: rgba(124,58,237,.25);
  --violet: #8b5cf6;
  --cyan: #22d3ee;
  --danger: #be123c;
  --success: #15803d;
  --shadow: 0 20px 60px rgba(55,46,92,.08);
}
body[data-theme='dark']{
  color-scheme: dark;
  --bg: #05060b;
  --panel: rgba(12,15,25,.82);
  --panel-strong: #0d101a;
  --ink: #f7f8ff;
  --muted: #8f97ac;
  --faint: #626b80;
  --line: rgba(148,163,184,.16);
  --line-strong: rgba(196,181,253,.28);
  --danger: #fb7185;
  --success: #4ade80;
  --shadow: 0 30px 90px rgba(0,0,0,.5);
}
*{box-sizing:border-box}
html{min-height:100%;background:var(--bg)}
body{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:center;
  min-height:100vh;
  margin:0;
  padding:28px;
  overflow-x:hidden;
  background:radial-gradient(circle at 50% -15%,rgba(139,92,246,.09),transparent 34%),radial-gradient(circle at 92% 88%,rgba(34,211,238,.07),transparent 30%),var(--bg);
  color:var(--ink);
  font:14px/1.6 Inter,"PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif
}
body[data-theme='dark']{
  background:radial-gradient(circle at 50% -15%,rgba(99,102,241,.18),transparent 34%),radial-gradient(circle at 92% 88%,rgba(34,211,238,.1),transparent 30%),var(--bg);
}
body:before{
  content:"";
  position:fixed;
  inset:-60px;
  pointer-events:none;
  opacity:.35;
  background-image:linear-gradient(rgba(99,102,241,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(99,102,241,.09) 1px,transparent 1px);
  background-size:42px 42px;
  mask-image:radial-gradient(ellipse 70% 62% at 50% 42%,#000 20%,transparent 78%);
  animation:grid-drift 22s linear infinite
}
body[data-theme='dark']:before{
  opacity:.28;
  background-image:linear-gradient(rgba(148,163,184,.075) 1px,transparent 1px),linear-gradient(90deg,rgba(148,163,184,.075) 1px,transparent 1px);
}
body:after{
  content:"";
  position:fixed;
  width:460px;
  height:460px;
  left:50%;
  top:50%;
  pointer-events:none;
  border-radius:50%;
  background:radial-gradient(circle,rgba(139,92,246,.12),rgba(34,211,238,.04) 42%,transparent 70%);
  filter:blur(12px);
  transform:translate(-50%,-50%);
  animation:aurora-pulse 8s ease-in-out infinite
}
a{color:#7c3aed;text-decoration:none;font-weight:720;transition:color .18s ease}
a:hover{color:#8b5cf6}
body[data-theme='dark'] a{color:#c4b5fd}
body[data-theme='dark'] a:hover{color:#67e8f9}

.auth-theme-toggle{
  position:fixed;
  top:20px;
  right:20px;
  z-index:100;
  display:grid;
  place-items:center;
  width:38px;
  height:38px;
  margin:0;
  padding:0;
  border:1px solid var(--line);
  border-radius:11px;
  background:var(--panel);
  box-shadow:var(--shadow);
  color:var(--muted);
  font-size:15px;
  cursor:pointer;
  backdrop-filter:blur(16px);
  transition:all .18s ease;
  animation:none;
}
.auth-theme-toggle:before{display:none}
.auth-theme-toggle:hover{
  border-color:var(--line-strong);
  background:rgba(139,92,246,.1);
  color:var(--ink);
  transform:translateY(-1px);
  box-shadow:0 6px 20px rgba(139,92,246,.12);
}

.auth-shell{
  position:relative;
  z-index:1;
  isolation:isolate;
  width:min(100%,400px);
  margin:auto;
  overflow:hidden;
  border:1px solid transparent;
  border-radius:24px;
  background:linear-gradient(var(--panel-strong),var(--panel-strong)) padding-box,linear-gradient(135deg,rgba(139,92,246,.5),rgba(148,163,184,.12) 42%,rgba(34,211,238,.4)) border-box;
  box-shadow:var(--shadow);
  backdrop-filter:blur(22px)
}
.auth-shell:before{
  content:"";
  position:absolute;
  left:20px;
  right:20px;
  top:0;
  height:1px;
  pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(196,181,253,.5),rgba(103,232,249,.3),transparent);
}
.auth-intro{position:relative;padding:34px 38px 0;text-align:center}
.brand-lockup{display:flex;align-items:center;justify-content:center}
.brand-lockup:before{
  content:"✦";
  display:grid;
  place-items:center;
  width:34px;
  height:34px;
  margin-right:11px;
  border:1px solid rgba(196,181,253,.35);
  border-radius:11px;
  background:linear-gradient(145deg,rgba(139,92,246,.28),rgba(34,211,238,.1));
  box-shadow:inset 0 1px rgba(255,255,255,.12),0 0 22px rgba(139,92,246,.18);
  color:#8b5cf6;
  font-size:15px
}
body[data-theme='dark'] .brand-lockup:before{color:#d8b4fe}
.brand-copy{display:grid;line-height:1.16;text-align:left}
.brand-copy strong{
  color:var(--ink);
  font-size:16px;
  letter-spacing:.01em
}
.brand-copy small{
  margin-top:4px;
  color:var(--faint);
  font-size:10px;
  font-weight:650;
  letter-spacing:.08em
}
.auth-panel{padding:26px 38px 36px}
.auth-card{width:100%}
.auth-card>h1{
  margin:0 0 22px;
  color:var(--ink);
  font-size:23px;
  line-height:1.2;
  letter-spacing:-.035em;
  text-align:center
}
.auth-card>p.muted{margin:0 0 22px;text-align:center}
.muted{color:var(--muted)}
label{
  display:grid;
  gap:7px;
  margin-top:16px;
  color:var(--ink);
  font-size:12px;
  font-weight:700;
  letter-spacing:.01em
}
body[data-theme='light'] label{color:#41475a}
input{
  width:100%;
  height:46px;
  padding:0 14px;
  outline:0;
  border:1px solid var(--line);
  border-radius:11px;
  background:rgba(255,255,255,.9);
  color:var(--ink);
  font:inherit;
  font-size:13px;
  transition:border-color .18s ease,box-shadow .18s ease,background .18s ease
}
body[data-theme='dark'] input{
  background:rgba(7,9,16,.74);
  box-shadow:inset 0 1px rgba(255,255,255,.025);
}
input:hover{
  border-color:rgba(196,181,253,.34);
}
input:focus{
  border-color:rgba(139,92,246,.88);
  box-shadow:0 0 0 4px rgba(139,92,246,.13),0 0 24px rgba(34,211,238,.06)
}
input::selection{background:rgba(139,92,246,.4)}
label.checkline{
  display:flex;
  align-items:center;
  gap:9px;
  margin-top:16px;
  color:var(--muted);
  font-weight:600;
  letter-spacing:0
}
label.checkline input{width:16px;height:16px;margin:0;accent-color:var(--violet)}
button{
  position:relative;
  width:100%;
  height:46px;
  margin-top:22px;
  overflow:hidden;
  border:1px solid rgba(196,181,253,.34);
  border-radius:11px;
  background:linear-gradient(105deg,#6d28d9 0%,#7c3aed 36%,#2563eb 70%,#0891b2 100%);
  background-size:200% 100%;
  box-shadow:0 10px 28px rgba(109,40,217,.22),inset 0 1px rgba(255,255,255,.18);
  color:#fff;
  font:inherit;
  font-weight:800;
  cursor:pointer;
  transition:transform .18s ease,box-shadow .18s ease;
  animation:button-hue 7s ease-in-out infinite
}
button:before{
  content:"";
  position:absolute;
  inset:-2px auto -2px -45%;
  width:34%;
  pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.38),transparent);
  transform:skewX(-18deg);
  animation:shimmer 3.8s ease-in-out infinite
}
button:hover{
  transform:translateY(-1px);
  box-shadow:0 14px 36px rgba(109,40,217,.3),0 0 28px rgba(34,211,238,.08)
}
button:active{transform:translateY(0)}
button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid #67e8f9;outline-offset:3px}
.links{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:12px;
  margin:20px 0 0;
  padding-top:16px;
  border-top:1px solid var(--line);
  color:var(--faint);
  font-size:12px
}
.error,.notice{
  margin:0 0 18px;
  padding:11px 14px;
  border:1px solid;
  border-radius:11px;
  font-size:12px
}
.error{border-color:rgba(251,113,133,.3);background:#fff1f2;color:#be123c}
body[data-theme='dark'] .error{background:rgba(127,29,29,.18);color:#fda4af}
.notice{border-color:rgba(74,222,128,.28);background:#f0fdf4;color:#15803d}
body[data-theme='dark'] .notice{background:rgba(20,83,45,.18);color:#86efac}
@keyframes grid-drift{to{transform:translate3d(42px,42px,0)}}
@keyframes aurora-pulse{0%,100%{opacity:.55;transform:translate(-50%,-50%) scale(.94)}50%{opacity:1;transform:translate(-50%,-50%) scale(1.08)}}
@keyframes orb-float{0%,100%{transform:translate3d(0,0,0)}50%{transform:translate3d(-12px,16px,0)}}
@keyframes shimmer{0%,58%{left:-45%}82%,100%{left:125%}}
@keyframes button-hue{0%,100%{background-position:0 50%}50%{background-position:100% 50%}}
@media(max-width:560px){
  body{align-items:flex-start;padding:18px 14px}
  .auth-shell{margin:auto 0;border-radius:20px}
  .auth-intro{padding:26px 22px 0}
  .auth-panel{padding:22px 22px 28px}
  .auth-card>h1{font-size:21px}
  .links{flex-wrap:wrap}
  input,button{height:46px}
}
@media(prefers-reduced-motion:reduce){
  *,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
"""

ADMIN_UI_CSS = r"""
:root{color-scheme:dark;--bg:#05060b;--sidebar:rgba(8,10,18,.88);--surface:rgba(13,16,27,.82);--surface-strong:#0d101b;--surface-soft:rgba(21,25,40,.72);--ink:#f7f8ff;--muted:#8e96aa;--faint:#626b80;--line:rgba(148,163,184,.15);--line-strong:rgba(196,181,253,.28);--violet:#8b5cf6;--violet-strong:#7c3aed;--cyan:#22d3ee;--success:#4ade80;--warning:#fbbf24;--danger:#fb7185;--shadow:0 24px 72px rgba(0,0,0,.34)}
*{box-sizing:border-box}[hidden]{display:none!important}html{min-height:100%;background:var(--bg)}body{position:relative;min-height:100vh;margin:0;overflow-x:hidden;background:radial-gradient(circle at 78% -12%,rgba(99,102,241,.16),transparent 31%),radial-gradient(circle at 96% 82%,rgba(34,211,238,.08),transparent 27%),var(--bg);color:var(--ink);font:14px/1.6 Inter,"PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
body:before{content:"";position:fixed;z-index:0;inset:-50px;pointer-events:none;opacity:.28;background-image:linear-gradient(rgba(148,163,184,.075) 1px,transparent 1px),linear-gradient(90deg,rgba(148,163,184,.075) 1px,transparent 1px);background-size:44px 44px;mask-image:radial-gradient(ellipse 80% 68% at 68% 35%,#000 15%,transparent 76%);animation:admin-grid 26s linear infinite}body:after{content:"";position:fixed;z-index:0;width:520px;height:520px;right:-180px;top:22%;pointer-events:none;border-radius:50%;background:radial-gradient(circle,rgba(139,92,246,.12),rgba(34,211,238,.04) 43%,transparent 70%);filter:blur(12px);animation:admin-orb 10s ease-in-out infinite}
.layout{position:relative;z-index:1;display:grid;grid-template-columns:258px minmax(0,1fr);min-height:100vh}
aside{position:sticky;top:0;display:flex;flex-direction:column;height:100vh;padding:25px 17px;border-right:1px solid var(--line);background:var(--sidebar);box-shadow:20px 0 70px rgba(0,0,0,.12);backdrop-filter:blur(24px)}
.brand{display:flex;align-items:center;gap:11px;margin:0 8px 34px;color:var(--ink);text-decoration:none}.brand-symbol{display:grid;place-items:center;width:37px;height:37px;border:1px solid rgba(196,181,253,.32);border-radius:12px;background:linear-gradient(145deg,rgba(139,92,246,.32),rgba(34,211,238,.12));box-shadow:inset 0 1px rgba(255,255,255,.14),0 0 28px rgba(139,92,246,.16);color:#ddd6fe;font-size:15px;font-weight:900}.brand-copy{display:grid;line-height:1.15}.brand-copy strong{background:linear-gradient(90deg,var(--ink),#c4b5fd 68%,#a5f3fc);background-clip:text;-webkit-background-clip:text;color:transparent;font-size:14px;letter-spacing:.01em}.brand-copy small{margin-top:5px;color:var(--faint);font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.side-label{margin:0 12px 9px;color:var(--faint);font-size:9px;font-weight:850;letter-spacing:.18em;text-transform:uppercase}aside nav{display:grid;gap:6px;margin-bottom:22px}aside nav a{display:flex;align-items:center;gap:11px;min-height:43px;padding:8px 11px;border:1px solid transparent;border-radius:11px;color:var(--muted);text-decoration:none;font-size:13px;font-weight:700;transition:background .18s ease,border-color .18s ease,color .18s ease,transform .18s ease}.nav-icon{display:grid;place-items:center;width:27px;height:27px;border:1px solid var(--line);border-radius:9px;background:var(--surface-soft);color:var(--faint);font-size:10px}aside nav a:hover{border-color:var(--line);background:rgba(139,92,246,.07);color:var(--ink);transform:translateX(2px)}aside nav a.active{border-color:rgba(139,92,246,.24);background:linear-gradient(90deg,rgba(139,92,246,.16),rgba(34,211,238,.045));box-shadow:inset 3px 0 #8b5cf6;color:#ede9fe}.active .nav-icon{border-color:rgba(139,92,246,.35);background:rgba(139,92,246,.18);color:#ddd6fe}
.side-note{margin:auto 7px 0;padding:14px;border:1px solid var(--line);border-radius:13px;background:var(--surface-soft);color:var(--faint);font-size:11px;line-height:1.7}.side-note a{display:block;margin-top:8px;color:#c4b5fd;text-decoration:none;font-weight:750}
main{width:100%;max-width:1480px;margin:0 auto;padding:30px 38px 64px}.admin-topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:30px;padding-bottom:17px;border-bottom:1px solid var(--line)}.admin-search{display:flex;align-items:center;gap:9px;width:min(100%,310px);height:40px;padding:0 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:inset 0 1px rgba(255,255,255,.025);color:var(--faint);font-size:12px;backdrop-filter:blur(16px)}.admin-search .search-icon{color:#a78bfa;font-size:15px}.admin-search kbd{margin-left:auto;padding:2px 6px;border:1px solid var(--line);border-radius:6px;background:var(--surface-soft);color:var(--faint);font:10px ui-monospace,SFMono-Regular,Consolas,monospace}.admin-search input{height:100%;padding:0;border:0;background:transparent;box-shadow:none;color:var(--ink);font-size:12px}.admin-search input:focus{border:0;background:transparent;box-shadow:none}.admin-search input::placeholder{color:var(--faint)}.admin-tools{display:flex;align-items:center;gap:8px}.tool-button{display:grid;place-items:center;width:38px;height:38px;min-height:0;padding:0;border:1px solid var(--line);border-radius:11px;background:var(--surface);box-shadow:none;color:var(--muted);font-size:14px;text-decoration:none;animation:none}.tool-button:hover{border-color:var(--line-strong);background:rgba(139,92,246,.1);box-shadow:0 0 24px rgba(139,92,246,.08);color:var(--ink);transform:translateY(-1px)}
.admin-header{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:24px}.admin-kicker{display:block;margin-bottom:7px;background:linear-gradient(90deg,#a78bfa,#67e8f9);background-clip:text;-webkit-background-clip:text;color:transparent;font-size:10px;font-weight:850;letter-spacing:.18em;text-transform:uppercase}.admin-header h1{margin:0;color:var(--ink);font-size:29px;line-height:1.2;letter-spacing:-.045em}.admin-header p{margin:8px 0 0}.view-site{display:inline-flex;align-items:center;height:40px;padding:0 14px;border:1px solid var(--line);border-radius:11px;background:var(--surface);color:var(--muted);text-decoration:none;font-size:12px;font-weight:750;backdrop-filter:blur(14px);transition:.18s ease}.view-site:hover{border-color:var(--line-strong);color:var(--ink);box-shadow:0 0 24px rgba(139,92,246,.08)}
section{position:relative;margin-top:18px;padding:22px;border:1px solid transparent;border-radius:17px;background:linear-gradient(var(--surface-strong),var(--surface-strong)) padding-box,linear-gradient(125deg,rgba(139,92,246,.3),rgba(148,163,184,.1) 40%,rgba(34,211,238,.18)) border-box;box-shadow:var(--shadow);backdrop-filter:blur(20px)}section:before{content:"";position:absolute;left:20px;right:20px;top:0;height:1px;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(196,181,253,.45),rgba(103,232,249,.28),transparent)}section h2{margin:0 0 6px;color:var(--ink);font-size:17px;letter-spacing:-.02em}section>p.muted{margin:0 0 18px}section>form{margin-top:17px}
.muted{color:var(--muted)}.notice,.error{margin:0 0 15px;padding:12px 14px;border:1px solid;border-radius:12px;font-size:12px}.notice{border-color:rgba(74,222,128,.25);background:rgba(20,83,45,.2);color:#86efac}.error{border-color:rgba(251,113,133,.28);background:rgba(127,29,29,.2);color:#fda4af}.ok{color:var(--success);font-weight:750}.off{color:var(--warning);font-weight:750}.tag{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border:1px solid rgba(139,92,246,.2);border-radius:999px;background:rgba(139,92,246,.1);color:#c4b5fd;font-size:11px;font-weight:750}.tag:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}
table{width:100%;border-collapse:separate;border-spacing:0}th,td{padding:14px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--faint);font-size:11px;font-weight:820;letter-spacing:.07em;text-transform:uppercase}td{color:#cbd1df;font-size:13px}tbody tr:last-child td{border-bottom:0}tbody tr{transition:background .16s ease}tbody tr:hover{background:rgba(139,92,246,.035)}code{color:#a5f3fc;font:12px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.grid>p{display:flex;align-items:flex-end;margin:0}.grid>p button{width:100%}label{display:grid;align-content:start;gap:7px;color:#bac2d3;font-size:12px;font-weight:720}input,select,textarea{width:100%;min-width:0;padding:10px 12px;outline:0;border:1px solid var(--line);border-radius:11px;background:rgba(6,8,15,.66);color:var(--ink);font:inherit;transition:border-color .18s ease,box-shadow .18s ease,background .18s ease}input:not([type=file]),select{height:45px}input[type=file]{padding:9px}input[type=checkbox]{width:auto;height:auto;accent-color:var(--violet)}input:hover,select:hover,textarea:hover{border-color:rgba(196,181,253,.3)}input:focus,select:focus,textarea:focus{border-color:rgba(139,92,246,.82);background:rgba(8,11,20,.9);box-shadow:0 0 0 4px rgba(139,92,246,.11),0 0 20px rgba(34,211,238,.04)}textarea{min-height:82px;resize:vertical}option{background:#0d101b;color:#f7f8ff}input.invite-code{width:270px;max-width:100%;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
button{min-height:40px;padding:8px 13px;border:1px solid rgba(196,181,253,.28);border-radius:10px;background:linear-gradient(110deg,#6d28d9,#7c3aed 42%,#2563eb 74%,#0891b2);background-size:220% 100%;box-shadow:0 9px 24px rgba(109,40,217,.2),inset 0 1px rgba(255,255,255,.14);color:#fff;font:inherit;font-size:12px;font-weight:780;cursor:pointer;transition:transform .17s ease,box-shadow .17s ease;animation:admin-shimmer 6s ease-in-out infinite}button:hover{transform:translateY(-1px);box-shadow:0 13px 30px rgba(109,40,217,.28),0 0 20px rgba(34,211,238,.06)}button:active{transform:translateY(0)}button.danger{border-color:rgba(251,113,133,.34);background:rgba(127,29,29,.28);box-shadow:none;color:#fda4af;animation:none}button.danger:hover{background:rgba(159,18,57,.38);box-shadow:0 8px 20px rgba(127,29,29,.18)}button.secondary,button.copy-value{border-color:var(--line);background:var(--surface-soft);box-shadow:none;color:#cbd1df;animation:none}button.secondary:hover,button.copy-value:hover{border-color:var(--line-strong);background:rgba(139,92,246,.11)}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #67e8f9;outline-offset:3px}
form.inline{display:inline-flex;margin:2px 4px 2px 0}.copy-control{display:flex;align-items:center;gap:8px}.copy-control button{flex:0 0 auto}.compact{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px;margin-top:11px;padding:13px;border:1px solid var(--line);border-radius:12px;background:var(--surface-soft)}.compact label{min-width:135px;flex:1}.user-actions,.invite-actions{display:flex;align-items:center;flex-wrap:wrap;gap:7px}.user-actions form,.invite-actions form{margin:0}.user-actions button,.invite-actions button{min-height:34px;padding:6px 10px;font-size:11px}.row-editor{display:flex;align-items:flex-end;flex-wrap:wrap;gap:9px;margin-top:9px;padding:12px;border:1px solid var(--line);border-radius:12px;background:rgba(139,92,246,.045)}.row-editor[hidden]{display:none!important}.row-editor label{min-width:120px;flex:1}.row-editor input{height:38px;padding:6px 9px;font-size:12px}.row-editor .editor-actions{display:flex;gap:7px}.row-editor .editor-actions button{min-height:38px}.inline-delete{margin:7px 0 0}.invite-actions .tag{flex:0 0 auto}
details{margin-top:8px}summary{color:#a78bfa;font-size:12px;font-weight:680;cursor:pointer}.pagination{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:20px}.pagination a,.pagination span{padding:8px 12px;border:1px solid var(--line);border-radius:10px;font-size:11px}.pagination a{background:var(--surface-soft);color:#c4b5fd;text-decoration:none;font-weight:750}.pagination span{color:var(--faint)}.pagination b{color:var(--muted);font-size:11px}
.overview-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:22px}.overview-intro p{margin:0;color:var(--muted);font-size:13px}.overview-live{display:inline-flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:#aab3c6;font-size:11px;font-weight:700}.overview-live i{width:7px;height:7px;border-radius:50%;background:var(--success);box-shadow:0 0 0 4px rgba(74,222,128,.1),0 0 14px rgba(74,222,128,.5);animation:status-pulse 2.4s ease-in-out infinite}
.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin-bottom:18px}.metric-card{position:relative;min-height:122px;padding:17px;border:1px solid transparent;border-radius:16px;background:linear-gradient(var(--surface-strong),var(--surface-strong)) padding-box,linear-gradient(125deg,rgba(139,92,246,.42),rgba(148,163,184,.08) 48%,rgba(34,211,238,.25)) border-box;box-shadow:0 16px 44px rgba(0,0,0,.2);overflow:hidden}.metric-card header{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;color:var(--muted);font-size:11px}.metric-icon{display:grid;place-items:center;width:28px;height:28px;border:1px solid var(--line);border-radius:9px;background:var(--surface-soft);color:#c4b5fd;font-size:12px}.metric-card strong{position:relative;z-index:1;display:block;color:var(--ink);font-size:25px;line-height:1.1;letter-spacing:-.045em}.metric-card small{position:relative;z-index:1;display:block;margin-top:8px;color:var(--faint);font-size:10px}
.overview-columns{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(250px,.8fr);gap:18px}.overview-panel{margin-top:0;min-height:0}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:15px}.panel-heading h2{margin:0}.panel-heading p{margin:4px 0 0;color:var(--faint);font-size:11px}.panel-heading .panel-count{color:#a78bfa;font-size:11px;text-decoration:none}.node-overview-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.node-overview{padding:14px;border:1px solid var(--line);border-radius:13px;background:var(--surface-soft);transition:border-color .18s ease,transform .18s ease}.node-overview:hover{border-color:var(--line-strong);transform:translateY(-1px)}.node-overview header{display:flex;align-items:center;justify-content:space-between;gap:10px}.node-overview-title{display:flex;align-items:center;gap:9px;color:var(--ink);font-size:12px;font-weight:750}.node-overview-title .flag{font-size:18px}.node-state{color:var(--success);font-size:10px}.node-state:before{content:"●";margin-right:5px}.node-state.offline{color:var(--faint)}.node-overview-meta{display:flex;justify-content:space-between;gap:10px;margin-top:12px;color:var(--muted);font-size:10px}.node-progress{height:5px;margin-top:11px;overflow:hidden;border-radius:99px;background:rgba(148,163,184,.1)}.node-progress span{display:block;width:var(--progress,36%);height:100%;border-radius:inherit;background:linear-gradient(90deg,#8b5cf6,#22d3ee);box-shadow:0 0 12px rgba(34,211,238,.24)}.overview-list{display:grid}.overview-list-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 0;border-bottom:1px solid var(--line)}.overview-list-item:last-child{border-bottom:0}.overview-list-item strong{display:block;color:var(--ink);font-size:12px}.overview-list-item small{display:block;margin-top:3px;color:var(--faint);font-size:10px}.overview-list-item .list-value{color:var(--muted);font-size:11px;font-weight:700;text-align:right}.empty-state{padding:36px 12px;color:var(--faint);text-align:center;font-size:12px}
.admin-search input:not([type=file]){height:100%}
body[data-theme='light']{color-scheme:light;--bg:#f7f7fb;--sidebar:rgba(255,255,255,.9);--surface:rgba(255,255,255,.86);--surface-strong:#fff;--surface-soft:#f7f7fc;--ink:#171722;--muted:#697084;--faint:#9298a8;--line:rgba(67,72,92,.13);--line-strong:rgba(124,58,237,.25);--shadow:0 18px 55px rgba(55,46,92,.08);background:radial-gradient(circle at 78% -12%,rgba(139,92,246,.09),transparent 31%),radial-gradient(circle at 96% 82%,rgba(34,211,238,.07),transparent 27%),var(--bg)}body[data-theme='light']:before{opacity:.35;background-image:linear-gradient(rgba(99,102,241,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(99,102,241,.09) 1px,transparent 1px)}body[data-theme='light'] td{color:#41475a}body[data-theme='light'] input,body[data-theme='light'] select,body[data-theme='light'] textarea{background:rgba(255,255,255,.9)}body[data-theme='light'] option{background:#fff;color:#171722}body[data-theme='light'] .notice{color:#15803d}body[data-theme='light'] .error{color:#be123c}body[data-theme='light'] button.danger{background:#fff1f2;color:#be123c}
@keyframes admin-grid{to{transform:translate3d(44px,44px,0)}}@keyframes admin-orb{0%,100%{opacity:.58;transform:scale(.94) translate3d(0,0,0)}50%{opacity:1;transform:scale(1.06) translate3d(-24px,18px,0)}}@keyframes admin-shimmer{0%,100%{background-position:0 50%}50%{background-position:100% 50%}}@keyframes status-pulse{0%,100%{opacity:.7}50%{opacity:1;box-shadow:0 0 0 6px rgba(74,222,128,.08),0 0 18px rgba(74,222,128,.62)}}
@media(max-width:1040px){.layout{grid-template-columns:220px minmax(0,1fr)}main{padding:28px 24px 52px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-columns{grid-template-columns:1fr}}
@media(max-width:740px){.layout{display:block}aside{position:relative;display:block;width:100%;height:auto;padding:15px;border-right:0;border-bottom:1px solid var(--line)}.brand{margin:0 4px 14px}.side-label,.side-note{display:none}aside nav{display:flex;overflow-x:auto;gap:7px;margin:0;padding-bottom:3px;scrollbar-width:none}aside nav+nav{margin-top:7px}aside nav a{flex:0 0 auto;min-height:40px;padding:6px 10px}.nav-icon{width:25px;height:25px}main{padding:20px 13px 42px}.admin-topbar{margin-bottom:22px}.admin-search{width:100%}.admin-tools{display:none}.admin-header{align-items:center}.admin-header h1{font-size:25px}.view-site{display:none}.grid{grid-template-columns:1fr}section{padding:17px;border-radius:15px}table{display:block;overflow-x:auto;white-space:nowrap;-webkit-overflow-scrolling:touch}th,td{padding:12px 9px}.compact{display:grid}.copy-control{min-width:265px}.overview-intro{display:block}.overview-live{margin-top:13px}.overview-metrics{gap:9px}.metric-card{min-height:108px;padding:14px}.metric-card strong{font-size:22px}.node-overview-grid{grid-template-columns:1fr}}
@media(max-width:420px){.overview-metrics{grid-template-columns:1fr}.admin-header p{font-size:12px}.brand-copy small{display:none}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
"""

# Some media origins redirect large files to a dedicated, known storage host.
# Keep this list explicit: accepting a host from the redirect URL would turn
# every generated Nginx server into an unauthenticated forward proxy.
SAFE_REDIRECT_TARGETS = {
    "video.emos.best": "proxy.emosstore.sbs",
}

REGION_BADGES = (
    ("JP", "🇯🇵", ("日本", "东京", "大阪", "jp")),
    ("US", "🇺🇸", ("美国", "洛杉矶", "纽约", "西雅图", "us")),
    ("GB", "🇬🇧", ("英国", "伦敦", "gb", "uk")),
    ("HK", "🇭🇰", ("香港", "hk")),
    ("SG", "🇸🇬", ("新加坡", "sg")),
    ("KR", "🇰🇷", ("韩国", "首尔", "kr")),
    ("TW", "🇹🇼", ("台湾", "台北", "tw")),
    ("DE", "🇩🇪", ("德国", "法兰克福", "de")),
    ("IT", "🇮🇹", ("意大利", "米兰", "罗马", "it")),
    ("NL", "🇳🇱", ("荷兰", "阿姆斯特丹", "nl")),
    ("AU", "🇦🇺", ("澳大利亚", "悉尼", "au")),
)

COUNTRY_NAMES_ZH = {
    "AU": "澳大利亚", "CA": "加拿大", "DE": "德国", "FR": "法国", "GB": "英国",
    "HK": "香港", "IT": "意大利", "JP": "日本", "KR": "韩国", "NL": "荷兰", "SG": "新加坡",
    "TW": "台湾", "US": "美国",
}

CHINA_FLAG_SVG = (
    "<svg class='flag-icon' viewBox='0 0 30 20' role='img' aria-label='中国国旗'>"
    "<rect width='30' height='20' rx='1.5' fill='#de2910'/>"
    "<path fill='#ffde00' d='M5.4 3.2l.95 2.9 3.03.01-2.46 1.78.94 2.9-2.46-1.8-2.45 1.8.93-2.9-2.45-1.78 3.02-.01z'/>"
    "<path fill='#ffde00' d='M11.5 2.4l.28.84.88.01-.71.52.27.84-.72-.51-.71.51.27-.84-.71-.52.88-.01zM13.9 4.7l.28.84.88.01-.71.52.27.84-.72-.51-.71.51.27-.84-.71-.52.88-.01zM13.9 8l.28.84.88.01-.71.52.27.84-.72-.51-.71.51.27-.84-.71-.52.88-.01zM11.5 10.3l.28.84.88.01-.71.52.27.84-.72-.51-.71.51.27-.84-.71-.52.88-.01z'/>"
    "</svg>"
)

FLAG_SVG_BODIES = {
    "CN": "<rect width='30' height='20' fill='#de2910'/><path fill='#ffde00' d='M5.4 3.2l.95 2.9 3.03.01-2.46 1.78.94 2.9-2.46-1.8-2.45 1.8.93-2.9-2.45-1.78 3.02-.01z'/>",
    "HK": (
        "<rect width='30' height='20' fill='#de2910'/>"
        "<g fill='#fff'>"
        "<path d='M15 10c-1.8-1.4-2.4-3.4-1.1-5.4 2.7.5 4 2.5 3 4.8-.7.4-1.3.6-1.9.6z'/>"
        "<path d='M15 10c-1.8-1.4-2.4-3.4-1.1-5.4 2.7.5 4 2.5 3 4.8-.7.4-1.3.6-1.9.6z' transform='rotate(72 15 10)'/>"
        "<path d='M15 10c-1.8-1.4-2.4-3.4-1.1-5.4 2.7.5 4 2.5 3 4.8-.7.4-1.3.6-1.9.6z' transform='rotate(144 15 10)'/>"
        "<path d='M15 10c-1.8-1.4-2.4-3.4-1.1-5.4 2.7.5 4 2.5 3 4.8-.7.4-1.3.6-1.9.6z' transform='rotate(216 15 10)'/>"
        "<path d='M15 10c-1.8-1.4-2.4-3.4-1.1-5.4 2.7.5 4 2.5 3 4.8-.7.4-1.3.6-1.9.6z' transform='rotate(288 15 10)'/>"
        "<circle cx='15' cy='10' r='.65'/></g>"
    ),
    "JP": "<rect width='30' height='20' fill='#fff'/><circle cx='15' cy='10' r='6' fill='#bc002d'/>",
    "DE": "<path d='M0 0h30v6.67H0z'/><path d='M0 6.67h30v6.66H0z' fill='#dd0000'/><path d='M0 13.33h30V20H0z' fill='#ffce00'/>",
    "IT": "<path d='M0 0h10v20H0z' fill='#009246'/><path d='M10 0h10v20H10z' fill='#fff'/><path d='M20 0h10v20H20z' fill='#ce2b37'/>",
    "NL": "<path d='M0 0h30v6.67H0z' fill='#ae1c28'/><path d='M0 6.67h30v6.66H0z' fill='#fff'/><path d='M0 13.33h30V20H0z' fill='#21468b'/>",
    "TW": "<rect width='30' height='20' fill='#fe0000'/><rect width='15' height='10' fill='#000095'/><circle cx='7.5' cy='5' r='2.6' fill='#fff'/>",
    "SG": "<path d='M0 0h30v10H0z' fill='#ef3340'/><path d='M0 10h30v10H0z' fill='#fff'/><circle cx='7' cy='5' r='3.5' fill='#fff'/><circle cx='8.4' cy='5' r='3' fill='#ef3340'/><circle cx='11.2' cy='3.1' r='.55' fill='#fff'/><circle cx='12.5' cy='5' r='.55' fill='#fff'/><circle cx='11.2' cy='6.9' r='.55' fill='#fff'/>",
    "KR": "<rect width='30' height='20' fill='#fff'/><path d='M10 10a5 5 0 0 1 10 0 2.5 2.5 0 0 1-5 0 2.5 2.5 0 0 0-5 0' fill='#cd2e3a'/><path d='M20 10a5 5 0 0 1-10 0 2.5 2.5 0 0 1 5 0 2.5 2.5 0 0 0 5 0' fill='#0047a0'/><path d='M5 4l4 2M4.5 5l4 2M21 13l4 2M21.5 12l4 2M21 6l4-2M21.5 7l4-2M5 16l4-2M4.5 15l4-2' stroke='#111' stroke-width='.65'/>",
    "US": "<rect width='30' height='20' fill='#fff'/><path d='M0 0h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30V7.7H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30V20H0z' fill='#b22234'/><rect width='12.5' height='10.78' fill='#3c3b6e'/><g fill='#fff'><circle cx='2' cy='2' r='.55'/><circle cx='5' cy='2' r='.55'/><circle cx='8' cy='2' r='.55'/><circle cx='11' cy='2' r='.55'/><circle cx='3.5' cy='4.5' r='.55'/><circle cx='6.5' cy='4.5' r='.55'/><circle cx='9.5' cy='4.5' r='.55'/><circle cx='2' cy='7' r='.55'/><circle cx='5' cy='7' r='.55'/><circle cx='8' cy='7' r='.55'/><circle cx='11' cy='7' r='.55'/></g>",
    "GB": "<rect width='30' height='20' fill='#012169'/><path d='M0 0l30 20M30 0L0 20' stroke='#fff' stroke-width='4'/><path d='M0 0l30 20M30 0L0 20' stroke='#c8102e' stroke-width='1.5'/><path d='M15 0v20M0 10h30' stroke='#fff' stroke-width='6'/><path d='M15 0v20M0 10h30' stroke='#c8102e' stroke-width='3'/>",
    "AU": "<rect width='30' height='20' fill='#012169'/><path d='M0 0l13 9M13 0L0 9' stroke='#fff' stroke-width='2'/><path d='M6.5 0v9M0 4.5h13' stroke='#fff' stroke-width='3'/><path d='M6.5 0v9M0 4.5h13' stroke='#c8102e' stroke-width='1.4'/><g fill='#fff'><circle cx='21' cy='5' r='1'/><circle cx='25' cy='9' r='.8'/><circle cx='20' cy='14' r='.9'/><circle cx='26' cy='16' r='.75'/><circle cx='15' cy='12' r='1.2'/></g>",
}


def flag_svg_markup(code: str, label: str) -> str:
    normalized_code = code.upper()
    flag_code = "CN" if normalized_code in {"HK", "TW", "MO"} else normalized_code
    body = FLAG_SVG_BODIES.get(flag_code)
    if body is None:
        body = (
            "<rect width='30' height='20' fill='#7086b7'/>"
            "<circle cx='15' cy='10' r='6' fill='none' stroke='#fff' stroke-width='1.2'/>"
            "<path d='M9 10h12M15 4a10 10 0 0 1 0 12M15 4a10 10 0 0 0 0 12' fill='none' stroke='#fff' stroke-width='.8'/>"
        )
    aria = html.escape((label or code or "节点") + "旗帜", quote=True)
    return f"<svg class='flag-icon' viewBox='0 0 30 20' role='img' aria-label='{aria}'>{body}</svg>"

REQUEST_HEADERS_TO_DROP = (
    "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Port", "X-Forwarded-Proto",
    "X-Real-IP", "Forwarded", "Via", "CF-Connecting-IP", "CF-IPCountry", "CF-Ray",
    "CF-Visitor", "CDN-Loop", "True-Client-IP", "Client-IP", "Fastly-Client-IP",
    "Proxy-Client-IP", "WL-Proxy-Client-IP", "X-Client-IP", "X-Cluster-Client-IP",
    "X-Originating-IP", "X-Remote-Addr", "X-Remote-IP",
)
RESPONSE_HEADERS_TO_DROP = (
    "Alt-Svc", "CF-Cache-Status", "CF-Ray", "NEL", "Report-To", "Server",
    "Speculation-Rules", "Via", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version",
    "X-Backend-Server", "X-Cache", "X-Cache-Hits", "X-Runtime", "X-Served-By", "X-Timer",
)


class PanelError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def nginx_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class ProxyPanel:
    def __init__(self, normalize_origin):
        self.normalize_origin = normalize_origin
        self.username = os.environ.get("ADMIN_USERNAME", "admin")
        configured_password = os.environ.get("ADMIN_PASSWORD")
        self.admin_password_configured = configured_password is not None
        self.password = configured_password if configured_password is not None else DEFAULT_ADMIN_PASSWORD
        self.agent_token = os.environ.get("AGENT_TOKEN", "")
        self.local_agent_id = os.environ.get("LOCAL_AGENT_ID", "local-node")
        self.db_path = Path(os.environ.get("PANEL_DB_PATH", "/var/lib/uniproxy/panel.db"))
        self.default_domain = os.environ.get("PROXY_DOMAIN_SUFFIX", "").lower().strip(".")
        self.default_cert = os.environ.get("TLS_CERT_FILE", "")
        self.default_key = os.environ.get("TLS_KEY_FILE", "")
        self.default_nginx = os.environ.get("NGINX_CONFIG_FILE", "/etc/nginx/nginx.conf")
        self.default_generated = os.environ.get("GENERATED_NGINX_DIR", "/etc/nginx/conf.d")
        self.default_port = int(os.environ.get("PUBLIC_HTTPS_PORT", "443"))
        self.traffic_log_path = Path(os.environ.get("TRAFFIC_LOG_PATH", "/var/log/uniproxy-traffic.log"))
        self.auto_zone = os.environ.get("AUTO_NODE_ZONE", "example.com").lower().strip(".")
        self.acme_template = Path(os.environ.get("ACME_TEMPLATE_ARCHIVE", "/opt/uniproxy/acme-template.tgz"))
        self.acme_account = Path(os.environ.get("ACME_ACCOUNT_FILE", "/opt/uniproxy/acme-account.conf"))
        self.invite_key = os.environ.get("INVITE_CODE_ENCRYPTION_KEY", "").strip()
        self.user_route_creation_enabled = os.environ.get(
            "USER_ROUTE_CREATION_ENABLED", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self.allow_unprotected_egress = os.environ.get(
            "ALLOW_UNPROTECTED_EGRESS", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.minimum_password_length = max(
            1, min(256, int(os.environ.get("MINIMUM_PASSWORD_LENGTH", "1")))
        )
        self.password_policy = PasswordPolicy(
            min_characters=self.minimum_password_length,
            max_bytes=1024,
            common_passwords=frozenset(),
        )
        self.hash_limiter = HashWorkLimiter(
            max_concurrent=max(1, min(8, int(os.environ.get("PASSWORD_HASH_CONCURRENCY", "2")))),
            acquire_timeout=2.0,
            max_waiters=max(0, min(256, int(os.environ.get("PASSWORD_HASH_MAX_WAITERS", "32")))),
        )
        self.auth_throttle: PersistentAuthThrottle | None = None
        self._route_creation_locks: dict[int, threading.Lock] = {}
        self._route_creation_locks_guard = threading.Lock()
        self._cert_issue_lock = threading.Lock()
        self.protected_proxy_ips = tuple(
            item.strip() for item in os.environ.get("PROTECTED_PROXY_IPS", "").split(",")
            if item.strip()
        )
        try:
            self.user_origin_ports = frozenset(
                int(item.strip())
                for item in os.environ.get("USER_ORIGIN_ALLOWED_PORTS", "443,8443,8920,12172").split(",")
                if item.strip()
            )
        except ValueError as exc:
            raise RuntimeError("USER_ORIGIN_ALLOWED_PORTS contains a non-numeric port") from exc
        if not self.user_origin_ports or any(not 1 <= port <= 65535 for port in self.user_origin_ports):
            raise RuntimeError("USER_ORIGIN_ALLOWED_PORTS must contain ports in 1-65535")
        try:
            self.invite_cipher = Fernet(self.invite_key.encode("ascii")) if self.invite_key else None
        except (ValueError, UnicodeError):
            self.invite_cipher = None
        credential_key = os.environ.get("NODE_CREDENTIAL_ENCRYPTION_KEY", "").strip()
        try:
            self.node_credential_cipher = Fernet(credential_key.encode("ascii")) if credential_key else None
        except (ValueError, UnicodeError):
            raise RuntimeError("NODE_CREDENTIAL_ENCRYPTION_KEY must be a Fernet key")
        self._user_auth_failures: dict[str, list[float]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.password and self.default_domain and self.default_cert and self.default_key)

    @property
    def agent_enabled(self) -> bool:
        return bool(self.agent_token and SAFE_AGENT_ID.fullmatch(self.local_agent_id))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def setup(self) -> None:
        if not self.enabled:
            return
        self.db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS nodes ("
                "id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
                "kind TEXT NOT NULL CHECK(kind IN ('local','ssh')), "
                "ssh_host TEXT, ssh_port INTEGER NOT NULL DEFAULT 22, ssh_user TEXT, ssh_identity TEXT, ssh_password TEXT, "
                "domain_suffix TEXT NOT NULL, tls_cert_file TEXT NOT NULL, tls_key_file TEXT NOT NULL, "
                "caddy_config TEXT NOT NULL, generated_dir TEXT NOT NULL, "
                "public_https_port INTEGER NOT NULL DEFAULT 443, internal_https_port INTEGER NOT NULL DEFAULT 443, agent_id TEXT UNIQUE, last_seen TEXT, "
                "health_json TEXT NOT NULL DEFAULT '', traffic_rx INTEGER NOT NULL DEFAULT 0, "
                "traffic_tx INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS routes ("
                "id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE RESTRICT, "
                "name TEXT NOT NULL, origin TEXT NOT NULL, public_host TEXT NOT NULL UNIQUE, "
                "deployed INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS invites ("
                "id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, code_prefix TEXT NOT NULL, "
                "max_uses INTEGER NOT NULL, used_count INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL, "
                "account_days INTEGER, route_quota INTEGER NOT NULL DEFAULT 10, notes TEXT NOT NULL DEFAULT '', "
                "revoked_at TEXT, created_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS users ("
                "id INTEGER PRIMARY KEY, username TEXT NOT NULL, username_norm TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', route_quota INTEGER NOT NULL DEFAULT 10, "
                "expires_at TEXT, notes TEXT NOT NULL DEFAULT '', invite_id INTEGER REFERENCES invites(id) ON DELETE SET NULL, "
                "must_change_password INTEGER NOT NULL DEFAULT 0, is_admin INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "last_login_at TEXT NOT NULL DEFAULT '', last_login_ip TEXT NOT NULL DEFAULT '');"
                "CREATE TABLE IF NOT EXISTS user_sessions ("
                "token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "csrf_secret TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS login_events ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "success INTEGER NOT NULL, ip TEXT NOT NULL, created_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS invite_redemptions ("
                "id INTEGER PRIMARY KEY, invite_id INTEGER NOT NULL REFERENCES invites(id) ON DELETE RESTRICT, "
                "user_id INTEGER NOT NULL, username TEXT NOT NULL, redeemed_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS traffic_cursors ("
                "node_id INTEGER PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE, "
                "inode TEXT NOT NULL DEFAULT '', byte_offset INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS node_traffic_daily ("
                "day TEXT NOT NULL, node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, "
                "rx_bytes INTEGER NOT NULL DEFAULT 0, tx_bytes INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(day,node_id));"
                "CREATE TABLE IF NOT EXISTS user_traffic_daily ("
                "day TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "rx_bytes INTEGER NOT NULL DEFAULT 0, tx_bytes INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(day,user_id));"
                "CREATE TABLE IF NOT EXISTS deployment_jobs ("
                "id INTEGER PRIMARY KEY, route_id INTEGER REFERENCES routes(id) ON DELETE CASCADE, "
                "node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE RESTRICT, "
                "action TEXT NOT NULL CHECK(action IN ('deploy','delete','probe','decommission','refresh-origin')), "
                "state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','succeeded','failed','cancelled')), "
                "idempotency_key TEXT NOT NULL UNIQUE, attempts INTEGER NOT NULL DEFAULT 0, "
                "last_error TEXT NOT NULL DEFAULT '', available_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
            )
            schema_row = db.execute(
                "SELECT value FROM settings WHERE key='schema_version'"
            ).fetchone()
            try:
                previous_schema_version = int(schema_row["value"]) if schema_row else 1
            except (TypeError, ValueError):
                previous_schema_version = 1
            columns = {row["name"] for row in db.execute("PRAGMA table_info(nodes)")}
            migrations = {
                "agent_id": "TEXT",
                "last_seen": "TEXT",
                "health_json": "TEXT NOT NULL DEFAULT ''",
                "traffic_rx": "INTEGER NOT NULL DEFAULT 0",
                "traffic_tx": "INTEGER NOT NULL DEFAULT 0",
                "country_name": "TEXT NOT NULL DEFAULT ''",
                "country_code": "TEXT NOT NULL DEFAULT ''",
                "country_flag": "TEXT NOT NULL DEFAULT ''",
                "ssh_password": "TEXT",
                "ssh_password_ciphertext": "TEXT NOT NULL DEFAULT ''",
                "auto_managed": "INTEGER NOT NULL DEFAULT 0",
                "network_mode": "TEXT NOT NULL DEFAULT 'legacy'",
                "state": "TEXT NOT NULL DEFAULT 'active'",
                "state_step": "TEXT NOT NULL DEFAULT ''",
                "last_error": "TEXT NOT NULL DEFAULT ''",
                "dns_record_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "ssh_host_key": "TEXT NOT NULL DEFAULT ''",
                "ssh_host_fingerprint": "TEXT NOT NULL DEFAULT ''",
                "host_key_verified_at": "TEXT",
                "auth_mode": "TEXT NOT NULL DEFAULT 'root-bootstrap'",
                "cert_mode": "TEXT NOT NULL DEFAULT 'node-acme'",
                "security_policy_version": "INTEGER NOT NULL DEFAULT 1",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "ca_bundle_path": "TEXT NOT NULL DEFAULT '/etc/uniproxy-nginx/ca-bundle.pem'",
                "internal_https_port": "INTEGER NOT NULL DEFAULT 443",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE nodes ADD COLUMN {name} {definition}")
            route_columns = {row["name"] for row in db.execute("PRAGMA table_info(routes)")}
            route_state_added = "state" not in route_columns
            route_migrations = {
                "owner_user_id": "INTEGER REFERENCES users(id) ON DELETE RESTRICT",
                "suspended_by_owner": "INTEGER NOT NULL DEFAULT 0",
                "notes": "TEXT NOT NULL DEFAULT ''",
                "state": "TEXT NOT NULL DEFAULT 'pending'",
                "resolved_ips_json": "TEXT NOT NULL DEFAULT '[]'",
                "resolved_at": "TEXT",
                "upstream_security_status": "TEXT NOT NULL DEFAULT ''",
                "security_policy_version": "INTEGER NOT NULL DEFAULT 1",
                "redirect_token": "TEXT NOT NULL DEFAULT ''",
                "allow_insecure_http": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in route_migrations.items():
                if name not in route_columns:
                    db.execute(f"ALTER TABLE routes ADD COLUMN {name} {definition}")
            if route_state_added:
                db.execute(
                    "UPDATE routes SET state=CASE WHEN deployed=1 THEN 'deployed' ELSE 'failed' END"
                )
            user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "is_admin" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            invite_columns = {row["name"] for row in db.execute("PRAGMA table_info(invites)")}
            if "code_ciphertext" not in invite_columns:
                db.execute("ALTER TABLE invites ADD COLUMN code_ciphertext TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS nodes_agent_id_unique ON nodes(agent_id) WHERE agent_id IS NOT NULL")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS nodes_domain_suffix_unique ON nodes(domain_suffix)")
            db.execute("CREATE INDEX IF NOT EXISTS routes_owner_user_id_index ON routes(owner_user_id)")
            db.execute("CREATE INDEX IF NOT EXISTS user_sessions_expires_index ON user_sessions(expires_at)")
            db.execute("CREATE INDEX IF NOT EXISTS login_events_user_created_index ON login_events(user_id, created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS invite_redemptions_invite_index ON invite_redemptions(invite_id, id)")
            db.execute("CREATE INDEX IF NOT EXISTS deployment_jobs_state_available_index ON deployment_jobs(state, available_at, id)")
            db.execute("CREATE INDEX IF NOT EXISTS deployment_jobs_node_state_index ON deployment_jobs(node_id, state, id)")
            for route in db.execute("SELECT id FROM routes WHERE redirect_token = ''"):
                db.execute(
                    "UPDATE routes SET redirect_token=? WHERE id=?",
                    (secrets.token_urlsafe(24), route["id"]),
                )
            db.execute(
                "INSERT INTO settings (key,value) VALUES ('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            if previous_schema_version < 2:
                # Cookie names changed to the __Host- form.  Invalidate old
                # server-side sessions once so a legacy token cannot be
                # carried into the new authentication boundary.
                db.execute("DELETE FROM user_sessions")
            db.execute(
                "INSERT INTO invite_redemptions (invite_id,user_id,username,redeemed_at) "
                "SELECT users.invite_id,users.id,users.username,users.created_at FROM users "
                "WHERE users.invite_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM invite_redemptions WHERE invite_redemptions.invite_id=users.invite_id "
                "AND invite_redemptions.user_id=users.id)"
            )
            db.execute(
                "UPDATE nodes SET network_mode = CASE WHEN public_https_port = 443 THEN 'vps' ELSE 'nat' END "
                "WHERE network_mode NOT IN ('vps','nat')"
            )
            if self.node_credential_cipher:
                for legacy in db.execute("SELECT id,ssh_password FROM nodes WHERE COALESCE(ssh_password,'')!=''"):
                    ciphertext = self.node_credential_cipher.encrypt(str(legacy["ssh_password"]).encode()).decode()
                    db.execute(
                        "UPDATE nodes SET ssh_password='',ssh_password_ciphertext=? WHERE id=?",
                        (ciphertext, legacy["id"]),
                    )
            db.execute(
                "UPDATE nodes SET ca_bundle_path='/etc/ssl/certs/ca-certificates.crt' WHERE kind='local'"
            )
            # SSH host-key confirmation is intentionally non-blocking.  Keep
            # the legacy columns for compatibility, but reactivate nodes that
            # were marked pending by the short-lived confirmation workflow.
            db.execute(
                "UPDATE nodes SET state='active',state_step='',last_error='' "
                "WHERE kind!='local' AND state='legacy-ssh-unverified'"
            )
            local = db.execute("SELECT id FROM nodes WHERE kind = 'local' LIMIT 1").fetchone()
            local_disabled = db.execute("SELECT value FROM settings WHERE key = 'local_node_disabled'").fetchone()
            if local is None and local_disabled is None:
                cursor = db.execute(
                    "INSERT INTO nodes (name,kind,domain_suffix,tls_cert_file,tls_key_file,caddy_config,generated_dir,public_https_port,agent_id,created_at) "
                    "VALUES (?, 'local', ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("本机入口", self.default_domain, self.default_cert, self.default_key,
                     self.default_nginx, self.default_generated, self.default_port, self.local_agent_id, now()),
                )
                local_id = cursor.lastrowid
            elif local is not None:
                local_id = local["id"]
                db.execute("UPDATE nodes SET agent_id = ? WHERE id = ? AND (agent_id IS NULL OR agent_id = '')", (self.local_agent_id, local_id))
            else:
                local_id = None
            if local_id is not None:
                self._import_local_routes(db, local_id)
        self._sync_admin_account()
        os.chmod(self.db_path, 0o600)
        throttle_secret = os.environ.get("AUTH_THROTTLE_SECRET", "").strip()
        if not throttle_secret:
            with self._connect() as db:
                row = db.execute(
                    "SELECT value FROM settings WHERE key='auth_throttle_secret'"
                ).fetchone()
                if row:
                    throttle_secret = str(row["value"])
                else:
                    throttle_secret = secrets.token_urlsafe(32)
                    db.execute(
                        "INSERT INTO settings (key,value) VALUES ('auth_throttle_secret',?)",
                        (throttle_secret,),
                    )
        self.auth_throttle = PersistentAuthThrottle(self.db_path, throttle_secret)

    def _sync_admin_account(self) -> None:
        """Create or explicitly reset the single administrator account.

        The configured credentials seed the account once.  A later UI
        password change is kept in the database; changing the environment
        credentials is treated as an intentional emergency reset.
        """
        try:
            admin_username = self._normalize_username(self.username)
        except PanelError as exc:
            raise RuntimeError("ADMIN_USERNAME is invalid") from exc
        if not self.password:
            raise RuntimeError("ADMIN_PASSWORD is required")
        with self._connect() as db:
            secret_row = db.execute(
                "SELECT value FROM settings WHERE key='admin_env_sync_secret'"
            ).fetchone()
            if secret_row:
                sync_secret = str(secret_row["value"])
            else:
                sync_secret = secrets.token_urlsafe(32)
                db.execute(
                    "INSERT INTO settings (key,value) VALUES ('admin_env_sync_secret',?)",
                    (sync_secret,),
                )
            fingerprint = hmac.new(
                sync_secret.encode("utf-8"),
                (self.username + "\x00" + self.password).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            fingerprint_row = db.execute(
                "SELECT value FROM settings WHERE key='admin_env_fingerprint'"
            ).fetchone()
            admins = db.execute(
                "SELECT * FROM users WHERE is_admin=1 ORDER BY id"
            ).fetchall()
            if len(admins) > 1:
                raise RuntimeError("数据库中存在多个管理员账号，已停止启动")
            admin = admins[0] if admins else None
            conflict = db.execute(
                "SELECT id FROM users WHERE username_norm=? AND is_admin=0",
                (admin_username,),
            ).fetchone()
            if conflict and (admin is None or int(conflict["id"]) != int(admin["id"])):
                raise RuntimeError(
                    f"管理员用户名 {self.username!r} 已被普通用户占用，请修改 ADMIN_USERNAME 后重试"
                )
            if admin is None:
                timestamp = now()
                db.execute(
                    "INSERT INTO users (username,username_norm,password_hash,status,route_quota,expires_at,notes,"
                    "must_change_password,is_admin,created_at,updated_at) VALUES (?,?,?,'active',1000,NULL,?,?,1,?,?)",
                    (
                        self.username.strip(), admin_username, self._password_hash(self.password),
                        "系统管理员", int(self.password == DEFAULT_ADMIN_PASSWORD), timestamp, timestamp,
                    ),
                )
                db.execute(
                    "INSERT INTO settings (key,value) VALUES ('admin_env_fingerprint',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (fingerprint,),
                )
                return
            # If ADMIN_PASSWORD is omitted after the first deployment, preserve
            # the password changed through the account UI instead of resetting
            # it back to the public bootstrap password.
            if not self.admin_password_configured:
                db.execute(
                    "UPDATE users SET status='active',expires_at=NULL,is_admin=1,updated_at=? WHERE id=?",
                    (now(), admin["id"]),
                )
                return
            if fingerprint_row is None or str(fingerprint_row["value"]) != fingerprint:
                db.execute(
                    "UPDATE users SET username=?,username_norm=?,password_hash=?,status='active',"
                    "expires_at=NULL,must_change_password=?,is_admin=1,updated_at=? WHERE id=?",
                    (
                        self.username.strip(), admin_username, self._password_hash(self.password),
                        int(self.password == DEFAULT_ADMIN_PASSWORD), now(), admin["id"],
                    ),
                )
                db.execute("DELETE FROM user_sessions WHERE user_id=?", (admin["id"],))
                db.execute(
                    "INSERT INTO settings (key,value) VALUES ('admin_env_fingerprint',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (fingerprint,),
                )
            else:
                db.execute(
                    "UPDATE users SET status='active',expires_at=NULL,is_admin=1,updated_at=? WHERE id=?",
                    (now(), admin["id"]),
                )

    def _node_password(self, node) -> str:
        ciphertext = str(node["ssh_password_ciphertext"] or "") if "ssh_password_ciphertext" in node.keys() else ""
        if ciphertext:
            if not self.node_credential_cipher:
                raise PanelError("缺少 NODE_CREDENTIAL_ENCRYPTION_KEY，无法读取节点凭据")
            try:
                return self.node_credential_cipher.decrypt(ciphertext.encode()).decode()
            except Exception as exc:
                raise PanelError("节点 SSH 凭据解密失败") from exc
        return str(node["ssh_password"] or "")

    def _import_local_routes(self, db, node_id: int) -> None:
        directory = Path(self.default_generated)
        marker = re.compile(r"^# generated by uniproxy for (https?://\S+)$", re.MULTILINE)
        if not directory.is_dir():
            return
        for path in directory.glob("*.conf"):
            try:
                match = marker.search(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            if not match:
                continue
            host = path.name[:-5]
            if not SAFE_HOST.fullmatch(host):
                continue
            if db.execute("SELECT 1 FROM routes WHERE public_host = ?", (host,)).fetchone():
                continue
            db.execute(
                "INSERT INTO routes (node_id,name,origin,public_host,deployed,created_at,updated_at) VALUES (?,?,?,?,1,?,?)",
                (node_id, host.split(".", 1)[0], match.group(1), host, now(), now()),
            )

    def _client_ip(self, request: web.Request) -> str:
        peer = request.transport.get_extra_info("peername") if request.transport else None
        peer_ip = str(peer[0]) if peer else "unknown"
        try:
            trusted_proxy = ipaddress.ip_address(peer_ip).is_loopback
        except ValueError:
            trusted_proxy = False
        if trusted_proxy:
            forwarded = request.headers.get("X-Real-IP", "").strip()
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return peer_ip

    def require_admin(self, request: web.Request):
        """Require a live user session whose role is administrator."""
        user = self.require_user(request)
        if int(user["is_admin"] or 0) != 1:
            raise web.HTTPNotFound()
        return user

    @staticmethod
    def _normalize_username(value: str) -> str:
        username = value.strip()
        if not SAFE_USERNAME.fullmatch(username):
            raise PanelError("用户名只能包含字母、数字、点、下划线或连字符，且不能为空")
        if len(username.encode("utf-8")) > 1024:
            raise PanelError("用户名内容过长")
        return username.lower()

    @staticmethod
    def _password_hash(password: str) -> str:
        if not password:
            raise PanelError("密码不能为空")
        if len(password.encode("utf-8")) > 4096:
            raise PanelError("密码内容过长")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()

    def _validate_new_password(self, username: str, password: str) -> None:
        try:
            self.password_policy.require(password, username=username)
        except PasswordPolicyViolation as exc:
            if "too_short" in exc.violations:
                raise PanelError(f"密码至少需要 {self.minimum_password_length} 个字符") from exc
            if "too_long" in exc.violations:
                raise PanelError("密码内容过长") from exc
            if "matches_username" in exc.violations:
                raise PanelError("密码不能与账号相同") from exc
            if "whitespace_only" in exc.violations:
                raise PanelError("密码不能只包含空格") from exc
            raise PanelError("密码格式不符合要求") from exc

    @staticmethod
    def _password_matches(password: str, stored: str) -> bool:
        try:
            algorithm, n, r, p, salt_text, digest_text = stored.split("$", 5)
            if algorithm != "scrypt":
                return False
            salt = base64.urlsafe_b64decode(salt_text.encode())
            expected = base64.urlsafe_b64decode(digest_text.encode())
            actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            return False

    @staticmethod
    def _dummy_password_check() -> None:
        hashlib.scrypt(b"invalid-password", salt=b"uniproxy-auth-salt", n=2**14, r=8, p=1, dklen=32)

    @staticmethod
    def _future(days: int) -> str | None:
        return None if days == 0 else (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()

    @staticmethod
    def _is_user_active(user) -> bool:
        if not user or user["status"] != "active":
            return False
        expiry = user["expires_at"]
        return not expiry or expiry > now()

    @staticmethod
    def _display_expiry(value: str | None) -> str:
        if not value:
            return "永久"
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            return value[:10]

    def _session_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _create_user_session(self, user_id: int, remember: bool = True) -> tuple[str, str, int]:
        token = secrets.token_urlsafe(32)
        csrf_secret = secrets.token_urlsafe(32)
        lifetime = SESSION_REMEMBER_SECONDS if remember else SESSION_EPHEMERAL_SECONDS
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).replace(microsecond=0).isoformat()
        with self._connect() as db:
            db.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now(),))
            db.execute(
                "INSERT INTO user_sessions (token_hash,user_id,csrf_secret,expires_at,created_at) VALUES (?,?,?,?,?)",
                (self._session_hash(token), user_id, csrf_secret, expires, now()),
            )
        return token, csrf_secret, lifetime

    def _session_user(self, request: web.Request):
        token = request.cookies.get(USER_SESSION_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT users.*,user_sessions.csrf_secret,user_sessions.expires_at AS session_expires_at "
                "FROM user_sessions JOIN users ON users.id=user_sessions.user_id "
                "WHERE user_sessions.token_hash=? AND user_sessions.expires_at > ?",
                (self._session_hash(token), now()),
            ).fetchone()
            if not self._is_user_active(row):
                if row:
                    db.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
                return None
        return row

    def require_user(self, request: web.Request):
        user = self._session_user(request)
        if not user:
            raise web.HTTPFound("/login")
        return user

    def _clear_legacy_user_cookies(self, response: web.StreamResponse) -> None:
        for name in (LEGACY_USER_SESSION_COOKIE, LEGACY_USER_CSRF_COOKIE):
            response.del_cookie(name, path="/", secure=True)
            if self.auto_zone:
                response.del_cookie(name, domain=self.auto_zone, path="/", secure=True)

    def _set_user_session(self, response: web.StreamResponse, token: str, csrf_secret: str, max_age: int | None = None) -> None:
        self._clear_legacy_user_cookies(response)
        cookie_args = {"secure": True, "httponly": True, "samesite": "Strict", "path": "/"}
        csrf_args = {"secure": True, "httponly": False, "samesite": "Strict", "path": "/"}
        if max_age is not None:
            cookie_args["max_age"] = max_age
            csrf_args["max_age"] = max_age
        response.set_cookie(USER_SESSION_COOKIE, token, **cookie_args)
        response.set_cookie(USER_CSRF_COOKIE, csrf_secret, **csrf_args)

    def _clear_user_session(self, response: web.StreamResponse) -> None:
        response.del_cookie(USER_SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="Strict")
        response.del_cookie(USER_CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="Strict")
        self._clear_legacy_user_cookies(response)

    def _check_user_csrf(self, user, data) -> None:
        token = str(data.get("csrf", ""))
        if not token or not hmac.compare_digest(token, str(user["csrf_secret"])):
            raise web.HTTPForbidden(text="invalid form token")

    async def _enforce_user_auth_limit(self, request: web.Request, username: str) -> None:
        if self.auth_throttle is None:
            raise web.HTTPServiceUnavailable(text="authentication protection is unavailable")
        decision = await asyncio.to_thread(
            self.auth_throttle.precheck, self._client_ip(request), username
        )
        if not decision.allowed:
            raise web.HTTPTooManyRequests(
                text="too many authentication failures",
                headers={"Retry-After": str(decision.retry_after)},
            )

    async def _record_user_auth_failure(self, request: web.Request, username: str) -> None:
        if self.auth_throttle is None:
            raise web.HTTPServiceUnavailable(text="authentication protection is unavailable")
        decision = await asyncio.to_thread(
            self.auth_throttle.record_failure, self._client_ip(request), username
        )
        await asyncio.sleep(0.2)
        if not decision.allowed:
            raise web.HTTPTooManyRequests(
                text="too many authentication failures",
                headers={"Retry-After": str(decision.retry_after)},
            )

    async def _record_user_auth_success(self, request: web.Request, username: str) -> None:
        if self.auth_throttle is not None:
            await asyncio.to_thread(
                self.auth_throttle.record_success, self._client_ip(request), username
            )

    def _record_login_event(self, db, user_id: int, success: bool, client_ip: str) -> None:
        db.execute("INSERT INTO login_events (user_id,success,ip,created_at) VALUES (?,?,?,?)", (user_id, int(success), client_ip[:64], now()))
        db.execute("DELETE FROM login_events WHERE created_at < ?", ((datetime.now(timezone.utc) - timedelta(days=90)).replace(microsecond=0).isoformat(),))
        db.execute(
            "DELETE FROM login_events WHERE user_id=? AND id NOT IN "
            "(SELECT id FROM login_events WHERE user_id=? ORDER BY id DESC LIMIT 100)",
            (user_id, user_id),
        )

    def _authenticate_user(self, username: str, password: str, client_ip: str):
        try:
            normalized = self._normalize_username(username)
        except PanelError:
            self._dummy_password_check()
            return None
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE username_norm=?", (normalized,)).fetchone()
            valid = bool(user and self._is_user_active(user) and self._password_matches(password, user["password_hash"]))
            if not user:
                self._dummy_password_check()
                return None
            self._record_login_event(db, int(user["id"]), valid, client_ip)
            if not valid:
                return None
            db.execute("UPDATE users SET last_login_at=?,last_login_ip=?,updated_at=? WHERE id=?", (now(), client_ip[:64], now(), user["id"]))
            return db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()

    def _register_user(self, invite_code: str, username: str, password: str, client_ip: str):
        normalized = self._normalize_username(username)
        if normalized == str(self.username).strip().lower():
            raise PanelError("该用户名为系统保留名称")
        code_hash = hashlib.sha256(invite_code.strip().encode("utf-8")).hexdigest()
        with self._connect() as db:
            invite = db.execute("SELECT * FROM invites WHERE code_hash=?", (code_hash,)).fetchone()
            username_taken = db.execute(
                "SELECT 1 FROM users WHERE username_norm=?", (normalized,)
            ).fetchone()
        if not invite or invite["revoked_at"] or invite["expires_at"] <= now() or int(invite["used_count"]) >= int(invite["max_uses"]):
            raise PanelError("邀请码无效或已失效")
        if username_taken:
            raise PanelError("用户名已被使用")
        self._validate_new_password(username, password)
        password_hash = self._password_hash(password)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            invite = db.execute("SELECT * FROM invites WHERE code_hash=?", (code_hash,)).fetchone()
            if not invite or invite["revoked_at"] or invite["expires_at"] <= now() or int(invite["used_count"]) >= int(invite["max_uses"]):
                raise PanelError("邀请码无效或已失效")
            if normalized == str(self.username).strip().lower():
                raise PanelError("该用户名为系统保留名称")
            if db.execute("SELECT 1 FROM users WHERE username_norm=?", (normalized,)).fetchone():
                raise PanelError("用户名已被使用")
            expires_at = self._future(int(invite["account_days"])) if invite["account_days"] is not None else None
            cursor = db.execute(
                "INSERT INTO users (username,username_norm,password_hash,status,route_quota,expires_at,notes,invite_id,created_at,updated_at) "
                "VALUES (?,?,?,'active',?,?,?,?,?,?)",
                (username.strip(), normalized, password_hash, int(invite["route_quota"]), expires_at, "", invite["id"], now(), now()),
            )
            changed = db.execute(
                "UPDATE invites SET used_count=used_count+1 WHERE id=? AND used_count < max_uses",
                (invite["id"],),
            ).rowcount
            if changed != 1:
                raise PanelError("邀请码已被使用完")
            db.execute(
                "INSERT INTO invite_redemptions (invite_id,user_id,username,redeemed_at) VALUES (?,?,?,?)",
                (invite["id"], cursor.lastrowid, username.strip(), now()),
            )
            user_id = int(cursor.lastrowid)
            login_at = now()
            self._record_login_event(db, user_id, True, client_ip)
            db.execute(
                "UPDATE users SET last_login_at=?,last_login_ip=?,updated_at=? WHERE id=?",
                (login_at, client_ip[:64], login_at, user_id),
            )
            return user_id

    def _invalidate_user_sessions(self, user_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))

    def _agent_signature(self, timestamp: str, body: bytes) -> str:
        return hmac.new(self.agent_token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()

    async def agent_heartbeat(self, request: web.Request) -> web.Response:
        if request.method != "POST" or not self.agent_enabled:
            raise web.HTTPNotFound()
        body = await request.read()
        agent_id = request.headers.get("X-Agent-Id", "")
        timestamp = request.headers.get("X-Agent-Timestamp", "")
        signature = request.headers.get("X-Agent-Signature", "")
        if len(body) > 16 * 1024 or not SAFE_AGENT_ID.fullmatch(agent_id):
            raise web.HTTPBadRequest(text="bad heartbeat")
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise web.HTTPUnauthorized(text="bad timestamp") from exc
        if abs(time.time() - sent_at) > 120 or not hmac.compare_digest(signature, self._agent_signature(timestamp, body)):
            raise web.HTTPUnauthorized(text="bad signature")
        try:
            payload = json.loads(body.decode("utf-8"))
            services = payload["services"]
            if payload.get("agent_id") != agent_id or not isinstance(services, dict):
                raise ValueError("bad payload")
            rx_bytes = int(payload.get("rx_bytes", 0))
            tx_bytes = int(payload.get("tx_bytes", 0))
            if rx_bytes < 0 or tx_bytes < 0:
                raise ValueError("negative counters")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="bad heartbeat payload") from exc
        health = {
            "version": str(payload.get("version", ""))[:32],
            "services": {name: bool(services.get(name)) for name in ("nginx", "uniproxy", "hysteria-server")},
            "uptime_seconds": max(0, int(payload.get("uptime_seconds", 0))),
            "load1": max(0.0, float(payload.get("load1", 0))),
            "mem_available_kb": max(0, int(payload.get("mem_available_kb", 0))),
        }
        with self._connect() as db:
            updated = db.execute(
                "UPDATE nodes SET last_seen=?,health_json=?,traffic_rx=?,traffic_tx=? WHERE agent_id=?",
                (now(), json.dumps(health, separators=(",", ":")), rx_bytes, tx_bytes, agent_id),
            ).rowcount
        if updated != 1:
            raise web.HTTPNotFound(text="unknown agent")
        return web.json_response({"ok": True, "next_heartbeat_seconds": 60})

    @staticmethod
    def _health_summary(node) -> str:
        if not node["last_seen"]:
            return "等待心跳"
        try:
            health = json.loads(node["health_json"] or "{}")
            services = health.get("services", {})
            broken = [name for name, alive in services.items() if not alive]
            if broken:
                return "异常：" + ", ".join(broken)
            return f"正常 · 负载 {health.get('load1', 0):.2f} · 可用内存 {health.get('mem_available_kb', 0) // 1024} MiB"
        except (TypeError, ValueError, json.JSONDecodeError):
            return "心跳数据无效"

    @staticmethod
    def _format_bytes(value: int) -> str:
        return f"{max(0, int(value)) / (1024 ** 3):.2f} GB"

    def _traffic_format_config(self) -> str:
        return (
            f"log_format {TRAFFIC_FORMAT_NAME} "
            "'$server_name|$request_length|$bytes_sent|$upstream_bytes_sent|$upstream_bytes_received';\n"
        )

    @staticmethod
    def _traffic_byte_value(value: str) -> int:
        if value == "-":
            return 0
        return sum(int(item) for item in re.findall(r"\d+", value))

    @staticmethod
    def _complete_traffic_chunk(inode: str, start: int, payload: bytes) -> tuple[str, int, bytes]:
        if not payload:
            return inode, start, b""
        last_newline = payload.rfind(b"\n")
        if last_newline < 0:
            return inode, start, b""
        consumed = last_newline + 1
        return inode, start + consumed, payload[:consumed]

    def _read_traffic_chunk(self, node, cursor_inode: str, cursor_offset: int) -> tuple[str, int, bytes]:
        if node["kind"] == "local":
            path = self.traffic_log_path
            if not path.is_file():
                return "0", 0, b""
            stat = path.stat()
            inode = str(stat.st_ino)
            start = cursor_offset if inode == cursor_inode and stat.st_size >= cursor_offset else 0
            with path.open("rb") as file:
                file.seek(start)
                payload = file.read(TRAFFIC_MAX_CHUNK_BYTES)
            return self._complete_traffic_chunk(inode, start, payload)

        log_path = shlex.quote(str(self.traffic_log_path))
        expected_inode = shlex.quote(cursor_inode)
        script = "\n".join([
            "set -eu", "export LC_ALL=C",
            f"file={log_path}",
            "if [ ! -f \"$file\" ]; then printf '0 0 0\\n'; exit 0; fi",
            "inode=$(stat -Lc '%i' \"$file\")", "size=$(stat -Lc '%s' \"$file\")",
            f"start={max(0, int(cursor_offset))}",
            f"if [ \"$inode\" != {expected_inode} ] || [ \"$size\" -lt \"$start\" ]; then start=0; fi",
            "remaining=$((size - start))", f"limit={TRAFFIC_MAX_CHUNK_BYTES}",
            "if [ \"$remaining\" -gt \"$limit\" ]; then count=$limit; else count=$remaining; fi",
            "printf '%s %s %s\\n' \"$inode\" \"$start\" \"$count\"",
            "if [ \"$count\" -gt 0 ]; then tail -c \"+$((start + 1))\" \"$file\" | head -c \"$count\"; fi",
        ])
        result = subprocess.run(
            self._ssh_args(node) + [script], capture_output=True, timeout=40, env=self._ssh_env(node),
        )
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", "replace").strip()
            raise PanelError(error[-300:] or "读取节点流量失败")
        metadata, separator, payload = result.stdout.partition(b"\n")
        if not separator:
            raise PanelError("节点流量响应格式错误")
        match = re.fullmatch(rb"(\d+) (\d+) (\d+)", metadata)
        if not match:
            raise PanelError("节点流量元数据无效")
        inode = match.group(1).decode("ascii")
        start = int(match.group(2))
        count = int(match.group(3))
        if len(payload) < count:
            raise PanelError("节点流量读取不完整")
        return self._complete_traffic_chunk(inode, start, payload[:count])

    def _collect_node_traffic(self, node) -> None:
        node_id = int(node["id"])
        with self._connect() as db:
            cursor = db.execute(
                "SELECT inode,byte_offset FROM traffic_cursors WHERE node_id=?", (node_id,),
            ).fetchone()
            routes = db.execute(
                "SELECT public_host,owner_user_id FROM routes WHERE node_id=? AND deployed=1", (node_id,),
            ).fetchall()
        cursor_inode = str(cursor["inode"]) if cursor else ""
        cursor_offset = int(cursor["byte_offset"]) if cursor else 0
        inode, next_offset, payload = self._read_traffic_chunk(node, cursor_inode, cursor_offset)
        route_owners = {str(route["public_host"]): route["owner_user_id"] for route in routes}
        node_rx = 0
        node_tx = 0
        user_totals: dict[int, list[int]] = {}
        for raw_line in payload.splitlines():
            if len(raw_line) > 1024:
                continue
            try:
                fields = raw_line.decode("ascii").split("|")
            except UnicodeDecodeError:
                continue
            if len(fields) != 5 or fields[0] not in route_owners:
                continue
            request_bytes = self._traffic_byte_value(fields[1])
            response_bytes = self._traffic_byte_value(fields[2])
            upstream_sent = self._traffic_byte_value(fields[3])
            upstream_received = self._traffic_byte_value(fields[4])
            rx_bytes = request_bytes + upstream_received
            tx_bytes = response_bytes + upstream_sent
            node_rx += rx_bytes
            node_tx += tx_bytes
            owner_user_id = route_owners[fields[0]]
            if owner_user_id is not None:
                total = user_totals.setdefault(int(owner_user_id), [0, 0])
                total[0] += rx_bytes
                total[1] += tx_bytes

        day = datetime.now(TRAFFIC_TIMEZONE).date().isoformat()
        updated_at = now()
        with self._connect() as db:
            if node_rx or node_tx:
                db.execute(
                    "INSERT INTO node_traffic_daily (day,node_id,rx_bytes,tx_bytes) VALUES (?,?,?,?) "
                    "ON CONFLICT(day,node_id) DO UPDATE SET rx_bytes=rx_bytes+excluded.rx_bytes,tx_bytes=tx_bytes+excluded.tx_bytes",
                    (day, node_id, node_rx, node_tx),
                )
            for user_id, (rx_bytes, tx_bytes) in user_totals.items():
                db.execute(
                    "INSERT INTO user_traffic_daily (day,user_id,rx_bytes,tx_bytes) VALUES (?,?,?,?) "
                    "ON CONFLICT(day,user_id) DO UPDATE SET rx_bytes=rx_bytes+excluded.rx_bytes,tx_bytes=tx_bytes+excluded.tx_bytes",
                    (day, user_id, rx_bytes, tx_bytes),
                )
            db.execute(
                "INSERT INTO traffic_cursors (node_id,inode,byte_offset,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(node_id) DO UPDATE SET inode=excluded.inode,byte_offset=excluded.byte_offset,updated_at=excluded.updated_at",
                (node_id, inode, next_offset, updated_at),
            )
            db.execute("UPDATE nodes SET last_seen=? WHERE id=?", (updated_at, node_id))

    def collect_traffic_usage(self) -> list[str]:
        with self._connect() as db:
            nodes = db.execute(
                "SELECT DISTINCT nodes.* FROM nodes JOIN routes ON routes.node_id=nodes.id WHERE routes.deployed=1 ORDER BY nodes.id"
            ).fetchall()
        errors = []
        for node in nodes:
            try:
                self._collect_node_traffic(node)
            except Exception as exc:
                errors.append(f"{node['name']}：{str(exc)[-200:]}")
        return errors

    def _traffic_summaries(self, table: str, key: str) -> dict[int, dict[str, int]]:
        if (table, key) not in {("node_traffic_daily", "node_id"), ("user_traffic_daily", "user_id")}:
            raise ValueError("unsupported traffic summary")
        today = datetime.now(TRAFFIC_TIMEZONE).date().isoformat()
        month = today[:7] + "%"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT {key} AS item_id,"
                "SUM(CASE WHEN day=? THEN rx_bytes ELSE 0 END) AS today_rx,"
                "SUM(CASE WHEN day=? THEN tx_bytes ELSE 0 END) AS today_tx,"
                "SUM(CASE WHEN day LIKE ? THEN rx_bytes+tx_bytes ELSE 0 END) AS month_total,"
                "SUM(rx_bytes+tx_bytes) AS all_total "
                f"FROM {table} GROUP BY {key}",
                (today, today, month),
            ).fetchall()
        return {
            int(row["item_id"]): {
                "today_rx": int(row["today_rx"] or 0), "today_tx": int(row["today_tx"] or 0),
                "month_total": int(row["month_total"] or 0), "all_total": int(row["all_total"] or 0),
            }
            for row in rows
        }

    def _format_traffic_usage(self, usage: dict[str, int] | None) -> str:
        usage = usage or {}
        today_rx = int(usage.get("today_rx", 0))
        today_tx = int(usage.get("today_tx", 0))
        today_total = today_rx + today_tx
        return (
            f"今日 {self._format_bytes(today_total)}（入 {self._format_bytes(today_rx)} / 出 {self._format_bytes(today_tx)}）"
            f"<br><span class='muted'>本月 {self._format_bytes(int(usage.get('month_total', 0)))} · "
            f"累计 {self._format_bytes(int(usage.get('all_total', 0)))}</span>"
        )

    @staticmethod
    def _slug_from_origin(origin: str) -> str:
        host = (urlsplit(origin).hostname or "emby").lower()
        parts = [part for part in host.split(".") if part and part not in {"www", "emby", "jellyfin"}]
        slug = re.sub(r"[^a-z0-9-]+", "-", parts[0] if parts else host.split(".")[0]).strip("-") or "emby"
        if len(slug) < 3:
            slug = "emby-" + slug
        return slug[:24].strip("-") or "emby"

    def _origin_security_policy(self, *, allow_insecure_http: bool = False) -> OriginSecurityPolicy:
        node_addresses: list[str] = []
        with self._connect() as db:
            rows = db.execute(
                "SELECT ssh_host FROM nodes WHERE ssh_host IS NOT NULL AND ssh_host != ''"
            ).fetchall()
        for row in rows:
            try:
                node_addresses.append(str(ipaddress.ip_address(str(row["ssh_host"]))))
            except ValueError:
                continue
        try:
            protected = tuple(str(ipaddress.ip_address(item)) for item in self.protected_proxy_ips)
        except ValueError as exc:
            raise PanelError("PROTECTED_PROXY_IPS 配置包含无效 IP") from exc
        owned_domains = tuple(
            dict.fromkeys(domain for domain in (self.auto_zone, self.default_domain) if domain)
        )
        return OriginSecurityPolicy(
            owned_domains=owned_domains,
            node_addresses=tuple(node_addresses),
            proxy_addresses=protected,
            allowed_schemes=("https", "http") if allow_insecure_http else ("https",),
            max_addresses=8,
        )

    def _resolve_route_origin(
        self, origin: str, *, allow_insecure_http: bool = False, enforce_user_ports: bool = True
    ) -> SafeOriginResolution:
        try:
            resolved = resolve_origin_safely(
                origin,
                policy=self._origin_security_policy(allow_insecure_http=allow_insecure_http),
            )
        except OriginSecurityError as exc:
            messages = {
                "scheme-not-allowed": "普通用户线路只允许使用 HTTPS 源站",
                "owned-origin": "源站不能指向本面板、节点或其他反代线路",
                "proxy-loop": "源站解析到了本项目节点，已拒绝代理环路",
                "mixed-address-space": "源站同时解析到公网和内网地址，已拒绝",
                "non-global-address": "源站解析到了非公网地址",
                "resolution-failed": "源站域名解析失败",
            }
            raise PanelError(messages.get(exc.code, "源站地址未通过安全检查")) from exc
        if enforce_user_ports and resolved.port not in self.user_origin_ports:
            allowed = "、".join(str(port) for port in sorted(self.user_origin_ports))
            raise PanelError(f"普通用户源站端口仅允许：{allowed}")
        return resolved

    @staticmethod
    def _public_url(node, host: str) -> str:
        port = int(node["public_https_port"])
        suffix = "" if port == 443 else f":{port}"
        return f"https://{host}{suffix}/"

    def frontend_nodes(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        nodes = []
        for row in rows:
            name = row["name"].strip()
            lowered_name = name.lower()
            code = row["country_code"] or name[:4] or "节点"
            flag = row["country_flag"] or "🖥️"
            country_name = row["country_name"]
            if not row["country_code"]:
                for candidate_code, candidate_flag, aliases in REGION_BADGES:
                    if any(alias in lowered_name for alias in aliases):
                        code, flag = candidate_code, candidate_flag
                        country_name = COUNTRY_NAMES_ZH.get(candidate_code, name)
                        break
            base = row["domain_suffix"]
            port = int(row["public_https_port"])
            node_host = f"{base}{'' if port == 443 else ':' + str(port)}"
            probe_url = f"https://{node_host}/__health"
            nodes.append({
                "id": row["id"],
                "name": name,
                "code": code,
                "flag": flag,
                "flag_markup": flag_svg_markup(code, country_name or name),
                "country_name": country_name,
                "is_local": row["kind"] == "local",
                "icon": "🖥️" if row["kind"] == "local" else "🌐",
                "health": self._health_summary(row),
                "probe_url": probe_url,
                "host": node_host,
                "online": bool(row["last_seen"]),
            })
        return nodes

    def create_frontend_route(self, origin: str, node_id: int, user_id: int, notes: str = "") -> tuple[str, str]:
        with self._route_creation_locks_guard:
            lock = self._route_creation_locks.setdefault(int(user_id), threading.Lock())
        if not lock.acquire(timeout=2):
            raise PanelError("线路创建正在处理中，请稍后重试")
        try:
            return self._create_frontend_route_locked(origin, node_id, user_id, notes)
        finally:
            lock.release()

    def _create_frontend_route_locked(self, origin: str, node_id: int, user_id: int, notes: str = "") -> tuple[str, str]:
        """Allocate an address owned by one user; never share it across accounts."""
        if not self.user_route_creation_enabled:
            raise PanelError("线路创建暂时关闭，管理员正在进行安全升级")
        resolution = self._resolve_route_origin(origin)
        origin = resolution.origin
        resolved_json = json.dumps(resolution.addresses, separators=(",", ":"))
        resolved_at = now()
        notes = notes.strip()
        if len(notes) > 500:
            raise PanelError("线路备注不能超过 500 个字符")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not self._is_user_active(user):
                raise PanelError("账号已停用或已到期")
            node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not node:
                raise PanelError("所选节点不存在")
            existing = db.execute(
                "SELECT * FROM routes WHERE node_id=? AND origin=? AND owner_user_id=? ORDER BY id LIMIT 1",
                (node_id, origin, user_id),
            ).fetchone()
            if existing:
                route = existing
                db.execute(
                    "UPDATE routes SET resolved_ips_json=?,resolved_at=?,upstream_security_status='verified',updated_at=? WHERE id=?",
                    (resolved_json, resolved_at, now(), route["id"]),
                )
                route = db.execute("SELECT * FROM routes WHERE id=?", (route["id"],)).fetchone()
            else:
                used = int(db.execute("SELECT COUNT(*) FROM routes WHERE owner_user_id=?", (user_id,)).fetchone()[0])
                if used >= int(user["route_quota"]):
                    raise PanelError(f"线路额度已用完（{used}/{int(user['route_quota'])}），请先删除不需要的线路")
                slug = self._slug_from_origin(origin)
                route = None
                for index in range(1, 1000):
                    name = slug if index == 1 else f"{slug}{index}"
                    host = f"{name}.{node['domain_suffix']}"
                    if not db.execute("SELECT 1 FROM routes WHERE public_host = ?", (host,)).fetchone():
                        cursor = db.execute(
                            "INSERT INTO routes (node_id,name,origin,public_host,deployed,owner_user_id,suspended_by_owner,notes,state,resolved_ips_json,resolved_at,upstream_security_status,security_policy_version,redirect_token,created_at,updated_at) "
                            "VALUES (?,?,?,?,0,?,0,?,'pending',?,?,'verified',2,?,?,?)",
                            (node_id, name, origin, host, user_id, notes, resolved_json, resolved_at, secrets.token_urlsafe(24), now(), now()),
                        )
                        route = db.execute("SELECT * FROM routes WHERE id = ?", (cursor.lastrowid,)).fetchone()
                        break
                if route is None:
                    raise PanelError("无法分配线路地址")
        if not route["deployed"]:
            self._deploy_and_verify(node, route)
        return route["public_host"], self._public_url(node, route["public_host"])

    def user_routes(self, user_id: int) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT routes.*,nodes.name AS node_name,nodes.public_https_port FROM routes "
                "JOIN nodes ON nodes.id=routes.node_id WHERE routes.owner_user_id=? ORDER BY routes.id DESC",
                (user_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            port = int(row["public_https_port"])
            item["public_url"] = f"https://{row['public_host']}{'' if port == 443 else ':' + str(port)}/"
            result.append(item)
        return result

    def user_route_usage(self, user_id: int) -> tuple[int, int]:
        with self._connect() as db:
            user = db.execute("SELECT route_quota FROM users WHERE id=?", (user_id,)).fetchone()
            used = int(db.execute("SELECT COUNT(*) FROM routes WHERE owner_user_id=?", (user_id,)).fetchone()[0])
        return used, int(user["route_quota"]) if user else 0

    def delete_user_route(self, user_id: int, route_id: int) -> None:
        with self._connect() as db:
            route = db.execute("SELECT * FROM routes WHERE id=? AND owner_user_id=?", (route_id, user_id)).fetchone()
            if not route:
                raise PanelError("线路不存在或无权操作")
            node = db.execute("SELECT * FROM nodes WHERE id=?", (route["node_id"],)).fetchone()
        # A failed/pending deployment is safe to remove from the panel even when
        # the node has already gone away.  A confirmed deployment still needs
        # remote cleanup so we do not silently leave a live route behind.
        self._delete_route_file_best_effort(node, route)
        with self._connect() as db:
            db.execute("DELETE FROM routes WHERE id=? AND owner_user_id=?", (route_id, user_id))

    def update_user_route_note(self, user_id: int, route_id: int, notes: str) -> None:
        notes = notes.strip()
        if len(notes) > 500:
            raise PanelError("线路备注不能超过 500 个字符")
        with self._connect() as db:
            changed = db.execute(
                "UPDATE routes SET notes=?,updated_at=? WHERE id=? AND owner_user_id=?",
                (notes, now(), route_id, user_id),
            ).rowcount
        if changed != 1:
            raise PanelError("线路不存在或无权操作")

    def _anonymous_csrf(self, request: web.Request) -> str:
        token = request.cookies.get(USER_CSRF_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            return secrets.token_urlsafe(32)
        return token

    def _check_anonymous_csrf(self, request: web.Request, data) -> None:
        cookie = request.cookies.get(USER_CSRF_COOKIE, "")
        submitted = str(data.get("csrf", ""))
        if not cookie or not hmac.compare_digest(cookie, submitted):
            raise web.HTTPForbidden(text="invalid form token")

    def _user_page(self, title: str, content: str, csrf_token: str | None = None, error: str = "", notice: str = "") -> web.Response:
        messages = ""
        if error:
            messages += f"<p class='error'>{html.escape(error)}</p>"
        if notice:
            messages += f"<p class='notice'>{html.escape(notice)}</p>"
        body = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#ffffff'>
<title>Emby Relay · {html.escape(title)}</title><style>{AUTH_UI_CSS}</style></head><body data-theme='light'>
<button type='button' id='theme-toggle' class='auth-theme-toggle' title='切换主题' aria-label='切换主题'>◐</button>
<main class='auth-shell'>
  <section class='auth-intro' aria-label='Emby Relay'>
    <div class='brand-lockup'><span class='brand-copy'><strong>Emby Relay</strong><small>节点与线路管理</small></span></div>
  </section>
  <section class='auth-panel'><div class='auth-card'>{messages}{content}</div></section>
</main>
<script>
const themeKey = 'emby-relay-admin-theme';
const themeToggle = document.getElementById('theme-toggle');
let savedTheme = '';
try {{ savedTheme = localStorage.getItem(themeKey) || ''; }} catch (e) {{}}
function applyTheme(theme) {{
  const resolved = theme === 'dark' ? 'dark' : 'light';
  document.body.dataset.theme = resolved;
  if (themeToggle) {{ themeToggle.textContent = resolved === 'dark' ? '☼' : '◐'; }}
  try {{ localStorage.setItem(themeKey, resolved); }} catch (e) {{}}
}}
applyTheme(savedTheme || 'light');
themeToggle?.addEventListener('click', () => {{
  applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
}});
</script>
</body></html>"""
        response = web.Response(text=body, content_type="text/html")
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        })
        self._clear_legacy_user_cookies(response)
        if csrf_token:
            response.set_cookie(USER_CSRF_COOKIE, csrf_token, secure=True, httponly=False, samesite="Strict", max_age=SESSION_EPHEMERAL_SECONDS, path="/")
        return response

    def login_page(self, request: web.Request, error: str = "") -> web.Response:
        csrf_token = self._anonymous_csrf(request)
        content = f"""<h1>登录</h1>
<form method='post' action='/login'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><label>用户名<input required name='username' autocomplete='username'></label><label>密码<input required type='password' name='password' autocomplete='current-password'></label><label class='checkline'><input type='checkbox' name='remember' value='1' checked> 保持登录 90 天</label><button>登录</button></form><p class='links'><span>没有账号？</span><a href='/register'>使用邀请码注册</a></p>"""
        return self._user_page("登录", content, csrf_token=csrf_token, error=error)

    def register_page(self, request: web.Request, error: str = "") -> web.Response:
        csrf_token = self._anonymous_csrf(request)
        content = f"""<h1>邀请码注册</h1>
<form method='post' action='/register'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><label>邀请码<input required name='invite_code' autocomplete='off' maxlength='128'></label><label>用户名<input required name='username' autocomplete='username' pattern='[A-Za-z0-9._-]+'></label><label>密码<input required type='password' name='password' autocomplete='new-password'></label><label>确认密码<input required type='password' name='confirm_password' autocomplete='new-password'></label><button>注册并登录</button></form><p class='links'><span>已有账号？</span><a href='/login'>返回登录</a></p>"""
        return self._user_page("注册", content, csrf_token=csrf_token, error=error)

    def account_page(self, request: web.Request, user, error: str = "", notice: str = "") -> web.Response:
        content = f"""<h1>账号安全</h1><p class='muted'>账号：{html.escape(user['username'])} · 有效期：{html.escape(self._display_expiry(user['expires_at']))}</p>
<form method='post' action='/account/password'><input type='hidden' name='csrf' value='{html.escape(user['csrf_secret'], quote=True)}'><label>当前密码<input required type='password' name='current_password' autocomplete='current-password'></label><label>新密码<input required type='password' name='new_password' autocomplete='new-password'></label><label>确认新密码<input required type='password' name='confirm_password' autocomplete='new-password'></label><button>修改密码</button></form><p class='links'><a href='/'>返回主界面</a></p>"""
        return self._user_page("账号安全", content, error=error, notice=notice)

    def _change_user_password(self, user_id: int, current_password: str, new_password: str) -> None:
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user or not self._password_matches(current_password, user["password_hash"]):
                raise PanelError("当前密码不正确")
            old_hash = str(user["password_hash"])
            username = str(user["username"])
        self._validate_new_password(username, new_password)
        new_hash = self._password_hash(new_password)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE users SET password_hash=?,must_change_password=0,updated_at=? "
                "WHERE id=? AND password_hash=?",
                (new_hash, now(), user_id, old_hash),
            ).rowcount
            if changed != 1:
                raise PanelError("密码已被其他操作修改，请重新登录后再试")
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))

    async def handle_user(self, request: web.Request) -> web.StreamResponse:
        path = request.path
        if path == "/login":
            if request.method == "GET":
                if self._session_user(request):
                    raise web.HTTPFound("/")
                return self.login_page(request)
            if request.method == "POST":
                data = await request.post()
                self._check_anonymous_csrf(request, data)
                username = str(data.get("username", ""))
                remember = str(data.get("remember", "")) == "1"
                await self._enforce_user_auth_limit(request, username)
                try:
                    user = await self.hash_limiter.run(
                        self._authenticate_user,
                        username,
                        str(data.get("password", "")),
                        self._client_ip(request),
                    )
                except HashWorkLimitExceeded as exc:
                    raise web.HTTPServiceUnavailable(
                        text="password service is busy", headers={"Retry-After": "3"}
                    ) from exc
                if not user:
                    await self._record_user_auth_failure(request, username)
                    return self.login_page(request, error="用户名或密码错误，或账号已停用/到期")
                await self._record_user_auth_success(request, username)
                token, csrf_secret, lifetime = await asyncio.to_thread(
                    self._create_user_session, int(user["id"]), remember
                )
                response = web.HTTPFound("/account" if user["must_change_password"] else "/")
                self._set_user_session(response, token, csrf_secret, lifetime if remember else None)
                return response
        if path == "/register":
            if request.method == "GET":
                return self.register_page(request)
            if request.method == "POST":
                data = await request.post()
                self._check_anonymous_csrf(request, data)
                username = str(data.get("username", ""))
                await self._enforce_user_auth_limit(request, username)
                password = str(data.get("password", ""))
                if password != str(data.get("confirm_password", "")):
                    await self._record_user_auth_failure(request, username)
                    return self.register_page(request, error="两次输入的密码不一致")
                try:
                    user_id = await self.hash_limiter.run(
                        self._register_user,
                        str(data.get("invite_code", "")),
                        username,
                        password,
                        self._client_ip(request),
                    )
                except HashWorkLimitExceeded as exc:
                    raise web.HTTPServiceUnavailable(
                        text="password service is busy", headers={"Retry-After": "3"}
                    ) from exc
                except PanelError as exc:
                    await self._record_user_auth_failure(request, username)
                    return self.register_page(request, error=str(exc))
                await self._record_user_auth_success(request, username)
                token, csrf_secret, lifetime = await asyncio.to_thread(
                    self._create_user_session, user_id, True
                )
                response = web.HTTPFound("/")
                self._set_user_session(response, token, csrf_secret, lifetime)
                return response
        if path == "/logout" and request.method == "POST":
            user = self.require_user(request)
            data = await request.post()
            self._check_user_csrf(user, data)
            await asyncio.to_thread(self._invalidate_user_sessions, int(user["id"]))
            response = web.HTTPFound("/login")
            self._clear_user_session(response)
            return response
        if path == "/account":
            if request.method != "GET":
                raise web.HTTPMethodNotAllowed(request.method, ["GET"])
            return self.account_page(request, self.require_user(request))
        if path == "/account/password" and request.method == "POST":
            user = self.require_user(request)
            data = await request.post()
            self._check_user_csrf(user, data)
            await self._enforce_user_auth_limit(request, str(user["username"]))
            if str(data.get("new_password", "")) != str(data.get("confirm_password", "")):
                return self.account_page(request, user, error="两次输入的新密码不一致")
            try:
                await self.hash_limiter.run(
                    self._change_user_password,
                    int(user["id"]),
                    str(data.get("current_password", "")),
                    str(data.get("new_password", "")),
                )
            except HashWorkLimitExceeded as exc:
                raise web.HTTPServiceUnavailable(
                    text="password service is busy", headers={"Retry-After": "3"}
                ) from exc
            except PanelError as exc:
                await self._record_user_auth_failure(request, str(user["username"]))
                return self.account_page(request, user, error=str(exc))
            await self._record_user_auth_success(request, str(user["username"]))
            response = web.HTTPFound("/login")
            self._clear_user_session(response)
            return response
        route_match = re.fullmatch(r"/my/routes/(\d+)/(delete|note)", path)
        if route_match and request.method == "POST":
            user = self.require_user(request)
            if user["must_change_password"]:
                raise web.HTTPFound("/account")
            data = await request.post()
            self._check_user_csrf(user, data)
            route_id, action = int(route_match.group(1)), route_match.group(2)
            if action == "delete":
                await asyncio.to_thread(self.delete_user_route, int(user["id"]), route_id)
            else:
                await asyncio.to_thread(self.update_user_route_note, int(user["id"]), route_id, str(data.get("notes", "")))
            raise web.HTTPFound("/")
        raise web.HTTPNotFound()

    def _page(self, content: str, notice: str = "", error: str = "", active: str = "nodes") -> web.Response:
        message = ""
        if notice:
            message += f"<p class='notice'>{html.escape(notice)}</p>"
        if error:
            message += f"<p class='error'>{html.escape(error)}</p>"
        nonce = secrets.token_urlsafe(16)
        overview_class = " active" if active == "overview" else ""
        nodes_class = " active" if active == "nodes" else ""
        routes_class = " active" if active == "routes" else ""
        users_class = " active" if active == "users" else ""
        invites_class = " active" if active == "invites" else ""
        page_title = {"overview": "运行概览", "nodes": "节点面板", "routes": "线路管理", "users": "用户管理", "invites": "邀请码管理"}.get(active, "管理后台")
        page_subtitle = {
            "overview": "统一查看节点、线路和流量运行状态。",
            "nodes": "线路只影响新请求；正在播放的 Emby 连接不会被自动迁移。",
            "routes": "创建、验证、重新下发或移除反代线路。",
            "users": "账号、额度、到期状态与登录记录。",
            "invites": "创建、查看、撤销或删除邀请码及其兑换记录。",
        }.get(active, "")
        body = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#111927'>
<title>Emby Relay · {html.escape(page_title)}</title><style>{ADMIN_UI_CSS}</style></head><body>
<div class='layout'><aside>
  <a class='brand' href='/'><span class='brand-symbol' aria-hidden='true'>✦</span><span class='brand-copy'><strong>Emby Relay</strong><small>管理控制台</small></span></a>
  <p class='side-label'>监控</p>
  <nav aria-label='后台模块'>
    <a class='{overview_class}' data-admin-page='运行概览' href='{ADMIN_PREFIX}/overview'><span class='nav-icon'>O</span>运行概览</a>
    <a class='{nodes_class}' data-admin-page='节点面板' href='{ADMIN_PREFIX}/nodes'><span class='nav-icon'>N</span>节点面板</a>
  </nav>
  <p class='side-label'>管理</p>
  <nav aria-label='管理模块'>
    <a class='{routes_class}' data-admin-page='线路管理' href='{ADMIN_PREFIX}/routes'><span class='nav-icon'>R</span>线路管理</a>
    <a class='{users_class}' data-admin-page='用户管理' href='{ADMIN_PREFIX}/users'><span class='nav-icon'>U</span>用户管理</a>
    <a class='{invites_class}' data-admin-page='邀请码管理' href='{ADMIN_PREFIX}/invites'><span class='nav-icon'>I</span>邀请码管理</a>
  </nav>
  <p class='side-note'>节点和线路操作只影响新连接。<a href='/'>← 返回用户界面</a></p>
</aside><main>
  <div class='admin-topbar'><label class='admin-search' for='admin-page-search'><span class='search-icon'>⌕</span><input id='admin-page-search' type='search' placeholder='搜索页面' autocomplete='off' aria-label='搜索后台页面'><kbd>Ctrl K</kbd></label><div class='admin-tools'><a class='tool-button' href='/account' aria-label='账号安全' title='账号安全'>⚙</a><button type='button' class='tool-button' id='fullscreen-toggle' aria-label='全屏' title='全屏'>↗</button><button type='button' class='tool-button' id='theme-toggle' aria-label='切换主题' title='切换主题'>◐</button></div></div>
  <header class='admin-header'><div><span class='admin-kicker'>Emby Relay</span><h1>{page_title}</h1><p class='muted'>{page_subtitle}</p></div><a class='view-site' href='/'>查看用户界面 ↗</a></header>"""
        copy_script = """<script nonce='__CSP_NONCE__'>
async function copyPanelValue(value) { try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(value); return true; } const field = document.createElement('textarea'); field.value = value; field.readOnly = true; field.style.cssText = 'position:fixed;opacity:0'; document.body.append(field); field.select(); const copied = document.execCommand('copy'); field.remove(); return copied; } catch (error) { return false; } }
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => { const label = button.textContent; button.textContent = (await copyPanelValue(button.dataset.copy)) ? '已复制' : '复制失败'; setTimeout(() => button.textContent = label, 1200); }));
const adminSearch = document.getElementById('admin-page-search');
const adminLinks = Array.from(document.querySelectorAll('[data-admin-page]'));
const focusAdminSearch = () => { if (adminSearch) { adminSearch.focus(); adminSearch.select(); } };
const filterAdminLinks = () => { const query = (adminSearch?.value || '').trim().toLowerCase(); adminLinks.forEach(link => { link.hidden = Boolean(query) && !link.dataset.adminPage.toLowerCase().includes(query); }); };
adminSearch?.addEventListener('input', filterAdminLinks);
adminSearch?.addEventListener('keydown', event => { if (event.key === 'Escape') { adminSearch.value = ''; filterAdminLinks(); adminSearch.blur(); } if (event.key === 'Enter') { const target = adminLinks.find(link => !link.hidden); if (target) target.click(); } });
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); focusAdminSearch(); } });
const themeToggle = document.getElementById('theme-toggle');
const themeKey = 'emby-relay-admin-theme';
let savedTheme = '';
try { savedTheme = localStorage.getItem(themeKey) || ''; } catch (error) {}
const applyTheme = theme => { document.body.dataset.theme = theme === 'dark' ? 'dark' : 'light'; if (themeToggle) themeToggle.textContent = theme === 'dark' ? '☼' : '◐'; try { localStorage.setItem(themeKey, document.body.dataset.theme); } catch (error) {} };
applyTheme(savedTheme || 'dark');
themeToggle?.addEventListener('click', () => applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark'));
const fullscreenToggle = document.getElementById('fullscreen-toggle');
fullscreenToggle?.addEventListener('click', async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch (error) {} });
document.querySelectorAll('.toggle-user-edit').forEach(button => { const panel = button.closest('td')?.querySelector('.user-edit-panel'); if (!panel) return; button.addEventListener('click', () => { const open = panel.hidden; panel.hidden = !open; button.setAttribute('aria-expanded', String(open)); button.textContent = open ? '收起' : '编辑'; if (open) panel.querySelector('input')?.focus(); }); });
document.querySelectorAll('.cancel-inline-edit').forEach(button => button.addEventListener('click', () => { const panel = button.closest('.user-edit-panel'); const toggle = button.closest('td')?.querySelector('.toggle-user-edit'); if (panel) panel.hidden = true; if (toggle) { toggle.setAttribute('aria-expanded', 'false'); toggle.textContent = '编辑'; } }));
document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
</script>""".replace("__CSP_NONCE__", nonce)
        body += message + content.replace("__CSP_NONCE__", nonce) + copy_script + "</main></div></body></html>"
        response = web.Response(text=body, content_type="text/html")
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        })
        return response

    def overview_dashboard(self, notice: str = "", error: str = "", csrf_token: str = "") -> web.Response:
        with self._connect() as db:
            nodes = db.execute("SELECT * FROM nodes ORDER BY id").fetchall()
            route_total = int(db.execute("SELECT COUNT(*) FROM routes").fetchone()[0])
            deployed_routes = int(db.execute("SELECT COUNT(*) FROM routes WHERE deployed=1").fetchone()[0])
            user_total = int(db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0])
            invite_total = int(db.execute("SELECT COUNT(*) FROM invites WHERE revoked_at IS NULL AND expires_at > ?", (now(),)).fetchone()[0])
            recent_routes = db.execute(
                "SELECT routes.name,routes.public_host,routes.deployed,nodes.name AS node_name "
                "FROM routes JOIN nodes ON nodes.id=routes.node_id ORDER BY routes.updated_at DESC, routes.id DESC LIMIT 6"
            ).fetchall()
        node_usage = self._traffic_summaries("node_traffic_daily", "node_id")
        node_count = len(nodes)
        online_nodes = sum(1 for node in nodes if str(node["state"] or "active") == "active")
        today_total = sum(int(item.get("today_rx", 0)) + int(item.get("today_tx", 0)) for item in node_usage.values())
        month_total = sum(int(item.get("month_total", 0)) for item in node_usage.values())
        max_node_total = max((int(item.get("all_total", 0)) for item in node_usage.values()), default=0)

        node_cards = []
        locations: dict[str, int] = {}
        for node in nodes:
            node_id = int(node["id"])
            usage = node_usage.get(node_id, {})
            total = int(usage.get("all_total", 0))
            progress = min(100, max(8, round(total * 100 / max_node_total))) if max_node_total else 8
            location = " ".join(filter(None, (node["country_flag"], node["country_name"]))) or "未识别地区"
            locations[location] = locations.get(location, 0) + 1
            active = str(node["state"] or "active") == "active"
            state_label = "在线" if active else "离线"
            state_class = "" if active else " offline"
            node_cards.append(
                f"<article class='node-overview'><header><div class='node-overview-title'><span class='flag'>{html.escape(node['country_flag'] or '◌')}</span><span>{html.escape(node['name'])}</span></div><span class='node-state{state_class}'>{state_label}</span></header>"
                f"<div class='node-overview-meta'><span>{html.escape(location)}</span><span>{self._format_bytes(total)} 累计</span></div><div class='node-progress' style='--progress:{progress}%;'><span></span></div></article>"
            )
        node_grid = "".join(node_cards) or "<div class='empty-state'>暂无节点，请先在节点面板添加服务器。</div>"
        location_rows = "".join(
            f"<div class='overview-list-item'><span><strong>{html.escape(location)}</strong><small>节点位置</small></span><span class='list-value'>{count} 个</span></div>"
            for location, count in sorted(locations.items(), key=lambda item: (-item[1], item[0]))
        ) or "<div class='empty-state'>暂无地区数据</div>"
        route_rows = "".join(
            f"<div class='overview-list-item'><span><strong>{html.escape(route['name'])}</strong><small>{html.escape(route['node_name'])}</small></span><span class='list-value'>{'已下发' if route['deployed'] else '待处理'}</span></div>"
            for route in recent_routes
        ) or "<div class='empty-state'>暂无线路</div>"
        content = f"""
<div class='overview-intro'><div><p>实时流量、线路请求与节点健康状态</p></div><span class='overview-live'><i></i>网关在线</span></div>
<div class='overview-metrics'>
  <article class='metric-card'><header><span>今日总流量</span><span class='metric-icon'>↓</span></header><strong>{self._format_bytes(today_total)}</strong><small>节点入站与出站合计</small></article>
  <article class='metric-card'><header><span>本月总流量</span><span class='metric-icon'>↗</span></header><strong>{self._format_bytes(month_total)}</strong><small>按北京时间统计</small></article>
  <article class='metric-card'><header><span>活跃线路</span><span class='metric-icon'>⌁</span></header><strong>{deployed_routes}<small style='display:inline;margin:0 0 0 4px;font-size:11px;color:#a1a1aa'>/ {route_total}</small></strong><small>已下发 / 全部线路</small></article>
  <article class='metric-card'><header><span>在线节点</span><span class='metric-icon'>⌾</span></header><strong>{online_nodes}<small style='display:inline;margin:0 0 0 4px;font-size:11px;color:#a1a1aa'>/ {node_count}</small></strong><small>{user_total} 个普通用户 · {invite_total} 个可用邀请码</small></article>
</div>
<div class='overview-columns'>
  <section class='overview-panel'><div class='panel-heading'><div><h2>节点概览</h2><p>按节点查看位置、状态和累计用量</p></div><span class='panel-count'>{node_count} 个节点</span></div><div class='node-overview-grid'>{node_grid}</div></section>
  <div class='overview-side'><section class='overview-panel'><div class='panel-heading'><div><h2>地区分布</h2><p>节点所在地区</p></div></div><div class='overview-list'>{location_rows}</div></section><section class='overview-panel'><div class='panel-heading'><div><h2>最近线路</h2><p>最近更新的访问入口</p></div><a class='panel-count' href='{ADMIN_PREFIX}/routes'>查看全部</a></div><div class='overview-list'>{route_rows}</div></section></div>
</div>"""
        return self._page(content, notice, error, active="overview")

    def dashboard(self, notice: str = "", error: str = "", route_page: int = 1, csrf_token: str = "") -> web.Response:
        csrf_token = html.escape(csrf_token, quote=True)
        try:
            route_page = max(1, int(route_page))
        except (TypeError, ValueError):
            route_page = 1
        with self._connect() as db:
            nodes = db.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        node_usage = self._traffic_summaries("node_traffic_daily", "node_id")
        node_rows_list = []
        for node in nodes:
            node_id = int(node["id"])
            check_token = csrf_token
            delete_token = csrf_token
            kind = "本机" if node["kind"] == "local" else "SSH"
            if node["kind"] == "ssh":
                mode = "普通 VPS" if node["network_mode"] == "vps" else "NAT"
                kind += f"<br><span class='muted'>{mode} · 公网 HTTPS {int(node['public_https_port'])} → 内部 {int(node['internal_https_port'])}</span>"
            health = self._health_summary(node)
            traffic = self._format_traffic_usage(node_usage.get(node_id))
            location = " ".join(filter(None, (node["country_flag"], node["country_name"], node["country_code"]))) or "未识别"
            check_form = f"<form class='inline' method='post' action='{ADMIN_PREFIX}/nodes/{node_id}/check'><input type='hidden' name='csrf' value='{check_token}'><button type='submit' class='action-check'>检查</button></form>"
            delete_form = f" <form class='inline' method='post' action='{ADMIN_PREFIX}/nodes/{node_id}/delete'><input type='hidden' name='csrf' value='{delete_token}'><button type='submit' class='danger'>删除节点</button></form>"
            node_rows_list.append(
                f"<tr><td>{html.escape(node['name'])}</td><td>{kind}</td><td>{html.escape(location)}</td><td><code>{html.escape(node['domain_suffix'])}</code></td><td>{html.escape(health)}<br><span class='muted'>状态：{html.escape(node['state'] or 'active')} · 采集：{html.escape(node['last_seen'] or '暂无')}</span><br>{traffic}</td><td>{check_form}{delete_form}</td></tr>"
            )
        node_rows = "".join(node_rows_list) or "<tr><td colspan='6' class='muted'>还没有节点</td></tr>"
        content = f"""
<section><h2>节点</h2><table><thead><tr><th>名称</th><th>类型</th><th>地区</th><th>域名后缀</th><th>状态 / 代理用量</th><th>操作</th></tr></thead><tbody>{node_rows}</tbody></table></section>
<section><h2>新增节点</h2><p class='muted'>公网 HTTPS 端口是用户访问时使用的端口，内部 HTTPS 端口是节点 Nginx 实际监听的端口，默认都是 443；两者可以独立填写。若远端已安装 Nginx，系统会自动读取它的 HTTPS 监听端口并优先使用，忽略你填写的内部端口。NAT 机需要让服务商把公网端口映射到内部端口。</p><form method='post' enctype='multipart/form-data' action='{ADMIN_PREFIX}/nodes'><div class='grid'><label>节点名称<input required name='name' placeholder='海创'></label><label>网络类型<select required name='network_mode' id='network-mode'><option value='vps'>普通 VPS（独立公网 IP）</option><option value='nat'>NAT 机（端口映射）</option></select></label><label>服务器公网 IP<input required name='ssh_host' inputmode='decimal' placeholder='162.141.136.85'></label><label>SSH 端口<input required name='ssh_port' value='22' inputmode='numeric'></label><label>公网 HTTPS 端口<input required id='public-port' name='public_https_port' value='443' inputmode='numeric'><span class='muted'>NAT 默认可填服务商分配的端口，例如 30004</span></label><label>内部 HTTPS 端口<input required name='internal_https_port' value='443' inputmode='numeric'><span class='muted'>Nginx 监听端口；远端已有 Nginx 时自动识别</span></label><label>SSH 密码（与私钥二选一）<input type='password' name='ssh_password' autocomplete='new-password'></label><label>SSH 私钥文件（与密码二选一）<input type='file' name='ssh_private_key' accept='.pem,.key,text/plain,application/x-pem-file'></label></div><p><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button>自动部署并添加</button></p></form><script nonce='__CSP_NONCE__'>(()=>{{const mode=document.getElementById('network-mode'),publicPort=document.getElementById('public-port');const sync=()=>{{if(mode.value==='nat'&&publicPort.value==='443')publicPort.value='30004';if(mode.value==='vps'&&publicPort.value==='30004')publicPort.value='443';}};mode.addEventListener('change',sync);}})();</script></section>"""
        content = content.replace("自动读取它的 HTTPS 监听端口", "自动读取它的监听端口")
        content = content.replace("Nginx 监听端口，不能使用 80；远端已有 Nginx 时自动识别", "Nginx 监听端口；远端已有 Nginx 时自动识别")
        content = content.replace("placeholder='海创'", "")
        content = content.replace("placeholder='162.141.136.85'", "")
        return self._page(content, notice, error)

    def routes_dashboard(self, notice: str = "", error: str = "", route_page: int = 1, csrf_token: str = "") -> web.Response:
        csrf_token = html.escape(csrf_token, quote=True)
        try:
            route_page = max(1, int(route_page))
        except (TypeError, ValueError):
            route_page = 1
        with self._connect() as db:
            nodes = db.execute("SELECT * FROM nodes ORDER BY id").fetchall()
            route_total = int(db.execute("SELECT COUNT(*) FROM routes").fetchone()[0])
            route_pages = max(1, (route_total + ADMIN_ROUTE_PAGE_SIZE - 1) // ADMIN_ROUTE_PAGE_SIZE)
            route_page = min(route_page, route_pages)
            route_offset = (route_page - 1) * ADMIN_ROUTE_PAGE_SIZE
            routes = db.execute(
                "SELECT routes.*,nodes.name AS node_name,nodes.public_https_port FROM routes "
                "JOIN nodes ON nodes.id=routes.node_id ORDER BY routes.id DESC LIMIT ? OFFSET ?",
                (ADMIN_ROUTE_PAGE_SIZE, route_offset),
            ).fetchall()
        node_options = "".join(
            f"<option value='{node['id']}'>{html.escape(node['name'])}</option>" for node in nodes
        ) or "<option value='' disabled selected>请先添加节点</option>"
        route_rows_list = []
        for route in routes:
            public_port = int(route["public_https_port"])
            public_suffix = "" if public_port == 443 else f":{public_port}"
            public_url = f"https://{route['public_host']}{public_suffix}/"
            state_class = "ok" if route["deployed"] else "off"
            state = "已下发" if route["deployed"] else "未下发"
            if route["last_error"]:
                state += f"<br><span class='error'>{html.escape(route['last_error'])}</span>"
            route_rows_list.append(
                f"<tr><td>{html.escape(route['name'])}</td><td><code>{html.escape(route['origin'])}</code></td><td><code>{html.escape(public_url)}</code></td><td>{html.escape(route['node_name'])}</td><td class='{state_class}'>{state}</td><td>"
                f"<form class='inline' method='post' action='{ADMIN_PREFIX}/routes/{route['id']}/deploy?page={route_page}'><input type='hidden' name='csrf' value='{csrf_token}'><button>下发</button></form> "
                f"<form class='inline' method='post' action='{ADMIN_PREFIX}/routes/{route['id']}/delete?page={route_page}'><input type='hidden' name='csrf' value='{csrf_token}'><button class='danger'>删除</button></form></td></tr>"
            )
        route_rows = "".join(route_rows_list) or "<tr><td colspan='6' class='muted'>还没有线路</td></tr>"
        if route_pages > 1:
            previous = f"<a href='{ADMIN_PREFIX}/routes?page={route_page - 1}'>上一页</a>" if route_page > 1 else "<span>上一页</span>"
            next_page = f"<a href='{ADMIN_PREFIX}/routes?page={route_page + 1}'>下一页</a>" if route_page < route_pages else "<span>下一页</span>"
            route_pagination = f"<nav class='pagination'>{previous}<b>第 {route_page} / {route_pages} 页 · 共 {route_total} 条</b>{next_page}</nav>"
        else:
            route_pagination = ""
        content = f"""
<section><h2>线路列表</h2><p class='muted'>线路是面向用户的访问入口；节点是承载线路的服务器。重新下发只影响新请求，正在播放的连接不会自动迁移。</p><table><thead><tr><th>名称</th><th>源站</th><th>公开地址</th><th>节点</th><th>状态</th><th>操作</th></tr></thead><tbody>{route_rows}</tbody></table>{route_pagination}</section>
<section><h2>新增线路</h2><p class='muted'>创建后会自动下发 Nginx，并从公网访问新地址确认链路；验证结果会直接显示。</p><form method='post' action='{ADMIN_PREFIX}/routes'><div class='grid'><label>线路名称（小写英文、数字、连字符）<input required name='name' pattern='[a-z0-9][a-z0-9-]{{1,31}}' placeholder='emby-a'></label><label>源站地址<input required name='origin' placeholder='https://emby.example.com'></label><label>部署节点<select required name='node_id'>{node_options}</select></label></div><p><input type='hidden' name='csrf' value='{csrf_token}'><button>创建、下发并验证</button></p></form></section>"""
        return self._page(content, notice, error, active="routes")

    @staticmethod
    def _bounded_int(value: object, field: str, lower: int, upper: int) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError) as exc:
            raise PanelError(f"{field}必须是数字") from exc
        if not lower <= parsed <= upper:
            raise PanelError(f"{field}需在 {lower}–{upper} 之间")
        return parsed

    @staticmethod
    def _expiry_from_date(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
        except ValueError as exc:
            raise PanelError("有效期格式不正确") from exc
        return parsed.isoformat()

    def _user_status_label(self, user) -> str:
        if user["status"] != "active":
            return "已停用"
        if user["expires_at"] and user["expires_at"] <= now():
            return "已到期"
        return "正常"

    def _encrypt_invite_code(self, code: str) -> str:
        if not self.invite_cipher:
            raise PanelError("邀请码加密密钥未配置，无法创建邀请码")
        return self.invite_cipher.encrypt(code.encode("utf-8")).decode("ascii")

    def _decrypt_invite_code(self, invite) -> str | None:
        ciphertext = str(invite["code_ciphertext"] or "")
        if not ciphertext or not self.invite_cipher:
            return None
        try:
            return self.invite_cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            return None

    def _create_invite(self, data) -> str:
        max_uses = self._bounded_int(data.get("max_uses", "1"), "使用次数", 1, 10000)
        valid_days = self._bounded_int(data.get("valid_days", "30"), "邀请码有效天数", 1, 3650)
        account_days = self._bounded_int(data.get("account_days", "0"), "账号有效天数", 0, 3650)
        route_quota = self._bounded_int(data.get("route_quota", "10"), "线路额度", 1, 1000)
        notes = str(data.get("notes", "")).strip()
        if len(notes) > 500:
            raise PanelError("备注不能超过 500 个字符")
        code = secrets.token_urlsafe(24)
        with self._connect() as db:
            db.execute(
                "INSERT INTO invites (code_hash,code_ciphertext,code_prefix,max_uses,used_count,expires_at,account_days,route_quota,notes,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (hashlib.sha256(code.encode("utf-8")).hexdigest(), self._encrypt_invite_code(code), code[:8], max_uses, 0, self._future(valid_days), account_days or None, route_quota, notes, now()),
            )
        return code

    def _delete_invite(self, invite_id: int) -> int:
        with self._connect() as db:
            invite = db.execute("SELECT id FROM invites WHERE id=?", (invite_id,)).fetchone()
            if not invite:
                raise PanelError("邀请码不存在")
            redemption_count = int(db.execute("SELECT COUNT(*) FROM invite_redemptions WHERE invite_id=?", (invite_id,)).fetchone()[0])
            db.execute("DELETE FROM invite_redemptions WHERE invite_id=?", (invite_id,))
            db.execute("DELETE FROM invites WHERE id=?", (invite_id,))
        return redemption_count

    def _update_user(self, user_id: int, data) -> bool:
        route_quota = self._bounded_int(data.get("route_quota", ""), "线路额度", 1, 1000)
        expires_at = self._expiry_from_date(str(data.get("expires_at", "")))
        notes = str(data.get("notes", "")).strip()
        if len(notes) > 500:
            raise PanelError("备注不能超过 500 个字符")
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise PanelError("用户不存在")
            if int(user["is_admin"] or 0):
                raise PanelError("管理员账号请在首页的账号安全中操作")
            used = int(db.execute("SELECT COUNT(*) FROM routes WHERE owner_user_id=?", (user_id,)).fetchone()[0])
            if route_quota < used:
                raise PanelError(f"线路额度不能低于当前已占用的 {used} 条")
            was_active = self._is_user_active(user)
            db.execute("UPDATE users SET route_quota=?,expires_at=?,notes=?,updated_at=? WHERE id=?", (route_quota, expires_at, notes, now(), user_id))
            updated = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return not was_active and self._is_user_active(updated)

    def _suspend_owned_routes(self, user_id: int) -> list[str]:
        with self._connect() as db:
            routes = db.execute("SELECT * FROM routes WHERE owner_user_id=? AND suspended_by_owner=0", (user_id,)).fetchall()
        errors: list[str] = []
        for route in routes:
            with self._connect() as db:
                node = db.execute("SELECT * FROM nodes WHERE id=?", (route["node_id"],)).fetchone()
            if not node:
                errors.append(f"{route['public_host']}：节点不存在")
                continue
            try:
                self._delete_route_file(node, route)
            except Exception as exc:
                message = f"账号暂停时线路下线失败：{exc}"[:700]
                with self._connect() as db:
                    db.execute("UPDATE routes SET last_error=?,updated_at=? WHERE id=?", (message, now(), route["id"]))
                errors.append(f"{route['public_host']}：{exc}")
                continue
            with self._connect() as db:
                db.execute("UPDATE routes SET deployed=0,suspended_by_owner=1,last_error='',updated_at=? WHERE id=?", (now(), route["id"]))
        return errors

    def _resume_owned_routes(self, user_id: int) -> list[str]:
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            routes = db.execute("SELECT * FROM routes WHERE owner_user_id=? AND suspended_by_owner=1", (user_id,)).fetchall()
        if not self._is_user_active(user):
            raise PanelError("账号仍处于停用或到期状态，不能恢复线路")
        errors: list[str] = []
        for route in routes:
            with self._connect() as db:
                node = db.execute("SELECT * FROM nodes WHERE id=?", (route["node_id"],)).fetchone()
            if not node:
                errors.append(f"{route['public_host']}：节点不存在")
                continue
            try:
                self._deploy_and_verify(node, route)
                with self._connect() as db:
                    db.execute("UPDATE routes SET suspended_by_owner=0,updated_at=? WHERE id=?", (now(), route["id"]))
            except Exception as exc:
                errors.append(f"{route['public_host']}：{exc}")
        return errors

    def _set_user_enabled(self, user_id: int, enabled: bool) -> list[str]:
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise PanelError("用户不存在")
            if int(user["is_admin"] or 0):
                raise PanelError("管理员账号不能在用户管理中停用")
            if enabled:
                if user["expires_at"] and user["expires_at"] <= now():
                    raise PanelError("该用户已到期，请先延长有效期")
                db.execute("UPDATE users SET status='active',updated_at=? WHERE id=?", (now(), user_id))
            else:
                db.execute("UPDATE users SET status='disabled',updated_at=? WHERE id=?", (now(), user_id))
                db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        return self._resume_owned_routes(user_id) if enabled else self._suspend_owned_routes(user_id)

    def _reset_user_password(self, user_id: int) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        temporary = "".join(secrets.choice(alphabet) for _ in range(16))
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise PanelError("用户不存在")
            if int(user["is_admin"] or 0):
                raise PanelError("管理员账号请在首页的账号安全中操作")
            db.execute(
                "UPDATE users SET password_hash=?,must_change_password=1,updated_at=? WHERE id=?",
                (self._password_hash(temporary), now(), user_id),
            )
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        return temporary

    def _delete_user_and_routes(self, user_id: int) -> None:
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise PanelError("用户不存在")
            if int(user["is_admin"] or 0):
                raise PanelError("管理员账号不能删除")
            db.execute("UPDATE users SET status='disabled',updated_at=? WHERE id=?", (now(), user_id))
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            routes = db.execute("SELECT * FROM routes WHERE owner_user_id=? ORDER BY id", (user_id,)).fetchall()
        failures = []
        for route in routes:
            with self._connect() as db:
                node = db.execute("SELECT * FROM nodes WHERE id=?", (route["node_id"],)).fetchone()
            try:
                if not node:
                    raise PanelError("节点不存在")
                self._delete_route_file(node, route)
                with self._connect() as db:
                    db.execute("UPDATE routes SET deployed=0,suspended_by_owner=1,last_error='',updated_at=? WHERE id=?", (now(), route["id"]))
            except Exception as exc:
                message = f"删除用户时线路下线失败：{exc}"[:700]
                with self._connect() as db:
                    db.execute("UPDATE routes SET last_error=?,updated_at=? WHERE id=?", (message, now(), route["id"]))
                failures.append(f"{route['public_host']}：{exc}")
        if failures:
            raise PanelError("用户已禁用，但以下线路清理失败，可重试删除：" + "；".join(failures[:3]))
        with self._connect() as db:
            db.execute("DELETE FROM routes WHERE owner_user_id=?", (user_id,))
            db.execute("DELETE FROM users WHERE id=?", (user_id,))

    def reconcile_inactive_users(self) -> None:
        with self._connect() as db:
            rows = db.execute("SELECT id FROM users WHERE is_admin=0 AND (status!='active' OR (expires_at IS NOT NULL AND expires_at <= ?))", (now(),)).fetchall()
            for row in rows:
                db.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))
        for row in rows:
            self._suspend_owned_routes(int(row["id"]))

    def users_dashboard(self, notice: str = "", error: str = "", csrf_token: str = "") -> web.Response:
        csrf_token = html.escape(csrf_token, quote=True)
        with self._connect() as db:
            users = db.execute(
                "SELECT users.*,COUNT(routes.id) AS route_count FROM users LEFT JOIN routes ON routes.owner_user_id=users.id "
                "GROUP BY users.id ORDER BY users.id DESC"
            ).fetchall()
            events = db.execute(
                "SELECT login_events.*,users.username FROM login_events JOIN users ON users.id=login_events.user_id ORDER BY login_events.id DESC LIMIT 50"
            ).fetchall()
        user_usage = self._traffic_summaries("user_traffic_daily", "user_id")
        user_rows = []
        for user in users:
            user_id = int(user["id"])
            status = self._user_status_label(user)
            expiry_value = html.escape((user["expires_at"] or "")[:10], quote=True)
            update_token = csrf_token
            action_token = csrf_token
            usage = self._format_traffic_usage(user_usage.get(user_id))
            if int(user["is_admin"] or 0):
                status = "管理员"
                buttons = "<span class='muted'>管理员账号请在首页的“账号安全”中改密</span>"
                edit = "<span class='muted'>管理员账号不可在此停用、删除或修改额度</span>"
            else:
                buttons = (f"<div class='user-actions'><form method='post' action='{ADMIN_PREFIX}/users/{user_id}/{'disable' if status == '正常' else 'enable'}'><input type='hidden' name='csrf' value='{action_token}'><button class='{'danger' if status == '正常' else ''}'>{'停用' if status == '正常' else '启用'}</button></form>"
                           f"<form method='post' action='{ADMIN_PREFIX}/users/{user_id}/reset-password'><input type='hidden' name='csrf' value='{action_token}'><button class='secondary'>重置密码</button></form>"
                           "<button type='button' class='secondary toggle-user-edit' aria-expanded='false'>编辑</button></div>")
                edit = f"""<form class='row-editor user-edit-panel' hidden method='post' action='{ADMIN_PREFIX}/users/{user_id}/update'><input type='hidden' name='csrf' value='{update_token}'><label>线路额度<input required name='route_quota' type='number' min='1' max='1000' value='{int(user['route_quota'])}'></label><label>有效期<input name='expires_at' type='date' value='{expiry_value}'></label><label>备注<input name='notes' maxlength='500' value='{html.escape(user['notes'], quote=True)}' placeholder='可选'></label><div class='editor-actions'><button type='submit'>保存</button><button type='button' class='secondary cancel-inline-edit'>取消</button></div></form><form class='inline-delete' method='post' action='{ADMIN_PREFIX}/users/{user_id}/delete' data-confirm='确认删除这个账号及其全部线路？'><input type='hidden' name='csrf' value='{action_token}'><button type='submit' class='danger'>删除账号</button></form>"""
            user_rows.append(f"<tr><td>{html.escape(user['username'])}</td><td><span class='tag'>{status}</span></td><td>{int(user['route_count'])}/{int(user['route_quota'])}</td><td>{usage}</td><td>{html.escape(self._display_expiry(user['expires_at']))}</td><td>{html.escape(user['last_login_at'] or '从未')}<br><span class='muted'>{html.escape(user['last_login_ip'] or '')}</span></td><td>{html.escape(user['notes'])}</td><td>{buttons}{edit}</td></tr>")
        event_rows = "".join(f"<tr><td>{html.escape(event['created_at'])}</td><td>{html.escape(event['username'])}</td><td>{'成功' if event['success'] else '失败'}</td><td>{html.escape(event['ip'])}</td></tr>" for event in events) or "<tr><td colspan='4' class='muted'>暂无记录</td></tr>"
        content = f"""
<section><h2>用户</h2><table><thead><tr><th>用户名</th><th>状态</th><th>额度</th><th>代理用量</th><th>有效期</th><th>最近登录</th><th>备注</th><th>操作</th></tr></thead><tbody>{''.join(user_rows) or "<tr><td colspan='8' class='muted'>暂无用户</td></tr>"}</tbody></table></section>
<section><h2>最近登录记录</h2><table><thead><tr><th>时间</th><th>用户</th><th>结果</th><th>IP</th></tr></thead><tbody>{event_rows}</tbody></table></section>"""
        return self._page(content, notice, error, active="users")

    def invites_dashboard(self, notice: str = "", error: str = "", csrf_token: str = "") -> web.Response:
        with self._connect() as db:
            invites = db.execute("SELECT * FROM invites ORDER BY id DESC LIMIT 100").fetchall()
            redemptions = db.execute("SELECT * FROM invite_redemptions ORDER BY invite_id DESC,id ASC").fetchall()
        redemptions_by_invite: dict[int, list] = {}
        for redemption in redemptions:
            redemptions_by_invite.setdefault(int(redemption["invite_id"]), []).append(redemption)
        invite_rows = []
        for invite in invites:
            invite_id = int(invite["id"])
            state = "已撤销" if invite["revoked_at"] else ("已到期" if invite["expires_at"] <= now() else ("已用完" if int(invite["used_count"]) >= int(invite["max_uses"]) else "可用"))
            revoke = "" if state != "可用" else f"<form class='inline' method='post' action='{ADMIN_PREFIX}/invites/{invite_id}/revoke'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='secondary'>撤销</button></form>"
            delete = f"<form class='inline' method='post' action='{ADMIN_PREFIX}/invites/{invite_id}/delete' data-confirm='确认删除这个邀请码及其兑换记录？'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='danger'>删除</button></form>"
            account_duration = "永久" if invite["account_days"] is None else f"{int(invite['account_days'])} 天"
            code = self._decrypt_invite_code(invite)
            code_html = (f"<div class='copy-control'><input class='invite-code' readonly aria-label='邀请码' value='{html.escape(code, quote=True)}'><button type='button' class='copy-value' data-copy='{html.escape(code, quote=True)}'>复制</button></div>" if code else "<span class='muted'>旧邀请码未保存全文</span>")
            redeemers = redemptions_by_invite.get(invite_id, [])
            redeemer_html = "<br>".join(
                f"<code>#{int(item['user_id'])}</code> {html.escape(item['username'])}<br><span class='muted'>{html.escape(item['redeemed_at'])}</span>"
                for item in redeemers
            ) or "<span class='muted'>暂无</span>"
            invite_rows.append(f"<tr><td>{code_html}</td><td>{int(invite['used_count'])}/{int(invite['max_uses'])}</td><td>{redeemer_html}</td><td>{html.escape(self._display_expiry(invite['expires_at']))}</td><td>{account_duration} / {int(invite['route_quota'])} 条</td><td>{html.escape(invite['notes'])}</td><td><div class='invite-actions'><span class='tag'>{state}</span>{revoke}{delete}</div></td></tr>")
        content = f"""
<section><h2>创建邀请码</h2><p class='muted'>邀请码会加密保存，可长期在下方列表查看与复制。</p><form class='grid' method='post' action='{ADMIN_PREFIX}/invites'><label>可用次数<input required name='max_uses' type='number' min='1' max='10000' value='1'></label><label>邀请码有效天数<input required name='valid_days' type='number' min='1' max='3650' value='30'></label><label>新账号有效天数（0=永久）<input required name='account_days' type='number' min='0' max='3650' value='0'></label><label>新账号线路额度<input required name='route_quota' type='number' min='1' max='1000' value='10'></label><label>备注<input name='notes' maxlength='500'></label><p><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button>创建邀请码</button></p></form></section>
<section><h2>邀请码</h2><p class='muted'>删除不会影响已注册账号或其线路，但会清除该邀请码的兑换历史。</p><table><thead><tr><th>邀请码</th><th>使用</th><th>使用者 ID / 用户名</th><th>邀请码到期</th><th>新账号参数</th><th>备注</th><th>操作</th></tr></thead><tbody>{''.join(invite_rows) or "<tr><td colspan='7' class='muted'>暂无邀请码</td></tr>"}</tbody></table></section>"""
        return self._page(content, notice, error, active="invites")

    def _valid_path(self, value: str, field: str) -> str:
        value = value.strip()
        if not SAFE_PATH.fullmatch(value):
            raise PanelError(f"{field} 必须是安全的绝对路径")
        return value

    def _parse_node(self, data) -> tuple:
        name = str(data.get("name", "")).strip()
        kind = str(data.get("kind", "")).strip()
        suffix = str(data.get("domain_suffix", "")).lower().strip(". ")
        if not SAFE_NAME.fullmatch(name) or kind not in {"local", "ssh"} or not SAFE_HOST.fullmatch(suffix):
            raise PanelError("节点名称、类型或域名后缀不合法")
        try:
            ssh_port = int(str(data.get("ssh_port", "22")))
            public_port = int(str(data.get("public_https_port", "443")))
            internal_port = int(str(data.get("internal_https_port", "443")))
        except ValueError as exc:
            raise PanelError("端口必须是数字") from exc
        if not (1 <= ssh_port <= 65535 and 1 <= public_port <= 65535 and 1 <= internal_port <= 65535):
            raise PanelError("端口超出范围")
        host = str(data.get("ssh_host", "")).strip().lower()
        user = str(data.get("ssh_user", "")).strip()
        identity = str(data.get("ssh_identity", "")).strip()
        ssh_password = str(data.get("ssh_password", ""))
        if kind == "ssh":
            if not SAFE_HOST.fullmatch(host) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
                raise PanelError("SSH 主机或用户不合法")
            if identity:
                identity = self._valid_path(identity, "SSH 私钥路径")
        else:
            host = user = identity = ssh_password = ""
        if kind == "ssh" and not identity and not ssh_password:
            raise PanelError("SSH 私钥路径和 SSH 密码至少填写一个")
        return (
            name, kind, host, ssh_port, user, identity, ssh_password, suffix,
            self._valid_path(str(data.get("tls_cert_file", "")), "TLS 证书文件"),
            self._valid_path(str(data.get("tls_key_file", "")), "TLS 私钥文件"),
            self._valid_path(str(data.get("caddy_config", "")), "Nginx 配置"),
            self._valid_path(str(data.get("generated_dir", "")), "线路生成目录"), public_port, internal_port,
        )

    async def _lookup_node_location(self, host: str = "") -> tuple[str, str, str]:
        """Resolve a public SSH host, then obtain country metadata without blocking node creation."""
        try:
            public_ip = ""
            if host:
                addresses = await asyncio.to_thread(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM)
                public_ip = next(
                    str(ipaddress.ip_address(item[4][0])) for item in addresses
                    if ipaddress.ip_address(item[4][0]).is_global
                )
            timeout = ClientTimeout(total=4)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(f"https://ipwho.is/{public_ip}", headers={"Accept": "application/json"}) as response:
                    if response.status != 200:
                        return "", "", ""
                    payload = await response.json(content_type=None)
            if not isinstance(payload, dict) or not payload.get("success"):
                return "", "", ""
            code = str(payload.get("country_code", "")).upper()
            country = str(payload.get("country", "")).strip()
            flag_data = payload.get("flag")
            flag = str(flag_data.get("emoji", "")).strip() if isinstance(flag_data, dict) else ""
            if not re.fullmatch(r"[A-Z]{2}", code) or not flag:
                return "", "", ""
            return COUNTRY_NAMES_ZH.get(code, country), code, flag
        except (OSError, ValueError, asyncio.TimeoutError):
            return "", "", ""

    async def refresh_local_location(self) -> bool:
        """Populate the pre-existing local node with the server's public egress location once."""
        if not self.enabled:
            return False
        with self._connect() as db:
            node = db.execute(
                "SELECT id FROM nodes WHERE kind = 'local' AND country_code = '' LIMIT 1"
            ).fetchone()
        if not node:
            return False
        country_name, country_code, country_flag = await self._lookup_node_location()
        if not country_code:
            return False
        with self._connect() as db:
            db.execute(
                "UPDATE nodes SET country_name=?,country_code=?,country_flag=? WHERE id=? AND country_code=''",
                (country_name, country_code, country_flag, node["id"]),
            )
        return True

    def _acme_account_value(self, key: str, *, required: bool = True) -> str:
        try:
            metadata = self.acme_account.lstat()
        except OSError as exc:
            raise PanelError("自动证书配置缺失，请联系管理员") from exc
        if not stat.S_ISREG(metadata.st_mode) or self.acme_account.is_symlink():
            raise PanelError("自动证书配置缺失，请联系管理员")
        if os.name == "posix" and (metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o077):
            raise PanelError("自动证书配置权限不安全，必须由 root 拥有且权限为 600")
        for line in self.acme_account.read_text(encoding="utf-8").splitlines():
            if not line.startswith(key + "="):
                continue
            try:
                values = shlex.split(line.split("=", 1)[1])
            except ValueError as exc:
                raise PanelError("自动证书配置格式错误") from exc
            if values:
                return values[0]
        if required:
            raise PanelError(f"自动证书配置缺少 {key}")
        return ""

    def _cloudflare_api(self, method: str, path: str, payload: dict | None = None) -> dict:
        token = self._acme_account_value("SAVED_CF_Token")
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        request = Request(
            "https://api.cloudflare.com/client/v4" + path,
            data=body,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=25) as response:
                result = json.loads(response.read().decode())
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                detail = {}
            codes = ",".join(str(item.get("code", "")) for item in detail.get("errors", []))
            suffix = f"（HTTP {exc.code}{'; code ' + codes if codes else ''}）"
            raise PanelError("DNS 自动配置失败" + suffix) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PanelError("DNS 自动配置请求失败") from exc
        if not result.get("success"):
            codes = ",".join(str(item.get("code", "")) for item in result.get("errors", []))
            raise PanelError(f"DNS 自动配置失败{('（' + codes + '）') if codes else ''}")
        return result

    def _cloudflare_zone_id(self) -> str:
        query = urlencode({"name": self.auto_zone, "status": "active"})
        result = self._cloudflare_api("GET", "/zones?" + query).get("result", [])
        if len(result) != 1:
            raise PanelError(f"没有找到可管理的 DNS 区域 {self.auto_zone}")
        return str(result[0]["id"])

    def _create_node_dns(self, domain_suffix: str, address: str) -> list[str]:
        zone_id = self._cloudflare_zone_id()
        created = []
        try:
            for name in (domain_suffix, "*." + domain_suffix):
                query = urlencode({"type": "A", "name": name})
                existing = self._cloudflare_api(
                    "GET", f"/zones/{zone_id}/dns_records?{query}"
                ).get("result", [])
                if existing:
                    record = existing[0]
                    if record.get("content") == address and not record.get("proxied"):
                        # An operator may have pre-created the exact record.
                        # It is usable, but it is not owned by this deployment
                        # and must not be removed on node deletion.
                        continue
                    raise PanelError(f"域名 {name} 已存在其他解析，请更换节点名称")
                record = self._cloudflare_api("POST", f"/zones/{zone_id}/dns_records", {
                    "type": "A", "name": name, "content": address, "ttl": 120, "proxied": False,
                }).get("result", {})
                if record.get("id"):
                    created.append(str(record["id"]))
        except Exception as exc:
            try:
                self._delete_node_dns(created)
            except Exception as cleanup_exc:
                raise PanelError("DNS 创建失败，且回滚也失败；请在 Cloudflare 中检查孤儿记录") from cleanup_exc
            raise
        return created

    def _delete_node_dns(self, record_ids: list[str]) -> None:
        if not record_ids:
            return
        zone_id = self._cloudflare_zone_id()
        failures = []
        for record_id in record_ids:
            try:
                self._cloudflare_api("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
            except Exception as exc:
                # Cloudflare 81044 means the record is already absent. Treat
                # deletion as idempotent so interrupted cleanup can complete.
                if "81044" in str(exc) or "HTTP 404" in str(exc):
                    continue
                failures.append(f"{record_id}: {exc}")
        if failures:
            raise PanelError("DNS 记录删除失败：" + "; ".join(failures[:3]))

    def _issue_central_certificate(self, node) -> tuple[str, str]:
        """Issue a node certificate on the control plane and return local paths."""
        domain = str(node["domain_suffix"] or "").lower().strip(".")
        if not SAFE_HOST.fullmatch(domain):
            raise PanelError("节点域名不合法，无法申请证书")
        acme_home = Path(os.environ.get("ACME_HOME", "/root/.acme.sh")).resolve()
        acme_bin = Path(os.environ.get("ACME_SH_BIN", str(acme_home / "acme.sh"))).resolve()
        if acme_bin.is_symlink() or not acme_bin.is_file() or not os.access(acme_bin, os.X_OK):
            raise PanelError("主控机缺少可执行的 acme.sh，无法申请节点证书")
        token = self._acme_account_value("SAVED_CF_Token")
        cert_root = Path(os.environ.get("CENTRAL_CERT_DIR", "/var/lib/uniproxy/certs")).resolve()
        cert_dir = cert_root / hashlib.sha256(domain.encode("utf-8")).hexdigest()[:32]
        cert_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(cert_root, 0o700)
        os.chmod(cert_dir, 0o700)
        source_dir = acme_home / (domain + "_ecc")
        fullchain_source = source_dir / "fullchain.cer"
        key_source = source_dir / (domain + ".key")
        with self._cert_issue_lock:
            env = os.environ.copy()
            env["CF_Token"] = token
            args = [
                str(acme_bin), "--issue", "--dns", "dns_cf",
                "-d", domain, "-d", "*." + domain,
                "--keylength", "ec-256", "--server", "letsencrypt",
                "--home", str(acme_home), "--dnssleep", "30",
            ]
            account_conf = acme_home / "account.conf"
            if account_conf.is_file() and not account_conf.is_symlink():
                args.extend(["--accountconf", str(account_conf)])
            try:
                result = subprocess.run(
                    args, env=env, text=True, capture_output=True,
                    timeout=max(120, min(900, int(os.environ.get("ACME_ISSUE_TIMEOUT", "600")))),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PanelError("中央证书申请超时或无法启动 acme.sh") from exc
            finally:
                env.pop("CF_Token", None)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            has_existing_cert = fullchain_source.is_file() and key_source.is_file()
            skipped_unchanged = "domains not changed" in output.lower() and "skipping" in output.lower()
            if result.returncode != 0 and not (skipped_unchanged and has_existing_cert):
                detail = output.strip().replace("\x00", "")
                detail = detail.replace(token, "[redacted]")
                raise PanelError("中央证书申请失败：" + detail[-600:])
            if not has_existing_cert:
                raise PanelError("acme.sh 已返回成功，但证书文件不完整")
            try:
                fullchain = fullchain_source.read_bytes()
                private_key = key_source.read_bytes()
                if not fullchain or not private_key:
                    raise ValueError("empty certificate")
                cert_tmp = cert_dir / "fullchain.pem.new"
                key_tmp = cert_dir / "key.pem.new"
                cert_tmp.write_bytes(fullchain)
                key_tmp.write_bytes(private_key)
                os.chmod(cert_tmp, 0o644)
                os.chmod(key_tmp, 0o600)
                os.replace(cert_tmp, cert_dir / "fullchain.pem")
                os.replace(key_tmp, cert_dir / "key.pem")
            except (OSError, ValueError) as exc:
                raise PanelError("中央证书文件安装失败") from exc
        return str(cert_dir / "fullchain.pem"), str(cert_dir / "key.pem")

    @staticmethod
    def _node_dns_record_ids(node) -> list[str]:
        try:
            values = json.loads(str(node["dns_record_ids_json"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        return [str(item) for item in values if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", str(item))]

    def _cleanup_managed_node(self, node) -> None:
        if not node["auto_managed"]:
            return
        record_ids = self._node_dns_record_ids(node)
        self._delete_node_dns(record_ids)
        if node["kind"] != "local":
            # Remove only files and jobs created by this project.  The marker
            # prevents an old/shared acme installation from being destroyed.
            marker = "/etc/uniproxy-nginx/.uniproxy-acme-managed"
            cleanup = "\n".join([
                "set -eu",
                f"if [ -f {shlex.quote(marker)} ]; then",
                "  if command -v crontab >/dev/null 2>&1; then crontab -l 2>/dev/null | grep -v 'uniproxy-nginx' | grep -v 'acme.sh.*--cron' | crontab - || true; fi",
                "  if command -v systemctl >/dev/null 2>&1; then systemctl disable --now uniproxy-nginx.service >/dev/null 2>&1 || true; systemctl daemon-reload || true; fi",
                "  rm -f /etc/systemd/system/uniproxy-nginx.service /usr/local/sbin/uniproxy-nginx",
                f"  rm -rf {shlex.quote(str(node['generated_dir']))} {shlex.quote(str(node['caddy_config']))} /etc/uniproxy-nginx",
                f"  rm -rf {shlex.quote('/root/.acme.sh/' + str(node['domain_suffix']) + '_ecc')}",
                "  rm -f /root/.acme.sh/account.conf",
                "fi",
            ])
            self._run(self._ssh_args(node) + [cleanup], env=self._ssh_env(node), timeout=90)
        identity = str(node["ssh_identity"] or "")
        if identity:
            try:
                path = Path(identity).resolve()
                key_dir = (self.db_path.parent / "keys").resolve()
                if path.parent == key_dir:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _remote_cleanup_unreachable(error: BaseException) -> bool:
        """Allow detaching a node when its SSH endpoint is clearly offline."""
        text = str(error).lower()
        return any(
            marker in text
            for marker in (
                "connection refused",
                "connection timed out",
                "no route to host",
                "network is unreachable",
            )
        )

    def _remove_node_identity(self, node) -> None:
        identity = str(node["ssh_identity"] or "")
        if not identity:
            return
        try:
            path = Path(identity).resolve()
            key_dir = (self.db_path.parent / "keys").resolve()
            if path.parent == key_dir:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def _auto_domain_suffix(self, name: str, address: str, ssh_port: int) -> str:
        label = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:18] or "node"
        digest = hashlib.sha256(f"{name}|{address}|{ssh_port}".encode()).hexdigest()[:6]
        return f"n-{label}-{digest}.{self.auto_zone}"

    def _store_private_key(self, upload) -> str:
        if not upload or not getattr(upload, "filename", "") or not getattr(upload, "file", None):
            return ""
        raw = upload.file.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise PanelError("SSH 私钥文件不能超过 128 KiB")
        if not raw.startswith(b"-----BEGIN ") or b"PRIVATE KEY-----" not in raw:
            raise PanelError("上传的文件不是有效的 PEM 私钥")
        directory = self.db_path.parent / "keys"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / f"node-{secrets.token_hex(12)}.key"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
        return str(path)

    def _detect_public_https_port(self, node) -> int:
        port = int(node["public_https_port"])
        authority = node["domain_suffix"] if port == 443 else f"{node['domain_suffix']}:{port}"
        url = f"https://{authority}/__health"
        for delay in (0, 3, 5, 8, 12, 15):
            if delay:
                time.sleep(delay)
            result = subprocess.run([
                "/usr/bin/curl", "--fail", "--silent", "--show-error",
                "--connect-timeout", "5", "--max-time", "10",
                "--resolve", f"{node['domain_suffix']}:{port}:{node['ssh_host']}", url,
            ], text=True, capture_output=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip() == "ok":
                return port
        if node["network_mode"] == "nat":
            raise PanelError(
                f"节点内部配置已完成，但连续探测后公网 TCP {port} 仍无法访问；"
                f"请确认服务商已将公网 TCP {port} 映射到机器内部 TCP {int(node['internal_https_port'])}"
            )
        raise PanelError(
            f"节点内部配置已完成，但连续探测后公网 TCP {port} 仍无法访问；"
            f"请检查云平台安全组，并确认服务监听内部 TCP {int(node['internal_https_port'])}"
        )

    @staticmethod
    def _select_existing_nginx_port(output: str) -> int | None:
        """Choose an existing Nginx listener for the isolated HTTPS service.

        The remote probe is deliberately limited to ``listen`` directives;
        it never trusts an arbitrary process port. Prefer an explicit SSL
        listener, then prefer 443. Port 80 is valid when the NAT mapping
        points the public HTTPS port to the node's port 80.
        """
        ssl_ports: set[int] = set()
        other_ports: set[int] = set()
        for raw_line in str(output or "").splitlines():
            match = re.match(r"^\s*listen\s+([^;]+);", raw_line, re.IGNORECASE)
            if not match:
                continue
            tokens = match.group(1).split()
            if not tokens:
                continue
            endpoint = tokens[0].strip()
            port_text = endpoint
            if endpoint.startswith("[") and "]" in endpoint:
                port_text = endpoint.rsplit(":", 1)[-1]
            elif ":" in endpoint and endpoint.count(":") == 1:
                port_text = endpoint.rsplit(":", 1)[-1]
            if not port_text.isdigit():
                continue
            port = int(port_text)
            if not 1 <= port <= 65535:
                continue
            if any(token.lower() == "ssl" for token in tokens[1:]):
                ssl_ports.add(port)
            else:
                other_ports.add(port)
        if ssl_ports:
            return min(ssl_ports, key=lambda port: (port != 443, port))
        if other_ports:
            non_http_ports = {port for port in other_ports if port != 80}
            candidates = non_http_ports or other_ports
            return min(candidates, key=lambda port: (port != 443, port))
        return None

    def _detect_existing_nginx_port(self, node) -> int | None:
        """Read an installed Nginx config before the project takes it over."""
        probe = (
            "if command -v nginx >/dev/null 2>&1; then "
            "nginx -T 2>/dev/null | grep -E '^\\s*listen\\s+[^;]+;' | head -n 200 || true; "
            "fi"
        )
        try:
            output = self._run(self._ssh_args(node) + [probe], env=self._ssh_env(node), timeout=30)
        except (PanelError, subprocess.TimeoutExpired):
            return None
        return self._select_existing_nginx_port(output)

    def _provision_auto_node(self, node) -> tuple[int, list[str]]:
        self._wait_for_root_ssh(node)
        dns_records = self._create_node_dns(node["domain_suffix"], node["ssh_host"])
        try:
            cert_path, key_path = self._issue_central_certificate(node)
        except Exception:
            try:
                self._delete_node_dns(dns_records)
            except Exception:
                pass
            raise
        remote_stage = f"/tmp/uniproxy-stage-{secrets.token_hex(16)}"
        remote_cert = remote_stage + "/fullchain.pem"
        remote_key = remote_stage + "/key.pem"
        try:
            self._run(
                self._ssh_args(node) + [f"umask 077; install -d -m 700 {shlex.quote(remote_stage)}"],
                env=self._ssh_env(node), timeout=30,
            )
            self._run(
                self._scp_args(node, cert_path, remote_cert),
                env=self._ssh_env(node), timeout=60,
            )
            self._run(
                self._scp_args(node, key_path, remote_key),
                env=self._ssh_env(node), timeout=60,
            )
            root_dir = "/etc/uniproxy-nginx"
            controller_path = "/usr/local/sbin/uniproxy-nginx"
            pid_path = "/run/uniproxy-nginx.pid"
            controller = "\n".join([
                "#!/bin/sh", "set -eu",
                f"NGINX={shlex.quote('/usr/sbin/nginx')}",
                f"CONF={shlex.quote(node['caddy_config'])}",
                f"PID={shlex.quote(pid_path)}",
                "alive() { [ -s \"$PID\" ] && kill -0 \"$(cat \"$PID\")\" 2>/dev/null; }",
                "case \"${1:-}\" in",
                "  test) exec \"$NGINX\" -t -c \"$CONF\" ;;",
                "  start) \"$NGINX\" -t -c \"$CONF\"; alive || \"$NGINX\" -c \"$CONF\" ;;",
                "  reload) \"$NGINX\" -t -c \"$CONF\"; if alive; then \"$NGINX\" -c \"$CONF\" -s reload; else \"$NGINX\" -c \"$CONF\"; fi ;;",
                "  stop) if alive; then \"$NGINX\" -c \"$CONF\" -s quit; fi ;;",
                "  status) alive ;;",
                "  *) echo 'usage: uniproxy-nginx {start|reload|stop|status|test}' >&2; exit 2 ;;",
                "esac", "",
            ])
            nginx_config = "\n".join([
                "# isolated Nginx configuration managed by uniproxy",
                "user uniproxy-nginx;",
                "worker_processes auto;",
                "worker_rlimit_nofile 65535;",
                f"pid {pid_path};",
                "error_log /var/log/uniproxy-nginx-error.log crit;",
                "events { worker_connections 8192; multi_accept on; }",
                "http {",
                "    server_tokens off;",
                "    ssl_protocols TLSv1.2 TLSv1.3;",
                "    default_type application/octet-stream;",
                "    log_format uniproxy '$remote_addr - [$time_local] \"$request_method $uri $server_protocol\" $status $body_bytes_sent $request_time';",
                "    access_log off;",
                "    sendfile on;",
                "    tcp_nopush on;",
                "    tcp_nodelay on;",
                "    reset_timedout_connection on;",
                "    keepalive_timeout 75;",
                "    keepalive_requests 10000;",
                "    send_timeout 3600s;",
                "    ssl_session_cache shared:UNIPROXY_SSL:10m;",
                "    ssl_session_timeout 1h;",
                "    server_names_hash_bucket_size 128;",
                f"    include {node['generated_dir']}/*.conf;",
                "}", "",
            ])
            base_config = "\n".join([
                "# generated by uniproxy automatic node provisioning",
                "server {",
                f"    listen {int(node['internal_https_port'])} ssl;",
                f"    server_name {node['domain_suffix']};",
                f"    ssl_certificate {node['tls_cert_file']};",
                f"    ssl_certificate_key {node['tls_key_file']};",
                "    ssl_protocols TLSv1.2 TLSv1.3;",
                "    location = /__health { access_log off; default_type text/plain; return 200 'ok\\n'; }",
                "    location / { return 404; }",
                "}", "",
            ])
            systemd_unit = "\n".join([
                "[Unit]", "Description=Uniproxy isolated Nginx", "After=network-online.target",
                "Wants=network-online.target", "Conflicts=nginx.service", "",
                "[Service]", "Type=forking", f"PIDFile={pid_path}",
                f"ExecStart={controller_path} start", f"ExecReload={controller_path} reload",
                f"ExecStop={controller_path} stop", "Restart=on-failure", "", "[Install]",
                "WantedBy=multi-user.target", "",
            ])
            encoded_controller = base64.b64encode(controller.encode()).decode()
            encoded_nginx = base64.b64encode(nginx_config.encode()).decode()
            encoded_config = base64.b64encode(base_config.encode()).decode()
            encoded_unit = base64.b64encode(systemd_unit.encode()).decode()
            egress_path = Path(__file__).resolve().parent / "deploy" / "uniproxy-egress.nft"
            logrotate_path = Path(__file__).resolve().parent / "deploy" / "uniproxy.logrotate"
            if not egress_path.is_file() or not logrotate_path.is_file():
                raise PanelError("节点安全部署模板缺失")
            encoded_egress = base64.b64encode(egress_path.read_bytes()).decode()
            encoded_logrotate = base64.b64encode(logrotate_path.read_bytes()).decode()
            if self.allow_unprotected_egress:
                egress_command = (
                    f"printf %s {shlex.quote(encoded_egress)} | base64 -d > {shlex.quote(root_dir + '/egress.nft')}; "
                    f"printf '%s\\n' disabled-by-admin > {shlex.quote(root_dir + '/.uniproxy-egress-unprotected')}; "
                    f"chmod 600 {shlex.quote(root_dir + '/.uniproxy-egress-unprotected')}"
                )
            else:
                egress_command = (
                    f"printf %s {shlex.quote(encoded_egress)} | base64 -d > {shlex.quote(root_dir + '/egress.nft')}; "
                    f"if ! nft list table inet uniproxy_egress >/dev/null 2>&1; then "
                    f"nft -c -f {shlex.quote(root_dir + '/egress.nft')}; "
                    f"nft -f {shlex.quote(root_dir + '/egress.nft')}; fi"
                )
            ensure_nginx_user = "\n".join([
                "ensure_nginx_group() {",
                "  if getent group uniproxy-nginx >/dev/null 2>&1; then return 0; fi",
                "  if command -v groupadd >/dev/null 2>&1; then",
                "    groupadd --system uniproxy-nginx >/dev/null 2>&1 || groupadd -r uniproxy-nginx >/dev/null 2>&1 || true",
                "  fi",
                "  if ! getent group uniproxy-nginx >/dev/null 2>&1 && command -v addgroup >/dev/null 2>&1; then",
                "    addgroup -S uniproxy-nginx >/dev/null 2>&1 || addgroup --system uniproxy-nginx >/dev/null 2>&1 || true",
                "  fi",
                "  getent group uniproxy-nginx >/dev/null 2>&1 || { echo '无法创建 uniproxy-nginx 组' >&2; return 1; }",
                "}",
                "ensure_nginx_group",
                "if id -u uniproxy-nginx >/dev/null 2>&1; then",
                "  current_nginx_group=$(id -gn uniproxy-nginx 2>/dev/null || true)",
                "  if [ \"$current_nginx_group\" != \"uniproxy-nginx\" ]; then",
                "    command -v usermod >/dev/null 2>&1 || { echo '已有 uniproxy-nginx 用户但系统缺少 usermod，无法修复主组' >&2; exit 1; }",
                "    usermod -g uniproxy-nginx uniproxy-nginx >/dev/null 2>&1",
                "  fi",
                "else",
                "  if command -v useradd >/dev/null 2>&1; then",
                "    if ! useradd --system --no-create-home --shell /sbin/nologin --gid uniproxy-nginx uniproxy-nginx >/dev/null 2>&1; then",
                "      if ! useradd -r -M -s /sbin/nologin -g uniproxy-nginx uniproxy-nginx >/dev/null 2>&1; then",
                "        command -v adduser >/dev/null 2>&1 || { echo 'useradd 参数不兼容且缺少 adduser' >&2; exit 1; }",
                "        adduser -S -D -H -s /sbin/nologin -G uniproxy-nginx uniproxy-nginx >/dev/null 2>&1 || adduser --system --no-create-home --disabled-login --ingroup uniproxy-nginx uniproxy-nginx >/dev/null 2>&1",
                "      fi",
                "    fi",
                "  elif command -v adduser >/dev/null 2>&1; then",
                "    adduser -S -D -H -s /sbin/nologin -G uniproxy-nginx uniproxy-nginx >/dev/null 2>&1 || adduser --system --no-create-home --disabled-login --ingroup uniproxy-nginx uniproxy-nginx >/dev/null 2>&1",
                "  else echo '系统缺少 useradd/adduser，无法创建 Nginx 运行用户' >&2; exit 1; fi",
                "fi",
                "id -u uniproxy-nginx >/dev/null 2>&1",
                "getent group uniproxy-nginx >/dev/null 2>&1",
                "test \"$(id -gn uniproxy-nginx 2>/dev/null)\" = uniproxy-nginx",
            ])
            script = "\n".join([
                "set -eu", "export DEBIAN_FRONTEND=noninteractive",
                f"cleanup() {{ rm -rf {shlex.quote(remote_stage)}; }}", "trap cleanup EXIT",
                "apt_with_lock_retry() { attempts=0; while ! apt-get -o DPkg::Lock::Timeout=5 \"$@\"; do attempts=$((attempts + 1)); if [ \"$attempts\" -ge 12 ]; then echo 'APT package manager remained busy for about 2 minutes; retry node deployment shortly.' >&2; return 1; fi; echo 'Waiting for the system package manager to finish...' >&2; sleep 5; done; }",
                "if command -v apk >/dev/null 2>&1; then apk add --no-cache nginx ca-certificates curl dcron coreutils openssl nftables logrotate shadow;",
                "elif command -v apt-get >/dev/null 2>&1; then apt_with_lock_retry update -qq; apt_with_lock_retry install -y -qq nginx ca-certificates curl cron coreutils openssl nftables logrotate;",
                "elif command -v dnf >/dev/null 2>&1; then dnf install -y nginx ca-certificates curl cronie coreutils openssl nftables logrotate shadow-utils;",
                "elif command -v yum >/dev/null 2>&1; then yum install -y nginx ca-certificates curl cronie coreutils openssl nftables logrotate shadow-utils;",
                "else echo '不支持的系统，无法自动安装 Nginx' >&2; exit 1; fi",
                "if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then systemctl disable --now nginx >/dev/null 2>&1 || true;",
                "elif command -v rc-service >/dev/null 2>&1; then rc-service nginx stop >/dev/null 2>&1 || true; rc-update del nginx default >/dev/null 2>&1 || true;",
                "elif command -v service >/dev/null 2>&1; then service nginx stop >/dev/null 2>&1 || true; fi",
                "if [ -s /run/nginx.pid ]; then old_pid=$(cat /run/nginx.pid 2>/dev/null || true); if [ -n \"$old_pid\" ] && kill -0 \"$old_pid\" 2>/dev/null; then kill -QUIT \"$old_pid\" 2>/dev/null || true; sleep 1; fi; fi",
                f"mkdir -p {shlex.quote(root_dir)} {shlex.quote(node['generated_dir'])} {shlex.quote(root_dir + '/certs')} /usr/local/sbin",
                ensure_nginx_user,
                self._ca_bundle_prepare_script("/etc/uniproxy-nginx/ca-bundle.pem"),
                f"printf %s {shlex.quote(encoded_controller)} | base64 -d > {shlex.quote(controller_path)}",
                f"chmod 755 {shlex.quote(controller_path)}",
                f"printf %s {shlex.quote(encoded_nginx)} | base64 -d > {shlex.quote(node['caddy_config'])}",
                f"printf %s {shlex.quote(encoded_config)} | base64 -d > {shlex.quote(node['generated_dir'] + '/00-uniproxy-base.conf')}",
                "rm -f /etc/nginx/conf.d/00-uniproxy-base.conf",
                f"install -m 0600 {shlex.quote(remote_key)} {shlex.quote(node['tls_key_file'])}",
                f"install -m 0644 {shlex.quote(remote_cert)} {shlex.quote(node['tls_cert_file'])}",
                f"printf '%s\\n' managed > {shlex.quote(root_dir + '/.uniproxy-acme-managed')}; chmod 600 {shlex.quote(root_dir + '/.uniproxy-acme-managed')}",
                f"printf '%s\\n' central-cert-mode > {shlex.quote(root_dir + '/.uniproxy-cert-mode')}; chmod 600 {shlex.quote(root_dir + '/.uniproxy-cert-mode')}",
                egress_command,
                f"printf %s {shlex.quote(encoded_logrotate)} | base64 -d > /etc/logrotate.d/uniproxy",
                f"{shlex.quote(controller_path)} reload",
                "if command -v crontab >/dev/null 2>&1; then (crontab -l 2>/dev/null | grep -v 'uniproxy-nginx' || true; echo '@reboot /usr/local/sbin/uniproxy-nginx start >/dev/null 2>&1') | crontab -; fi",
                f"if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then printf %s {shlex.quote(encoded_unit)} | base64 -d > /etc/systemd/system/uniproxy-nginx.service; systemctl daemon-reload; systemctl enable uniproxy-nginx >/dev/null; fi",
                "if command -v rc-service >/dev/null 2>&1; then rc-update add dcron default >/dev/null 2>&1 || rc-update add crond default >/dev/null 2>&1 || true; rc-service dcron start >/dev/null 2>&1 || rc-service crond start >/dev/null 2>&1 || true;",
                "elif command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then systemctl enable --now cron >/dev/null 2>&1 || systemctl enable --now crond >/dev/null 2>&1 || true;",
                "elif command -v service >/dev/null 2>&1; then service cron start >/dev/null 2>&1 || service crond start >/dev/null 2>&1 || true;",
                "elif command -v crond >/dev/null 2>&1; then pgrep crond >/dev/null 2>&1 || crond; fi",
            ])
            self._run(self._ssh_args(node) + [script], env=self._ssh_env(node), timeout=480)
            return self._detect_public_https_port(node), dns_records
        except Exception:
            self._delete_node_dns(dns_records)
            raise

    def renew_node_certificates(self) -> list[str]:
        """Renew centrally managed certificates and atomically push them."""
        with self._connect() as db:
            nodes = db.execute(
                "SELECT * FROM nodes WHERE auto_managed=1 AND kind!='local' AND state='active' ORDER BY id"
            ).fetchall()
        errors = []
        for node in nodes:
            stage = f"/tmp/uniproxy-cert-{secrets.token_hex(16)}"
            try:
                cert_path, key_path = self._issue_central_certificate(node)
                self._run(
                    self._ssh_args(node) + [f"umask 077; install -d -m 700 {shlex.quote(stage)}"],
                    env=self._ssh_env(node), timeout=30,
                )
                self._run(self._scp_args(node, cert_path, stage + "/fullchain.pem"), env=self._ssh_env(node), timeout=60)
                self._run(self._scp_args(node, key_path, stage + "/key.pem"), env=self._ssh_env(node), timeout=60)
                command = "\n".join([
                    "set -eu",
                    self._ca_bundle_prepare_script(str(node["ca_bundle_path"])),
                    f"install -m 0600 {shlex.quote(stage + '/key.pem')} {shlex.quote(str(node['tls_key_file']))}",
                    f"install -m 0644 {shlex.quote(stage + '/fullchain.pem')} {shlex.quote(str(node['tls_cert_file']))}",
                    "rm -f /root/.acme.sh/account.conf; if command -v crontab >/dev/null 2>&1; then crontab -l 2>/dev/null | grep -v 'acme.sh.*--cron' | crontab - || true; fi",
                    f"/usr/local/sbin/uniproxy-nginx reload",
                    f"rm -rf {shlex.quote(stage)}",
                ])
                self._run(self._ssh_args(node) + [command], env=self._ssh_env(node), timeout=90)
            except Exception as exc:
                errors.append(f"{node['name']}：{str(exc)[-240:]}")
                try:
                    self._run(self._ssh_args(node) + [f"rm -rf {shlex.quote(stage)}"], env=self._ssh_env(node), timeout=30)
                except Exception:
                    pass
        return errors

    def _render_mapping(self, route, node) -> str:
        allow_insecure_http = bool(route["allow_insecure_http"])
        resolution = self._resolve_route_origin(
            str(route["origin"]),
            allow_insecure_http=allow_insecure_http,
            enforce_user_ports=route["owner_user_id"] is not None,
        )
        redirect_token = str(route["redirect_token"] or "")
        if not redirect_token:
            redirect_token = secrets.token_urlsafe(24)
        redirect = None
        redirect_target = SAFE_REDIRECT_TARGETS.get(resolution.hostname.lower())
        if redirect_target:
            redirect_resolution = self._resolve_route_origin(
                "https://" + redirect_target,
                allow_insecure_http=False,
                enforce_user_ports=False,
            )
            redirect = RedirectSpec(
                hostname=redirect_resolution.hostname,
                upstream_ips=redirect_resolution.addresses,
                token=redirect_token,
                port=redirect_resolution.port,
                ca_bundle=str(node["ca_bundle_path"]),
            )
        try:
            content = render_route(RouteSpec(
                origin=resolution.origin,
                public_host=str(route["public_host"]),
                upstream_ips=resolution.addresses,
                tls_cert_file=str(node["tls_cert_file"]),
                tls_key_file=str(node["tls_key_file"]),
                public_https_port=int(node["public_https_port"]),
                internal_https_port=int(node["internal_https_port"]),
                ca_bundle=str(node["ca_bundle_path"]),
                allow_insecure_http=allow_insecure_http,
                # The generated configuration is consumed on the remote Linux
                # node.  Keep the path POSIX even when the control panel is
                # tested or run from Windows, where Path.__str__ uses '\\'.
                traffic_log_path=self.traffic_log_path.as_posix(),
                traffic_log_format=TRAFFIC_FORMAT_NAME,
                error_log_path="/var/log/uniproxy-route-error.log",
                redirect=redirect,
            ))
        except RendererError as exc:
            raise PanelError(f"无法生成安全的 Nginx 配置：{exc}") from exc
        with self._connect() as db:
            db.execute(
                "UPDATE routes SET origin=?,resolved_ips_json=?,resolved_at=?,"
                "upstream_security_status='verified',security_policy_version=2,"
                "redirect_token=?,updated_at=? WHERE id=?",
                (
                    resolution.origin,
                    json.dumps(resolution.addresses, separators=(",", ":")),
                    now(),
                    redirect_token,
                    now(),
                    route["id"],
                ),
            )
        return content
    def _run(self, command: list[str], env: dict | None = None, timeout: int = 40) -> str:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()

        def drain(stream, target: bytearray, limit: int) -> None:
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        return
                    if len(target) + len(chunk) > limit:
                        remaining = max(0, limit - len(target))
                        target.extend(chunk[:remaining])
                        overflow.set()
                        process.kill()
                        return
                    target.extend(chunk)
            finally:
                stream.close()

        threads = [
            threading.Thread(target=drain, args=(process.stdout, stdout, 4 * 1024 * 1024), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr, 64 * 1024), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            for thread in threads:
                thread.join(timeout=1)
            raise
        for thread in threads:
            thread.join(timeout=1)
        if overflow.is_set():
            raise PanelError("远程命令输出超过安全上限")
        output = (stdout + stderr).decode("utf-8", errors="replace").strip()
        if returncode != 0:
            raise PanelError(output[-700:] or "命令执行失败")
        return output

    @staticmethod
    def _is_transient_ssh_failure(message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in (
            "connection timed out", "operation timed out", "connection refused", "no route to host",
            "network is unreachable", "connection reset", "connection closed", "kex_exchange_identification",
            "banner exchange", "ssh_exchange_identification",
        ))

    def _wait_for_root_ssh(self, node) -> None:
        """Wait briefly for just-created VPS instances to finish bringing SSH online."""
        last_error = ""
        for attempt in range(SSH_READY_ATTEMPTS):
            try:
                user_id = self._run(
                    self._ssh_args(node) + ["id -u"], env=self._ssh_env(node), timeout=15,
                )
            except subprocess.TimeoutExpired:
                last_error = "SSH 连接超时"
            except PanelError as exc:
                last_error = str(exc)
                if not self._is_transient_ssh_failure(last_error):
                    raise
            else:
                if any(line.strip() == "0" for line in user_id.splitlines()):
                    return
                raise PanelError("自动部署需要 root SSH 登录")
            if attempt + 1 < SSH_READY_ATTEMPTS:
                time.sleep(SSH_READY_RETRY_SECONDS)
        detail = last_error.replace("\n", " ")[-240:]
        raise PanelError(
            f"节点 SSH 自动重试 {SSH_READY_ATTEMPTS} 次后仍未就绪，请确认 SSH 端口、账号和防火墙后重试"
            + (f"：{detail}" if detail else "")
        )

    def _ssh_args(self, node) -> list[str]:
        known_hosts = self.db_path.parent / "known_hosts"
        args = [
            "ssh", "-F", "/dev/null", "-p", str(node["ssh_port"]),
            "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "IdentitiesOnly=yes",
            "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no",
            "-o", "PermitLocalCommand=no",
            "-o", f"UserKnownHostsFile={known_hosts}",
        ]
        if self._node_password(node):
            args = ["sshpass", "-e"] + args
            args.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
        else:
            args.extend(["-o", "BatchMode=yes"])
        if node["ssh_identity"]:
            args.extend(["-i", node["ssh_identity"]])
        return args + [f"{node['ssh_user']}@{node['ssh_host']}"]

    def _scp_args(self, node, source: str, target: str, preserve_mode: bool = False) -> list[str]:
        known_hosts = self.db_path.parent / "known_hosts"
        args = [
            "scp", "-F", "/dev/null", "-P", str(node["ssh_port"]),
            "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "IdentitiesOnly=yes",
            "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no",
            "-o", "PermitLocalCommand=no",
            "-o", f"UserKnownHostsFile={known_hosts}",
        ]
        if self._node_password(node):
            args = ["sshpass", "-e"] + args
            args.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
        else:
            args.extend(["-o", "BatchMode=yes"])
        if node["ssh_identity"]:
            args.extend(["-i", node["ssh_identity"]])
        if preserve_mode:
            args.append("-p")
        args.extend([source, f"{node['ssh_user']}@{node['ssh_host']}:{target}"])
        return args

    def _ssh_env(self, node) -> dict | None:
        password = self._node_password(node)
        if not password:
            return None
        env = os.environ.copy()
        env["SSHPASS"] = password
        return env

    @staticmethod
    def _ca_bundle_prepare_script(path: str) -> str:
        """Return a small idempotent migration for old nodes.

        Earlier node deployments did not copy a CA bundle to the project
        directory, while newly rendered routes require that stable path for
        ``proxy_ssl_trusted_certificate``.  Keep the renderer stable and
        repair the path just before every remote nginx test/reload.  The
        source list covers the layouts used by Debian/Ubuntu, Alpine,
        RHEL-family and other common distributions.
        """
        ca_path = str(path or "").strip()
        if not ca_path.startswith("/") or "\n" in ca_path or "\r" in ca_path:
            raise PanelError("远端 CA bundle 路径不合法")
        quoted_path = shlex.quote(ca_path)
        return "\n".join([
            f"ca_bundle={quoted_path}",
            'if [ ! -r "$ca_bundle" ]; then',
            '  install -d -m 0755 "$(dirname "$ca_bundle")"',
            '  ca_source=""',
            '  for candidate in /etc/ssl/certs/ca-certificates.crt /etc/ssl/cert.pem /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/ca-bundle.pem /etc/ssl/certs/ca-bundle.crt; do',
            '    if [ -r "$candidate" ]; then ca_source="$candidate"; break; fi',
            '  done',
            '  if [ -z "$ca_source" ]; then echo "系统 CA bundle 不存在，请先安装 ca-certificates" >&2; exit 1; fi',
            '  install -m 0644 "$ca_source" "$ca_bundle"',
            'fi',
            'test -r "$ca_bundle" || { echo "CA bundle 不可读：$ca_bundle" >&2; exit 1; }',
        ])

    def _deploy_route(self, node, route) -> None:
        content = self._render_mapping(route, node)
        target = f"{node['generated_dir']}/{route['public_host']}.conf"
        traffic_target = f"{node['generated_dir']}/{TRAFFIC_CONFIG_NAME}"
        traffic_content = self._traffic_format_config()
        managed = bool(node["auto_managed"])
        if node["kind"] == "local":
            path = Path(target)
            traffic_path = Path(traffic_target)
            path.parent.mkdir(parents=True, exist_ok=True)
            previous = path.read_bytes() if path.exists() else None
            previous_traffic = traffic_path.read_bytes() if traffic_path.exists() else None
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
                file.write(content)
                temporary = file.name
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
                file.write(traffic_content)
                traffic_temporary = file.name
            try:
                os.chmod(temporary, 0o644)
                os.chmod(traffic_temporary, 0o644)
                os.replace(traffic_temporary, traffic_path)
                os.replace(temporary, path)
                self._run(["/usr/sbin/nginx", "-t", "-c", node["caddy_config"]])
                if managed:
                    self._run(["/usr/local/sbin/uniproxy-nginx", "reload"])
                else:
                    self._run(["/bin/systemctl", "reload", "nginx"])
            except Exception:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(previous)
                if previous_traffic is None:
                    traffic_path.unlink(missing_ok=True)
                else:
                    traffic_path.write_bytes(previous_traffic)
                raise
            finally:
                Path(temporary).unlink(missing_ok=True)
                Path(traffic_temporary).unlink(missing_ok=True)
            return
        encoded = base64.b64encode(content.encode()).decode()
        encoded_traffic = base64.b64encode(traffic_content.encode()).decode()
        backup = target + ".panel-backup"
        temporary = target + ".panel-new"
        traffic_backup = traffic_target + ".panel-backup"
        traffic_temporary = traffic_target + ".panel-new"
        reload_command = "/usr/local/sbin/uniproxy-nginx reload" if managed else "/bin/systemctl reload nginx"
        ca_prepare = self._ca_bundle_prepare_script(str(node["ca_bundle_path"]))
        script = "\n".join([
            "set -eu", ca_prepare, f"mkdir -p {shlex.quote(node['generated_dir'])}",
            f"target={shlex.quote(target)}", f"backup={shlex.quote(backup)}", f"temporary={shlex.quote(temporary)}",
            f"traffic_target={shlex.quote(traffic_target)}", f"traffic_backup={shlex.quote(traffic_backup)}", f"traffic_temporary={shlex.quote(traffic_temporary)}",
            "had_old=0", "had_traffic_old=0",
            'if [ -f "$target" ]; then cp "$target" "$backup"; had_old=1; fi',
            'if [ -f "$traffic_target" ]; then cp "$traffic_target" "$traffic_backup"; had_traffic_old=1; fi',
            "restore() { if [ \"$had_old\" = 1 ]; then mv \"$backup\" \"$target\"; else rm -f \"$target\"; fi; if [ \"$had_traffic_old\" = 1 ]; then mv \"$traffic_backup\" \"$traffic_target\"; else rm -f \"$traffic_target\"; fi; rm -f \"$temporary\" \"$traffic_temporary\"; }",
            f"printf %s {shlex.quote(encoded_traffic)} | base64 -d > \"$traffic_temporary\"", 'install -m 0644 "$traffic_temporary" "$traffic_target"',
            f"printf %s {shlex.quote(encoded)} | base64 -d > \"$temporary\"", 'install -m 0644 "$temporary" "$target"',
            f"if ! /usr/sbin/nginx -t -c {shlex.quote(node['caddy_config'])}; then",
            '  restore; exit 1', "fi",
            f"if ! {reload_command}; then", "  restore;",
            f"  {reload_command} || true; exit 1", "fi", 'rm -f "$backup" "$temporary" "$traffic_backup" "$traffic_temporary"',
        ])
        self._run(self._ssh_args(node) + [script], env=self._ssh_env(node))

    def _delete_route_file(self, node, route) -> None:
        target = f"{node['generated_dir']}/{route['public_host']}.conf"
        managed = bool(node["auto_managed"])
        if node["kind"] == "local":
            path = Path(target)
            previous = path.read_bytes() if path.exists() else None
            path.unlink(missing_ok=True)
            try:
                self._run(["/usr/sbin/nginx", "-t", "-c", node["caddy_config"]])
                if managed:
                    self._run(["/usr/local/sbin/uniproxy-nginx", "reload"])
                else:
                    self._run(["/bin/systemctl", "reload", "nginx"])
            except Exception:
                if previous is not None:
                    path.write_bytes(previous)
                raise
            return
        backup = target + ".panel-backup"
        reload_command = "/usr/local/sbin/uniproxy-nginx reload" if managed else "/bin/systemctl reload nginx"
        ca_prepare = self._ca_bundle_prepare_script(str(node["ca_bundle_path"]))
        script = "\n".join([
            "set -eu", ca_prepare, f"target={shlex.quote(target)}", f"backup={shlex.quote(backup)}", "had_old=0",
            'if [ -f "$target" ]; then cp "$target" "$backup"; rm -f "$target"; had_old=1; fi',
            f"if ! /usr/sbin/nginx -t -c {shlex.quote(node['caddy_config'])}; then",
            '  if [ "$had_old" = 1 ]; then mv "$backup" "$target"; fi; exit 1', "fi",
            f"if ! {reload_command}; then", '  if [ "$had_old" = 1 ]; then mv "$backup" "$target"; fi',
            f"  {reload_command} || true; exit 1", "fi", 'rm -f "$backup"',
        ])
        self._run(self._ssh_args(node) + [script], env=self._ssh_env(node))

    def _delete_route_file_best_effort(self, node, route) -> str:
        """Remove a route, tolerating cleanup failures for failed deployments.

        Deployment can fail before a node has a usable Nginx installation (or
        the node can disappear entirely).  In that state the database record
        must remain deletable; otherwise one broken node permanently consumes
        a route slot and blocks node removal.  Confirmed deployments remain
        strict: callers still receive the cleanup error instead of hiding a
        potentially live remote configuration.
        """
        deployed = int(route["deployed"] or 0) == 1
        state = str(route["state"] or "").strip().lower()
        confirmed = deployed or state == "deployed"
        if node is None:
            if confirmed:
                raise PanelError("线路关联的节点不存在，且线路可能仍在远端运行；请先恢复节点后删除")
            return "节点记录不存在，未确认远端配置清理"
        try:
            self._delete_route_file(node, route)
        except Exception as exc:
            if confirmed:
                raise
            detail = str(exc).strip().replace("\r", " ").replace("\n", " ")
            if len(detail) > 240:
                detail = detail[-240:]
            return f"节点清理未确认{': ' + detail if detail else ''}"
        return ""

    def _check_node(self, node) -> str:
        if node["kind"] == "local":
            self._run(["/usr/sbin/nginx", "-t", "-c", node["caddy_config"]])
            try:
                self._run(["/bin/systemctl", "is-active", "--quiet", "nginx"])
            except PanelError as exc:
                raise PanelError("本机 Nginx 配置有效，但服务未运行") from exc
            public_url = self._public_url(node, node["domain_suffix"]).rstrip("/") + "/__health"
            try:
                self._check_public_probe(node)
            except PanelError as exc:
                raise PanelError(f"本机 Nginx 正常，但公网 HTTPS 检查失败（{public_url}）：{str(exc)[-240:]}") from exc
            return f"检查通过：Nginx 配置、服务和公网 HTTPS 均正常；{public_url}"
        requirements = [
            ("-x", "/usr/sbin/nginx", "远端未安装 Nginx：/usr/sbin/nginx"),
            ("-d", node["generated_dir"], f"线路生成目录不存在：{node['generated_dir']}"),
            ("-r", node["tls_cert_file"], f"TLS 证书不可读：{node['tls_cert_file']}"),
            ("-r", node["tls_key_file"], f"TLS 私钥不可读：{node['tls_key_file']}"),
            ("-r", node["caddy_config"], f"Nginx 配置不可读：{node['caddy_config']}"),
        ]
        if node["auto_managed"]:
            requirements.append(("-x", "/usr/local/sbin/uniproxy-nginx", "自动 Nginx 控制器不存在"))
        commands = ["set -eu", self._ca_bundle_prepare_script(str(node["ca_bundle_path"]))]
        for test, path, message in requirements:
            commands.append(f"test {test} {shlex.quote(path)} || {{ echo {shlex.quote(message)} >&2; exit 1; }}")
        commands.append(f"/usr/sbin/nginx -t -c {shlex.quote(node['caddy_config'])}")
        if node["auto_managed"]:
            commands.append(
                "/usr/local/sbin/uniproxy-nginx status || "
                "{ echo '远端 Nginx 配置有效，但进程未运行' >&2; exit 1; }"
            )
        else:
            commands.extend([
                "nginx_running=0",
                "if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && systemctl is-active --quiet nginx; then nginx_running=1; fi",
                "if [ \"$nginx_running\" -eq 0 ] && command -v pgrep >/dev/null 2>&1 && pgrep -x nginx >/dev/null; then nginx_running=1; fi",
                "if [ \"$nginx_running\" -eq 0 ] && command -v pidof >/dev/null 2>&1 && pidof nginx >/dev/null; then nginx_running=1; fi",
                "if [ \"$nginx_running\" -eq 0 ] && ps | grep '[n]ginx' >/dev/null; then nginx_running=1; fi",
                "[ \"$nginx_running\" -eq 1 ] || { echo '远端 Nginx 配置有效，但进程未运行' >&2; exit 1; }",
            ])
        internal_port = int(node["internal_https_port"])
        internal_host = str(node["domain_suffix"])
        internal_authority = f"{internal_host}:{internal_port}"
        internal_url = f"https://{internal_authority}/__health"
        commands.extend([
            "command -v curl >/dev/null 2>&1 || { echo '远端缺少 curl，无法执行内部 HTTPS 检查' >&2; exit 1; }",
            "curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "
            f"--resolve {shlex.quote(internal_authority + ':127.0.0.1')} --output /dev/null {shlex.quote(internal_url)} || "
            f"{{ echo {shlex.quote('远端 Nginx 已运行，但内部 HTTPS 健康检查失败：' + internal_url)} >&2; exit 1; }}",
        ])
        command = "\n".join(commands)
        self._run(self._ssh_args(node) + [command], env=self._ssh_env(node))
        public_url = self._public_url(node, node["domain_suffix"]).rstrip("/") + "/__health"
        try:
            self._check_public_probe(node)
        except PanelError as exc:
            raise PanelError(
                f"远端 Nginx 和内部 HTTPS 正常，但公网 HTTPS 检查失败（{public_url}）：{str(exc)[-240:]}"
            ) from exc
        return f"检查通过：SSH、Nginx 配置、进程、内部 HTTPS 和公网 HTTPS 均正常；{public_url}"

    def _check_public_probe(self, node) -> str:
        url = self._public_url(node, node["domain_suffix"]).rstrip("/") + "/__health"
        self._run([
            "/usr/bin/curl", "--fail", "--silent", "--show-error", "--location",
            "--connect-timeout", "8", "--max-time", "15", "--output", "/dev/null", url,
        ])
        return url

    def _probe_route(self, node, route) -> int:
        url = self._public_url(node, route["public_host"])
        output = self._run([
            "/usr/bin/curl", "--silent", "--show-error",
            "--connect-timeout", "8", "--max-time", "20",
            "--output", "/dev/null", "--write-out", "%{http_code}", url,
        ])
        try:
            status = int(output.strip())
        except ValueError as exc:
            raise PanelError(f"公网验证没有返回有效 HTTP 状态：{output[-100:]}") from exc
        if status == 403:
            raise PanelError("公网地址返回 HTTP 403：源站或其 WAF 拒绝当前节点出口 IP")
        if status in {502, 504}:
            raise PanelError(f"公网地址返回 HTTP {status}，Nginx 已载入但无法连接源站")
        return status

    def _deploy_and_verify(self, node, route) -> int:
        if route["owner_user_id"] is not None:
            with self._connect() as db:
                owner = db.execute("SELECT * FROM users WHERE id=?", (route["owner_user_id"],)).fetchone()
            if not self._is_user_active(owner):
                raise PanelError("所属用户已停用或已到期，不能下发线路")
        try:
            self._deploy_route(node, route)
        except Exception as exc:
            with self._connect() as db:
                db.execute(
                    "UPDATE routes SET state='failed',last_error = ?, updated_at = ? WHERE id = ?",
                    (f"下发失败：{exc}"[:700], now(), route["id"]),
                )
            raise
        with self._connect() as db:
            db.execute(
                "UPDATE routes SET deployed = 1,state='deployed',last_error = '',updated_at = ? WHERE id = ?",
                (now(), route["id"]),
            )
        try:
            status = self._probe_route(node, route)
        except Exception as exc:
            message = f"配置已下发，但公网验证失败：{exc}"
            with self._connect() as db:
                db.execute(
                    "UPDATE routes SET state='deployed',last_error = ?, updated_at = ? WHERE id = ?",
                    (message[:700], now(), route["id"]),
                )
            raise PanelError(message) from exc
        return status

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if not self.enabled:
            raise web.HTTPNotFound()
        admin = self.require_admin(request)
        csrf_token = str(admin["csrf_secret"])

        def admin_overview(**kwargs):
            return self.overview_dashboard(csrf_token=csrf_token, **kwargs)

        def admin_dashboard(**kwargs):
            return self.dashboard(csrf_token=csrf_token, **kwargs)

        def admin_routes(**kwargs):
            return self.routes_dashboard(csrf_token=csrf_token, **kwargs)

        def admin_users(**kwargs):
            return self.users_dashboard(csrf_token=csrf_token, **kwargs)

        def admin_invites(**kwargs):
            return self.invites_dashboard(csrf_token=csrf_token, **kwargs)

        try:
            route_page = max(1, int(request.query.get("page", "1")))
        except ValueError:
            route_page = 1
        if request.method == "GET":
            if request.path in {ADMIN_PREFIX, ADMIN_PREFIX + "/"}:
                raise web.HTTPFound(ADMIN_PREFIX + "/overview")
            if request.path == ADMIN_PREFIX + "/overview":
                return admin_overview()
            if request.path == ADMIN_PREFIX + "/nodes":
                return admin_dashboard()
            if request.path == ADMIN_PREFIX + "/routes":
                return admin_routes(route_page=route_page)
            if request.path == ADMIN_PREFIX + "/users":
                return admin_users()
            if request.path == ADMIN_PREFIX + "/invites":
                notice = "邀请码已创建，可在下方列表长期查看。" if request.query.get("created") == "1" else ""
                return admin_invites(notice=notice)
            raise web.HTTPNotFound()
        if request.path.startswith(ADMIN_PREFIX + "/invites"):
            view = "invites"
        elif request.path.startswith(ADMIN_PREFIX + "/routes"):
            view = "routes"
        elif request.path.startswith(ADMIN_PREFIX + "/users"):
            view = "users"
        else:
            view = "nodes"
        try:
            if request.method != "POST":
                raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST"])
            data = await request.post()
            if request.path == ADMIN_PREFIX + "/invites":
                self._check_user_csrf(admin, data)
                await asyncio.to_thread(self._create_invite, data)
                raise web.HTTPSeeOther(ADMIN_PREFIX + "/invites?created=1")
            invite_match = re.fullmatch(re.escape(ADMIN_PREFIX) + r"/invites/(\d+)/(revoke|delete)", request.path)
            if invite_match:
                invite_id, action = int(invite_match.group(1)), invite_match.group(2)
                self._check_user_csrf(admin, data)
                if action == "delete":
                    redemption_count = await asyncio.to_thread(self._delete_invite, invite_id)
                    return admin_invites(notice=f"邀请码已删除；已清除 {redemption_count} 条兑换记录。")
                with self._connect() as db:
                    changed = db.execute("UPDATE invites SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now(), invite_id)).rowcount
                if not changed:
                    raise PanelError("邀请码不存在或已撤销")
                return admin_invites(notice="邀请码已撤销。")
            user_match = re.fullmatch(re.escape(ADMIN_PREFIX) + r"/users/(\d+)/(update|enable|disable|reset-password|delete)", request.path)
            if user_match:
                user_id, action = int(user_match.group(1)), user_match.group(2)
                self._check_user_csrf(admin, data)
                if action == "update":
                    should_resume = await asyncio.to_thread(self._update_user, user_id, data)
                    errors = await asyncio.to_thread(self._resume_owned_routes, user_id) if should_resume else []
                    suffix = "；线路恢复失败：" + "；".join(errors[:2]) if errors else ""
                    return admin_users(notice="用户信息已保存" + suffix)
                if action in {"enable", "disable"}:
                    errors = await asyncio.to_thread(self._set_user_enabled, user_id, action == "enable")
                    suffix = "；部分线路处理失败：" + "；".join(errors[:2]) if errors else ""
                    return admin_users(notice=("用户已启用并恢复线路" if action == "enable" else "用户已停用并下线线路") + suffix)
                if action == "reset-password":
                    try:
                        temporary = await self.hash_limiter.run(self._reset_user_password, user_id)
                    except HashWorkLimitExceeded as exc:
                        raise web.HTTPServiceUnavailable(
                            text="password service is busy", headers={"Retry-After": "3"}
                        ) from exc
                    return admin_users(notice="临时密码（仅显示一次，用户登录后必须修改）：" + temporary)
                await asyncio.to_thread(self._delete_user_and_routes, user_id)
                return admin_users(notice="用户及其全部线路已删除。")
            if request.path == ADMIN_PREFIX + "/nodes":
                self._check_user_csrf(admin, data)
                name = str(data.get("name", "")).strip()
                if not SAFE_NAME.fullmatch(name):
                    raise PanelError("节点名称必须为 1–48 位中文、字母、数字、空格、连字符或下划线")
                network_mode = str(data.get("network_mode", "vps")).strip().lower()
                if network_mode not in {"vps", "nat"}:
                    raise PanelError("网络类型不正确")
                address = str(data.get("ssh_host", "")).strip()
                try:
                    parsed_address = ipaddress.ip_address(address)
                    ssh_port = int(str(data.get("ssh_port", "22")))
                    public_value = str(data.get("public_https_port", "")).strip()
                    if not public_value and network_mode == "nat":
                        # Accept the field name used by the previous NAT form
                        # while browsers still have a cached copy of it.
                        public_value = str(data.get("nat_https_port", "")).strip()
                    public_port = int(public_value or "443")
                    internal_port = int(str(data.get("internal_https_port", "443")))
                except ValueError as exc:
                    raise PanelError("服务器 IP、SSH 端口、公网端口或内部 HTTPS 端口格式不正确") from exc
                if parsed_address.version != 4 or not parsed_address.is_global:
                    raise PanelError("服务器 IP 必须是公网 IPv4 地址")
                if not 1 <= ssh_port <= 65535:
                    raise PanelError("SSH 端口超出范围")
                if not 1 <= public_port <= 65535:
                    raise PanelError("公网 HTTPS 端口超出范围")
                if not 1 <= internal_port <= 65535:
                    raise PanelError("内部 HTTPS 端口超出范围")
                password = str(data.get("ssh_password", ""))
                if len(password) > 512:
                    raise PanelError("SSH 密码过长")
                if password and not self.node_credential_cipher:
                    raise PanelError("请先配置 NODE_CREDENTIAL_ENCRYPTION_KEY，再添加密码登录节点")
                with self._connect() as db:
                    if db.execute("SELECT 1 FROM nodes WHERE name = ?", (name,)).fetchone():
                        raise PanelError("节点名称已存在")
                identity = self._store_private_key(data.get("ssh_private_key"))
                if bool(password) == bool(identity):
                    if identity:
                        Path(identity).unlink(missing_ok=True)
                    raise PanelError("SSH 密码和私钥必须且只能提供一个")
                domain_suffix = self._auto_domain_suffix(name, address, ssh_port)
                cert_dir = "/etc/uniproxy-nginx/certs"
                candidate = {
                    "name": name, "kind": "ssh", "ssh_host": address, "ssh_port": ssh_port,
                    "ssh_user": "root", "ssh_identity": identity, "ssh_password": password,
                    "domain_suffix": domain_suffix, "tls_cert_file": cert_dir + "/fullchain.pem",
                    "tls_key_file": cert_dir + "/key.pem",
                    "caddy_config": "/etc/uniproxy-nginx/nginx.conf",
                    "generated_dir": "/etc/uniproxy-nginx/conf.d", "auto_managed": 1,
                    "network_mode": network_mode, "public_https_port": public_port,
                    "internal_https_port": internal_port,
                    # Kept as empty compatibility fields for the legacy schema;
                    # host-key pinning was intentionally removed from the form.
                    "ssh_host_key": "", "ssh_host_fingerprint": "", "host_key_verified_at": "",
                }
                detected_internal_port = await asyncio.to_thread(self._detect_existing_nginx_port, candidate)
                if detected_internal_port is not None:
                    candidate["internal_https_port"] = detected_internal_port
                country_name, country_code, country_flag = await self._lookup_node_location(address)
                dns_records = []
                try:
                    public_port, dns_records = await asyncio.to_thread(self._provision_auto_node, candidate)
                    candidate["public_https_port"] = public_port
                    effective_internal_port = int(candidate["internal_https_port"])
                    security_notice = (
                        "警告：本次节点部署按管理员设置跳过了 Nginx 出站保护；该节点不应代理不受信任的源站。"
                        if self.allow_unprotected_egress else ""
                    )
                    if detected_internal_port is not None:
                        port_notice = (
                            f"最终采用端口：公网 HTTPS {int(public_port)} → 节点内部 {effective_internal_port}；"
                            f"已检测到远端 Nginx 端口并忽略表单中的内部端口。请确认服务商映射到内部 {effective_internal_port}。"
                        )
                    else:
                        port_notice = (
                            f"最终采用端口：公网 HTTPS {int(public_port)} → 节点内部 {effective_internal_port}；"
                            f"使用表单填写的内部端口，请确认服务商映射正确。"
                        )
                    with self._connect() as db:
                        db.execute(
                            "INSERT INTO nodes (name,kind,ssh_host,ssh_port,ssh_user,ssh_identity,ssh_password,ssh_password_ciphertext,domain_suffix,tls_cert_file,tls_key_file,caddy_config,generated_dir,public_https_port,internal_https_port,country_name,country_code,country_flag,network_mode,auto_managed,ssh_host_key,ssh_host_fingerprint,host_key_verified_at,dns_record_ids_json,cert_mode,state,security_policy_version,created_at,updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,1,?,?,?,?,'central','active',2,?,?)",
                            (candidate["name"], candidate["kind"], candidate["ssh_host"], candidate["ssh_port"],
                             candidate["ssh_user"], candidate["ssh_identity"], "",
                             self.node_credential_cipher.encrypt(candidate["ssh_password"].encode()).decode() if candidate["ssh_password"] and self.node_credential_cipher else candidate["ssh_password"],
                             candidate["domain_suffix"], candidate["tls_cert_file"], candidate["tls_key_file"],
                             candidate["caddy_config"], candidate["generated_dir"], candidate["public_https_port"], candidate["internal_https_port"],
                             country_name, country_code, country_flag, candidate["network_mode"],
                             candidate["ssh_host_key"], candidate["ssh_host_fingerprint"], candidate["host_key_verified_at"],
                             json.dumps(dns_records, separators=(",", ":")), now(), now()),
                        )
                except Exception:
                    await asyncio.to_thread(self._delete_node_dns, dns_records)
                    if identity:
                        Path(identity).unlink(missing_ok=True)
                    raise
                location = f"已识别为 {country_flag} {country_name}（{country_code}）；" if country_code else "未能识别地区，可稍后在节点名称中标注地区；"
                probe_url = self._public_url(candidate, domain_suffix).rstrip("/") + "/__health"
                return admin_dashboard(notice=security_notice + port_notice + location + f"节点已自动部署并添加；公网探测地址：{probe_url}")
            node_delete_match = re.fullmatch(re.escape(ADMIN_PREFIX) + r"/nodes/(\d+)/delete", request.path)
            if node_delete_match:
                node_id = int(node_delete_match.group(1))
                self._check_user_csrf(admin, data)
                with self._connect() as db:
                    node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
                    if not node:
                        raise PanelError("节点不存在")
                    route_count = db.execute("SELECT COUNT(*) FROM routes WHERE node_id = ?", (node_id,)).fetchone()[0]
                    if route_count:
                        raise PanelError(f"节点仍关联 {route_count} 条线路，请先删除线路")
                    if node["kind"] == "local":
                        db.execute(
                            "INSERT INTO settings (key,value) VALUES ('local_node_disabled','1') "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                        )
                    db.execute(
                        "UPDATE nodes SET state='decommissioning',state_step='dns-and-remote-cleanup',last_error='',updated_at=? WHERE id=?",
                        (now(), node_id),
                    )
                try:
                    await asyncio.to_thread(self._cleanup_managed_node, node)
                except Exception as exc:
                    if self._remote_cleanup_unreachable(exc):
                        # DNS cleanup has already completed before the remote
                        # SSH step. Detach the local record so an offline node
                        # cannot block the panel forever; remote files remain
                        # for manual cleanup when the machine returns.
                        self._remove_node_identity(node)
                        with self._connect() as db:
                            db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
                        return admin_dashboard(
                            notice="后台节点记录已删除；远端 SSH 当前不可达，远端项目文件未清理。"
                        )
                    with self._connect() as db:
                        db.execute(
                            "UPDATE nodes SET state='decommission_failed',last_error=?,updated_at=? WHERE id=?",
                            (str(exc)[-700:], now(), node_id),
                        )
                    raise PanelError("节点清理未完成，已保留记录并标记为待重试：" + str(exc)[-240:]) from exc
                with self._connect() as db:
                    db.execute("UPDATE nodes SET state='decommissioned',state_step='complete',updated_at=? WHERE id=?", (now(), node_id))
                    db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
                return admin_dashboard(notice="节点已删除。")
            node_match = re.fullmatch(re.escape(ADMIN_PREFIX) + r"/nodes/(\d+)/check", request.path)
            if node_match:
                node_id = int(node_match.group(1))
                self._check_user_csrf(admin, data)
                with self._connect() as db:
                    node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
                if not node:
                    raise PanelError("节点不存在")
                message = await asyncio.to_thread(self._check_node, node)
                return admin_dashboard(notice=message)
            if request.path == ADMIN_PREFIX + "/routes":
                self._check_user_csrf(admin, data)
                name = str(data.get("name", "")).strip().lower()
                if not SAFE_SLUG.fullmatch(name):
                    raise PanelError("线路名称必须为 2–32 位小写字母、数字或连字符")
                resolution = await asyncio.to_thread(
                    self._resolve_route_origin,
                    str(data.get("origin", "")),
                    allow_insecure_http=False,
                    enforce_user_ports=False,
                )
                origin = resolution.origin
                node_id = int(str(data.get("node_id", "")))
                with self._connect() as db:
                    node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
                    if not node:
                        raise PanelError("节点不存在")
                    host = f"{name}.{node['domain_suffix']}"
                    cursor = db.execute(
                        "INSERT INTO routes (node_id,name,origin,public_host,deployed,state,resolved_ips_json,resolved_at,upstream_security_status,security_policy_version,redirect_token,created_at,updated_at) "
                        "VALUES (?,?,?,?,0,'pending',?,?,'verified',2,?,?,?)",
                        (
                            node_id, name, origin, host,
                            json.dumps(resolution.addresses, separators=(",", ":")), now(),
                            secrets.token_urlsafe(24), now(), now(),
                        ),
                    )
                    route = db.execute("SELECT * FROM routes WHERE id = ?", (cursor.lastrowid,)).fetchone()
                status = await asyncio.to_thread(self._deploy_and_verify, node, route)
                return admin_routes(notice=f"线路已创建、下发并通过公网验证（HTTP {status}）。", route_page=route_page)
            route_match = re.fullmatch(re.escape(ADMIN_PREFIX) + r"/routes/(\d+)/(deploy|delete)", request.path)
            if route_match:
                route_id, action = int(route_match.group(1)), route_match.group(2)
                self._check_user_csrf(admin, data)
                with self._connect() as db:
                    route = db.execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
                    if not route:
                        raise PanelError("线路不存在")
                    node = db.execute("SELECT * FROM nodes WHERE id = ?", (route["node_id"],)).fetchone()
                if action == "deploy":
                    status = await asyncio.to_thread(self._deploy_and_verify, node, route)
                    return admin_routes(notice=f"线路已下发并通过公网验证（HTTP {status}）。", route_page=route_page)
                cleanup_warning = await asyncio.to_thread(self._delete_route_file_best_effort, node, route)
                with self._connect() as db:
                    db.execute("DELETE FROM routes WHERE id = ?", (route_id,))
                notice = "线路记录已删除。"
                if cleanup_warning:
                    notice += f" {cleanup_warning}。"
                return admin_routes(notice=notice, route_page=route_page)
            raise web.HTTPNotFound()
        except web.HTTPException:
            raise
        except (PanelError, ValueError, sqlite3.Error) as exc:
            if view == "invites":
                return admin_invites(error=str(exc))
            if view == "routes":
                return admin_routes(error=str(exc), route_page=route_page)
            return admin_users(error=str(exc)) if view == "users" else admin_dashboard(error=str(exc))
        except subprocess.TimeoutExpired:
            if view == "invites":
                return admin_invites(error="操作超时；没有确认配置已生效。")
            if view == "routes":
                return admin_routes(error="操作超时；没有确认配置已生效。", route_page=route_page)
            return admin_users(error="操作超时；没有确认配置已生效。") if view == "users" else admin_dashboard(error="操作超时；没有确认配置已生效。")
        except Exception as exc:
            if view == "invites":
                return admin_invites(error=f"操作失败：{exc}")
            if view == "routes":
                return admin_routes(error=f"操作失败：{exc}", route_page=route_page)
            return admin_users(error=f"操作失败：{exc}") if view == "users" else admin_dashboard(error=f"操作失败：{exc}")
