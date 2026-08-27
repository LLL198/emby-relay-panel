#!/usr/bin/env python3
"""HTTP entry point for the emby-relay-panel user and admin interfaces."""

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
PROXY_DOMAIN_SUFFIX = os.environ.get("PROXY_DOMAIN_SUFFIX", "panel.example.com").lower().strip(".")

DASHBOARD_UI_CSS = r"""
:root{
  color-scheme:dark;
  --canvas:#050711;
  --surface:rgba(10,15,30,.78);
  --surface-strong:rgba(14,20,38,.94);
  --surface-soft:rgba(20,27,48,.62);
  --line:rgba(148,163,184,.15);
  --line-strong:rgba(148,163,184,.25);
  --ink:#f8fafc;
  --muted:#94a3b8;
  --muted-strong:#cbd5e1;
  --violet:#8b5cf6;
  --violet-bright:#a78bfa;
  --cyan:#22d3ee;
  --emerald:#34d399;
  --danger:#fb7185;
  --radius:22px;
  --shadow:0 24px 80px rgba(0,0,0,.38);
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{background:var(--canvas);scroll-behavior:smooth}
body{
  position:relative;
  isolation:isolate;
  margin:0;
  min-height:100vh;
  overflow-x:hidden;
  background:
    radial-gradient(circle at 10% -8%,rgba(124,58,237,.22),transparent 34%),
    radial-gradient(circle at 92% 8%,rgba(6,182,212,.15),transparent 30%),
    linear-gradient(150deg,#050711 0%,#070a15 45%,#050816 100%);
  color:var(--ink);
  font:15px/1.6 "PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
body:before{
  content:"";
  position:fixed;
  z-index:-2;
  inset:-24%;
  width:auto;
  height:auto;
  pointer-events:none;
  border-radius:0;
  filter:blur(18px);
  background:
    radial-gradient(circle at 26% 28%,rgba(139,92,246,.18),transparent 19%),
    radial-gradient(circle at 72% 22%,rgba(34,211,238,.13),transparent 18%),
    radial-gradient(circle at 55% 76%,rgba(59,130,246,.11),transparent 22%);
  animation:magic-aurora 18s ease-in-out infinite alternate;
}
body:after{
  content:"";
  position:fixed;
  z-index:-1;
  inset:0;
  width:auto;
  height:auto;
  pointer-events:none;
  border-radius:0;
  filter:none;
  opacity:.42;
  background-image:
    linear-gradient(rgba(148,163,184,.055) 1px,transparent 1px),
    linear-gradient(90deg,rgba(148,163,184,.055) 1px,transparent 1px);
  background-size:52px 52px;
  mask-image:linear-gradient(to bottom,black 0%,rgba(0,0,0,.72) 58%,transparent 100%);
  animation:magic-grid 24s linear infinite;
}
::selection{background:rgba(139,92,246,.42);color:#fff}
.app-shell{position:relative;z-index:1;width:min(100%,1240px);max-width:1240px;margin:0 auto;padding:22px 28px 72px}

.topbar{
  position:sticky;
  z-index:20;
  top:14px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:18px;
  min-height:64px;
  margin:0 0 56px;
  padding:10px 12px;
  border:1px solid rgba(148,163,184,.14);
  border-radius:18px;
  background:rgba(7,10,22,.72);
  box-shadow:0 18px 55px rgba(0,0,0,.25),inset 0 1px rgba(255,255,255,.035);
  backdrop-filter:blur(22px) saturate(135%);
}
.brand{display:flex;align-items:center;gap:12px;color:var(--ink);text-decoration:none}
.brand-mark{
  display:grid;
  place-items:center;
  width:40px;
  height:40px;
  border:1px solid transparent;
  border-radius:13px;
  background:linear-gradient(#0a0f20,#0a0f20) padding-box,linear-gradient(135deg,var(--violet),var(--cyan)) border-box;
  box-shadow:0 0 28px rgba(139,92,246,.25),inset 0 0 18px rgba(139,92,246,.08);
  color:#fff;
  font-size:15px;
  font-weight:900;
}
.brand-copy{display:grid;line-height:1.15}
.brand-copy strong{font-size:14px;letter-spacing:.01em}
.brand-copy small{margin-top:4px;color:#64748b;font-size:9px;font-weight:700;letter-spacing:.18em;text-transform:uppercase}
.account-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px}
.account-actions>a,.account-actions button.logout{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-height:38px;
  padding:0 12px;
  border:1px solid var(--line);
  border-radius:11px;
  background:rgba(15,23,42,.62);
  box-shadow:none;
  color:var(--muted-strong);
  font-size:12px;
  font-weight:700;
  text-decoration:none;
  transition:border-color .18s,background .18s,color .18s,transform .18s;
}
.account-actions>a:hover,.account-actions button.logout:hover{border-color:rgba(167,139,250,.4);background:rgba(30,41,59,.78);color:#fff;transform:translateY(-1px);box-shadow:none}
.account-actions .admin-link{border-color:rgba(34,211,238,.24);background:rgba(8,145,178,.08);color:#a5f3fc}
.logout-form{margin:0}
.live{
  display:flex;
  align-items:center;
  gap:9px;
  min-height:38px;
  padding:0 13px;
  border:1px solid var(--line);
  border-radius:999px;
  background:rgba(15,23,42,.48);
  color:var(--muted);
  font-size:12px;
}
.live i{width:8px;height:8px;border-radius:50%;background:var(--emerald);box-shadow:0 0 0 5px rgba(52,211,153,.1);animation:magic-pulse 2.8s ease-in-out infinite}

.hero{display:grid;grid-template-columns:minmax(0,1.28fr) minmax(320px,.72fr);align-items:end;gap:56px;max-width:none;margin:0 0 30px;padding:0 8px;text-align:left}
.hero-copy{max-width:720px}
.eyebrow{
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding:6px 10px;
  border:1px solid rgba(167,139,250,.2);
  border-radius:999px;
  background:rgba(139,92,246,.07);
  color:#c4b5fd;
  font-size:10px;
  font-weight:850;
  letter-spacing:.16em;
  text-transform:uppercase;
}
.eyebrow:before{content:"";width:7px;height:7px;border-radius:50%;background:linear-gradient(135deg,var(--violet-bright),var(--cyan));box-shadow:0 0 12px rgba(34,211,238,.55)}
.hero h1{margin:18px 0 17px;color:var(--ink);font-size:clamp(42px,5.2vw,68px);font-weight:850;line-height:1.04;letter-spacing:-.065em;text-wrap:balance}
.hero h1 span{color:transparent;background:linear-gradient(100deg,#c4b5fd 4%,#67e8f9 48%,#c4b5fd 96%);background-size:200% auto;background-clip:text;-webkit-background-clip:text;animation:magic-title 7s linear infinite}
.subtitle,.hint{color:var(--muted);line-height:1.75}
.subtitle{max-width:610px;margin:0;font-size:15px}
.hero-stats{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.stat{
  position:relative;
  min-height:126px;
  padding:20px;
  overflow:hidden;
  border:1px solid transparent;
  border-radius:20px;
  background:linear-gradient(rgba(11,16,31,.9),rgba(11,16,31,.9)) padding-box,linear-gradient(145deg,rgba(167,139,250,.38),rgba(34,211,238,.08),rgba(148,163,184,.14)) border-box;
  box-shadow:0 20px 55px rgba(0,0,0,.22),inset 0 1px rgba(255,255,255,.035);
}
.stat:before{content:"";position:absolute;width:110px;height:110px;right:-45px;top:-50px;border-radius:50%;background:rgba(139,92,246,.16);filter:blur(4px);pointer-events:none}
.stat:nth-child(2):before{background:rgba(34,211,238,.12)}
.stat:after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(105deg,transparent 28%,rgba(255,255,255,.055) 45%,transparent 62%);transform:translateX(-120%);animation:magic-card-shimmer 8s ease-in-out infinite}
.stat:nth-child(2):after{animation-delay:1.3s}
.stat-label{position:relative;display:block;margin-bottom:13px;color:var(--muted);font-size:11px;font-weight:750}
.stat strong{position:relative;display:block;color:#fff;font-size:23px;line-height:1.2;letter-spacing:-.025em}
.stat small{position:relative;display:block;margin-top:7px;color:#64748b;font-size:11px}

.workspace,.result,.my-routes{
  border:1px solid transparent;
  background:linear-gradient(rgba(8,13,27,.86),rgba(8,13,27,.86)) padding-box,linear-gradient(135deg,rgba(167,139,250,.22),rgba(148,163,184,.09) 48%,rgba(34,211,238,.18)) border-box;
  box-shadow:var(--shadow),inset 0 1px rgba(255,255,255,.025);
  backdrop-filter:blur(20px) saturate(120%);
}
.workspace{position:relative;display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,.9fr);grid-template-rows:auto auto 1fr;gap:0 30px;padding:28px;border-radius:var(--radius);overflow:hidden}
.workspace:before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 4% 0%,rgba(139,92,246,.09),transparent 25%),radial-gradient(circle at 100% 100%,rgba(34,211,238,.055),transparent 28%)}
.workspace:after{content:"";position:absolute;width:220px;height:1px;right:8%;top:0;border-radius:50%;background:linear-gradient(90deg,transparent,var(--cyan),transparent);box-shadow:0 0 20px rgba(34,211,238,.7);animation:magic-edge 6s ease-in-out infinite;pointer-events:none}
.workspace>*{position:relative;z-index:1}
.workspace>.section-line,.workspace>.nodes,.workspace>.tools{grid-column:1}
.workspace>.route-form{grid-column:2;grid-row:1/4}
.section-line{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:17px}
.section-line h2{margin:0;color:#f1f5f9;font-size:17px;letter-spacing:-.015em}
.section-line>span{color:#64748b;font-size:12px}
.nodes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;max-width:none;margin:0}
.node-card{
  position:relative;
  display:flex;
  flex-direction:column;
  justify-content:center;
  gap:7px;
  min-height:108px;
  padding:14px 13px;
  overflow:hidden;
  border:1px solid rgba(148,163,184,.14);
  border-radius:16px;
  background:linear-gradient(145deg,rgba(18,25,45,.84),rgba(10,15,28,.68));
  box-shadow:inset 0 1px rgba(255,255,255,.025);
  color:var(--ink);
  text-align:left;
  cursor:pointer;
  transition:transform .2s,border-color .2s,background .2s,box-shadow .2s;
}
.node-card:before{content:"";position:absolute;inset:-1px;opacity:0;pointer-events:none;background:radial-gradient(circle at 15% 5%,rgba(139,92,246,.2),transparent 45%);transition:opacity .2s}
.node-card:after{content:"";position:absolute;width:8px;height:8px;right:12px;top:12px;border:1px solid #475569;border-radius:50%;background:#1e293b;box-shadow:0 0 0 4px rgba(71,85,105,.08)}
.node-card:hover{transform:translateY(-3px);border-color:rgba(167,139,250,.32);background:linear-gradient(145deg,rgba(25,33,57,.9),rgba(11,17,32,.78));box-shadow:0 16px 34px rgba(0,0,0,.24),0 0 22px rgba(139,92,246,.07)}
.node-card:hover:before{opacity:1}
.node-card.selected{border-color:rgba(34,211,238,.55);background:linear-gradient(145deg,rgba(17,30,51,.94),rgba(10,22,38,.86));box-shadow:0 0 0 1px rgba(34,211,238,.16),0 14px 36px rgba(0,0,0,.3),0 0 28px rgba(34,211,238,.11)}
.node-card.selected:before{opacity:1;background:radial-gradient(circle at 15% 5%,rgba(34,211,238,.18),transparent 46%)}
.node-card.selected:after{border-color:var(--cyan);background:var(--cyan);box-shadow:0 0 0 4px rgba(34,211,238,.1),0 0 14px rgba(34,211,238,.75)}
.node-title,.node-name,.node-meta{position:relative;z-index:1}
.node-title{display:flex;align-items:center;justify-content:flex-start;min-height:24px}
.node-flag{display:grid;place-items:center}
.flag-icon{display:block;width:32px;height:21px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.34)}
.node-name{overflow:hidden;color:#e2e8f0;font-size:12px;font-weight:800;white-space:nowrap;text-overflow:ellipsis}
.node-meta{display:flex;align-items:center;justify-content:space-between;gap:7px}
.node-card small{overflow:hidden;color:#64748b;font-size:10px;white-space:nowrap;text-overflow:ellipsis}
.latency{flex:0 0 auto;color:#a5b4fc;font-size:10px;font-weight:800}
.tools{display:flex;align-items:center;justify-content:space-between;align-self:end;gap:12px;margin-top:16px}
.tools .hint{margin:0;text-align:right}

.route-form{
  position:relative;
  padding:22px;
  border:1px solid rgba(148,163,184,.14);
  border-radius:18px;
  background:linear-gradient(160deg,rgba(20,28,50,.75),rgba(11,17,32,.72));
  box-shadow:inset 0 1px rgba(255,255,255,.025),0 18px 50px rgba(0,0,0,.18);
}
.route-form:before{content:"创建访问线路";display:block;margin-bottom:4px;color:#f1f5f9;font-size:17px;font-weight:850}
.route-form:after{content:"";position:absolute;width:90px;height:90px;right:-35px;bottom:-40px;border-radius:50%;background:rgba(139,92,246,.1);filter:blur(6px);pointer-events:none}
.route-form>*{position:relative;z-index:1}
.route-form>label:first-of-type{margin-top:20px}
.route-note-field{margin-top:14px}
.route-form .hint{margin:14px 0 0}
label{display:grid;gap:8px;margin:0;color:var(--muted-strong);font-size:13px;font-weight:750}
input{
  width:100%;
  min-width:0;
  height:46px;
  padding:0 14px;
  outline:0;
  border:1px solid rgba(148,163,184,.18);
  border-radius:12px;
  background:rgba(3,7,18,.66);
  box-shadow:inset 0 1px rgba(255,255,255,.02);
  color:#f8fafc;
  font:inherit;
  transition:border-color .18s,box-shadow .18s,background .18s;
}
input::placeholder{color:#475569}
input:hover{border-color:rgba(148,163,184,.32)}
input:focus{border-color:rgba(34,211,238,.55);background:rgba(4,10,23,.88);box-shadow:0 0 0 4px rgba(34,211,238,.09),0 0 24px rgba(34,211,238,.06)}
.row{display:flex;gap:10px}
button{
  position:relative;
  min-height:42px;
  height:auto;
  padding:9px 16px;
  overflow:hidden;
  border:1px solid rgba(167,139,250,.3);
  border-radius:12px;
  background:linear-gradient(110deg,#6d28d9,#7c3aed 42%,#2563eb);
  box-shadow:0 12px 28px rgba(109,40,217,.25),inset 0 1px rgba(255,255,255,.13);
  color:#fff;
  font:inherit;
  font-size:12px;
  font-weight:850;
  cursor:pointer;
  transition:transform .18s,box-shadow .18s,border-color .18s,background .18s,color .18s;
}
button:not(.node-card):not(.secondary):not(.copy-route):not(.note-edit):not(.note-cancel):not(.delete-route):not(.logout):before{content:"";position:absolute;inset:-2px auto -2px -42%;width:34%;pointer-events:none;background:linear-gradient(100deg,transparent,rgba(255,255,255,.5),transparent);transform:skewX(-18deg);animation:magic-button-shimmer 3.8s ease-in-out infinite}
.row button{flex:0 0 auto;min-width:132px}
button:hover{transform:translateY(-2px);box-shadow:0 16px 34px rgba(109,40,217,.34),0 0 24px rgba(34,211,238,.08)}
button:active{transform:translateY(0)}
button:focus-visible,.account-actions a:focus-visible,.brand:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
button.secondary,button.copy-route,.route-note-form .note-cancel{
  border:1px solid rgba(148,163,184,.2);
  background:rgba(15,23,42,.72);
  box-shadow:none;
  color:#cbd5e1;
}
button.secondary:hover,button.copy-route:hover,.route-note-form .note-cancel:hover{border-color:rgba(34,211,238,.34);background:rgba(30,41,59,.9);box-shadow:0 10px 24px rgba(0,0,0,.2);color:#fff}
.tools button.secondary{min-height:38px;padding:7px 12px;font-size:11px}
button.copy-route{min-height:34px;margin:0;padding:6px 10px;font-size:11px}
.copy-field{display:flex;align-items:center;gap:9px}
.copy-field button.copy-route{height:46px;min-height:46px;margin:0;padding:0 15px;font-size:12px}
.hint{margin:10px 0 0;font-size:11px}

.result{position:relative;margin-top:18px;padding:22px 24px;overflow:hidden;border-radius:18px;background:linear-gradient(rgba(7,21,26,.9),rgba(7,21,26,.9)) padding-box,linear-gradient(135deg,rgba(52,211,153,.5),rgba(34,211,238,.15),rgba(148,163,184,.12)) border-box}
.result:after{content:"";position:absolute;width:180px;height:180px;right:-80px;top:-110px;border-radius:50%;background:rgba(52,211,153,.13);filter:blur(8px);pointer-events:none}
.result>*{position:relative;z-index:1}
.result .eyebrow{margin-bottom:14px;border-color:rgba(52,211,153,.25);background:rgba(52,211,153,.07);color:#a7f3d0}
.result .eyebrow:before{background:var(--emerald);box-shadow:0 0 12px rgba(52,211,153,.65)}
.result input{background:rgba(2,12,18,.72)}
.error{margin:18px 0 0;padding:14px 16px;border:1px solid rgba(251,113,133,.3);border-radius:14px;background:rgba(159,18,57,.12);box-shadow:0 14px 35px rgba(0,0,0,.18);color:#fda4af;font-size:12px}

.my-routes{position:relative;margin-top:18px;padding:25px;border-radius:var(--radius);overflow:hidden}
.my-routes:before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 100% 0%,rgba(34,211,238,.055),transparent 24%)}
.my-routes>*{position:relative;z-index:1}
.my-routes .section-line{margin-bottom:10px}
.routes-scroll{overflow-x:auto;padding:0 1px 4px;-webkit-overflow-scrolling:touch;scrollbar-color:#334155 transparent;scrollbar-width:thin}
.routes-scroll::-webkit-scrollbar{height:8px}.routes-scroll::-webkit-scrollbar-track{background:transparent}.routes-scroll::-webkit-scrollbar-thumb{border-radius:999px;background:#334155}
.my-routes table{width:100%;min-width:1080px;margin-top:8px;border-collapse:separate;border-spacing:0 8px;table-layout:fixed}
.my-routes th,.my-routes td{padding:14px 12px;text-align:left;vertical-align:middle}
.my-routes th{border:0;color:#64748b;font-size:10px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}
.my-routes td{border-top:1px solid rgba(148,163,184,.1);border-bottom:1px solid rgba(148,163,184,.1);background:rgba(15,23,42,.45);color:#cbd5e1;font-size:13px;line-height:1.55;transition:border-color .18s,background .18s}
.my-routes td:first-child{border-left:1px solid rgba(148,163,184,.1);border-radius:13px 0 0 13px}
.my-routes td:last-child{border-right:1px solid rgba(148,163,184,.1);border-radius:0 13px 13px 0}
.my-routes tbody tr:hover td{border-color:rgba(167,139,250,.2);background:rgba(25,33,57,.68)}
.my-routes tbody tr:last-child td{border-bottom:1px solid rgba(148,163,184,.1)}
.my-routes th:nth-child(1),.my-routes td:nth-child(1){width:21%}
.my-routes th:nth-child(2),.my-routes td:nth-child(2){width:27%}
.my-routes th:nth-child(3),.my-routes td:nth-child(3){width:11%}
.my-routes th:nth-child(4),.my-routes td:nth-child(4){width:16%}
.my-routes th:nth-child(5),.my-routes td:nth-child(5){width:13%}
.my-routes th:nth-child(6),.my-routes td:nth-child(6){width:12%}
.route-url{display:inline;max-width:none;color:#67e8f9;font-size:13px;line-height:1.55;overflow-wrap:anywhere;word-break:break-word}
.route-link-cell{display:flex;align-items:center;gap:8px;min-width:0}
.route-link-cell .route-url{flex:1;min-width:0}
.route-link-cell .copy-route{flex:0 0 auto}
.route-state{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border:1px solid rgba(52,211,153,.18);border-radius:999px;background:rgba(16,185,129,.1);color:#6ee7b7;font-size:11px;font-weight:800;white-space:nowrap}
.route-state:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}
.route-state.off{border-color:rgba(251,191,36,.17);background:rgba(245,158,11,.09);color:#fcd34d}
.route-state.error-state{border-color:rgba(251,113,133,.18);background:rgba(225,29,72,.09);color:#fda4af}
.route-note-cell{min-width:190px}
.route-note-view{display:inline-flex;align-items:center;gap:7px;max-width:100%;white-space:nowrap}
.route-note-text{overflow:hidden;color:#c4b5fd;font-size:13px;white-space:nowrap;text-overflow:ellipsis}
.route-note-text.empty{color:#64748b}
.route-note-form{display:none;align-items:center;gap:6px}
.route-note-form.is-open{display:flex}
.route-note-form input{width:145px;height:36px;padding:0 9px;font-size:12px}
.route-note-form button{height:34px;min-height:34px;padding:5px 9px;font-size:11px}
button.note-edit{display:inline-grid;place-items:center;width:30px;height:30px;min-height:30px;margin:0;padding:0;border:1px solid rgba(148,163,184,.16);border-radius:9px;background:rgba(15,23,42,.72);box-shadow:none;color:#a5b4fc;font-size:13px;line-height:1}
button.note-edit:hover{transform:translateY(-1px);border-color:rgba(167,139,250,.36);background:rgba(30,41,59,.9);box-shadow:none;color:#ddd6fe}
button.delete-route{min-height:34px;padding:6px 11px;border:1px solid rgba(251,113,133,.22);background:rgba(159,18,57,.12);box-shadow:none;color:#fda4af;font-size:11px}
button.delete-route:hover{border-color:rgba(251,113,133,.42);background:rgba(190,18,60,.18);box-shadow:0 8px 20px rgba(159,18,57,.14);color:#fecdd3}
.route-error{display:inline-block;margin-top:6px;color:#fda4af;font-size:10px;line-height:1.45}

@keyframes magic-aurora{0%{transform:translate3d(-2%,-1%,0) scale(1)}50%{transform:translate3d(2%,2%,0) scale(1.05)}100%{transform:translate3d(0,-2%,0) scale(1.02)}}
@keyframes magic-grid{to{background-position:52px 52px}}
@keyframes magic-title{to{background-position:200% center}}
@keyframes magic-pulse{0%,100%{opacity:.72;box-shadow:0 0 0 4px rgba(52,211,153,.08)}50%{opacity:1;box-shadow:0 0 0 7px rgba(52,211,153,.03),0 0 14px rgba(52,211,153,.55)}}
@keyframes magic-card-shimmer{0%,64%{transform:translateX(-120%)}82%,100%{transform:translateX(120%)}}
@keyframes magic-button-shimmer{0%,52%{left:-42%}78%,100%{left:130%}}
@keyframes magic-edge{0%,100%{opacity:.25;transform:translateX(-70%)}50%{opacity:1;transform:translateX(70%)}}

@media(max-width:1020px){
  .hero{grid-template-columns:1fr;gap:28px}.hero-copy{max-width:760px}.hero-stats{max-width:520px}
  .workspace{grid-template-columns:1fr}.workspace>.section-line,.workspace>.nodes,.workspace>.tools,.workspace>.route-form{grid-column:1}.workspace>.route-form{grid-row:auto;margin-top:22px}
}
@media(max-width:760px){
  .app-shell{padding:12px 14px 48px}.topbar{position:relative;top:0;align-items:flex-start;flex-direction:column;margin-bottom:40px;padding:12px}
  .account-actions{width:100%;flex-wrap:wrap;justify-content:flex-start}.live{order:-1;width:100%;justify-content:center}.account-actions>a,.account-actions button.logout{min-height:44px}
  .hero{gap:24px;padding:0 2px}.hero h1{font-size:clamp(39px,11vw,54px)}.hero-stats{max-width:none}.stat{min-height:112px;padding:17px}
  .workspace,.my-routes{padding:18px;border-radius:18px}.route-form{padding:18px}.nodes{gap:8px}.node-card{min-height:102px;padding:12px 10px}
  .tools{align-items:flex-start;flex-direction:column}.tools .hint{text-align:left}.section-line{align-items:flex-start;flex-direction:column;gap:5px}
  .row{flex-direction:column}.row button{width:100%;min-height:46px}.copy-field{align-items:stretch}.copy-field input{height:auto;min-height:46px}.copy-field button.copy-route{height:auto;min-height:46px}
  .my-routes{padding-right:0}.routes-scroll{padding-right:18px}.my-routes table{min-width:1040px}
}
@media(max-width:520px){
  .brand-copy small{display:none}.hero h1 br{display:none}.subtitle{font-size:14px}.hero-stats{grid-template-columns:1fr 1fr;gap:8px}.stat{min-height:104px;padding:15px 13px}.stat strong{font-size:19px}.stat small{font-size:10px}
  .nodes{grid-template-columns:repeat(2,minmax(0,1fr))}.node-card{min-height:98px}.flag-icon{width:29px;height:19px}
  .tools button.secondary{min-height:44px}.route-note-form input{width:132px}.route-note-form button,button.note-edit,button.delete-route{min-height:38px}
}
@media(max-width:360px){
  .app-shell{padding-inline:10px}.topbar{border-radius:15px}.account-actions{gap:6px}.account-actions>a,.account-actions button.logout{padding-inline:9px;font-size:11px}
  .hero h1{font-size:36px}.hero-stats{grid-template-columns:1fr}.workspace,.my-routes{padding:15px}.my-routes{padding-right:0}.routes-scroll{padding-right:15px}
}
@media(prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  body:before,body:after,.hero h1 span,.live i,.stat:after,.workspace:after,button:before{animation:none!important}
  *,*:before,*:after{transition-duration:.01ms!important;transition-delay:0s!important}
}

/* The user dashboard opens in a calm light theme. The same surface tokens
   are overridden here so the dark Magic UI remains available as an explicit
   choice without changing the existing layout or interactions. */
body[data-theme='light']{
  color-scheme:light;
  --canvas:#f5f7fb;
  --surface:rgba(255,255,255,.84);
  --surface-strong:rgba(255,255,255,.96);
  --surface-soft:rgba(246,248,252,.9);
  --line:rgba(160,174,198,.36);
  --line-strong:rgba(132,149,180,.5);
  --ink:#172033;
  --muted:#667085;
  --muted-strong:#52627a;
  --shadow:0 24px 70px rgba(75,98,142,.14);
  background:
    radial-gradient(circle at 9% -8%,rgba(159,178,255,.28),transparent 34%),
    radial-gradient(circle at 94% 5%,rgba(129,221,213,.22),transparent 30%),
    linear-gradient(150deg,#f9fbff 0%,#f5f7fb 48%,#eef7f7 100%);
  color:var(--ink);
}
body[data-theme='light']:before{
  background:
    radial-gradient(circle at 26% 28%,rgba(129,153,255,.16),transparent 19%),
    radial-gradient(circle at 72% 22%,rgba(56,189,248,.1),transparent 18%),
    radial-gradient(circle at 55% 76%,rgba(45,212,191,.09),transparent 22%);
}
body[data-theme='light']:after{
  opacity:.3;
  background-image:
    linear-gradient(rgba(100,116,139,.075) 1px,transparent 1px),
    linear-gradient(90deg,rgba(100,116,139,.075) 1px,transparent 1px);
}
body[data-theme='light'] .topbar{
  border-color:rgba(192,205,226,.74);
  background:rgba(255,255,255,.78);
  box-shadow:0 18px 55px rgba(75,98,142,.12),inset 0 1px rgba(255,255,255,.8);
}
body[data-theme='light'] .brand{color:#24334d}
body[data-theme='light'] .brand-mark{
  background:linear-gradient(145deg,#fff,#edf3ff) padding-box,linear-gradient(135deg,#9aaef1,#75cfd1) border-box;
  box-shadow:0 8px 20px rgba(96,121,183,.14);
  color:#6079b7;
}
body[data-theme='light'] .brand-copy small{color:#8490a4}
body[data-theme='light'] .account-actions>a,
body[data-theme='light'] .account-actions button.logout,
body[data-theme='light'] .theme-toggle{
  border-color:#dce3ef;
  background:rgba(255,255,255,.84);
  color:#52627a;
}
body[data-theme='light'] .account-actions>a:hover,
body[data-theme='light'] .account-actions button.logout:hover,
body[data-theme='light'] .theme-toggle:hover{
  border-color:#a9b9dd;
  background:#f7f9ff;
  color:#304a7d;
  box-shadow:0 8px 20px rgba(75,98,142,.1);
}
body[data-theme='light'] .account-actions .admin-link{border-color:#bfe9d1;background:#eef9f4;color:#218451}
body[data-theme='light'] .live{border-color:rgba(192,205,226,.82);background:rgba(255,255,255,.78);color:#64748b;box-shadow:0 5px 16px rgba(73,99,143,.06)}
body[data-theme='light'] .hero h1{color:#253452}
body[data-theme='light'] .hero h1 span{background:linear-gradient(100deg,#667fd0 4%,#159eaf 48%,#667fd0 96%);background-size:200% auto;background-clip:text;-webkit-background-clip:text}
body[data-theme='light'] .eyebrow{border-color:rgba(99,102,241,.18);background:rgba(99,102,241,.06);color:#5966a5}
body[data-theme='light'] .subtitle,
body[data-theme='light'] .hint,
body[data-theme='light'] .section-line>span{color:#71809a}
body[data-theme='light'] .stat{
  background:linear-gradient(rgba(255,255,255,.9),rgba(255,255,255,.9)) padding-box,linear-gradient(145deg,rgba(126,145,226,.34),rgba(72,190,193,.12),rgba(148,163,184,.24)) border-box;
  box-shadow:0 20px 55px rgba(75,98,142,.12),inset 0 1px rgba(255,255,255,.9);
}
body[data-theme='light'] .stat strong{color:#253452}
body[data-theme='light'] .stat small,
body[data-theme='light'] .stat-label{color:#7f8aa0}
body[data-theme='light'] .workspace,
body[data-theme='light'] .result,
body[data-theme='light'] .my-routes{
  background:linear-gradient(rgba(255,255,255,.86),rgba(255,255,255,.86)) padding-box,linear-gradient(135deg,rgba(126,145,226,.28),rgba(148,163,184,.18) 48%,rgba(72,190,193,.22)) border-box;
  box-shadow:var(--shadow),inset 0 1px rgba(255,255,255,.9);
}
body[data-theme='light'] .workspace:before{background:radial-gradient(circle at 4% 0%,rgba(126,145,226,.1),transparent 25%),radial-gradient(circle at 100% 100%,rgba(72,190,193,.08),transparent 28%)}
body[data-theme='light'] .section-line h2{color:#405572}
body[data-theme='light'] .node-card{
  border-color:#dfe6f0;
  background:linear-gradient(145deg,rgba(255,255,255,.96),rgba(246,248,252,.9));
  color:#1f2937;
  box-shadow:inset 0 1px rgba(255,255,255,.9);
}
body[data-theme='light'] .node-card:after{border-color:#cbd5e1;background:#e8edf5;box-shadow:0 0 0 4px rgba(148,163,184,.1)}
body[data-theme='light'] .node-card:hover{border-color:#aebbd1;background:linear-gradient(145deg,#fff,#f5f8fd);box-shadow:0 16px 34px rgba(75,98,142,.14)}
body[data-theme='light'] .node-card.selected{border-color:#6478d9;background:#f7f8ff;box-shadow:0 0 0 3px rgba(100,120,217,.13),0 14px 30px rgba(75,98,142,.12)}
body[data-theme='light'] .node-card.selected:after{border-color:#6478d9;background:#6478d9;box-shadow:0 0 0 4px rgba(100,120,217,.12),0 0 14px rgba(100,120,217,.38)}
body[data-theme='light'] .node-name{color:#34435d}
body[data-theme='light'] .node-card small{color:#718096}
body[data-theme='light'] .latency{color:#536db0}
body[data-theme='light'] .route-form{border-color:#dce4ef;background:linear-gradient(160deg,rgba(248,250,253,.94),rgba(242,246,252,.88));box-shadow:inset 0 1px rgba(255,255,255,.95),0 18px 50px rgba(75,98,142,.1)}
body[data-theme='light'] .route-form:before{color:#26364f}
body[data-theme='light'] label{color:#53627a}
body[data-theme='light'] input{border-color:#dbe3ee;background:rgba(255,255,255,.92);color:#25344e;box-shadow:inset 0 1px rgba(255,255,255,.8)}
body[data-theme='light'] input::placeholder{color:#a5b0c1}
body[data-theme='light'] input:focus{border-color:#8295d9;background:#fff;box-shadow:0 0 0 4px rgba(99,102,241,.12)}
body[data-theme='light'] button.secondary,
body[data-theme='light'] button.copy-route,
body[data-theme='light'] .route-note-form .note-cancel,
body[data-theme='light'] button.note-edit{
  border-color:#d7e0ef;
  background:#f9fbff;
  color:#526b9f;
}
body[data-theme='light'] button.secondary:hover,
body[data-theme='light'] button.copy-route:hover,
body[data-theme='light'] .route-note-form .note-cancel:hover,
body[data-theme='light'] button.note-edit:hover{border-color:#b7c7e7;background:#eef3fb;color:#37558f;box-shadow:0 8px 18px rgba(75,98,142,.1)}
body[data-theme='light'] .result{border-color:#c8d8f0;background:linear-gradient(rgba(246,250,255,.9),rgba(246,250,255,.9)) padding-box,linear-gradient(135deg,rgba(99,164,214,.38),rgba(72,190,193,.16),rgba(148,163,184,.16)) border-box}
body[data-theme='light'] .result input{background:#fff}
body[data-theme='light'] .error{border-color:#f2c8d0;background:#fff5f6;color:#b85f6d;box-shadow:0 14px 35px rgba(75,98,142,.08)}
body[data-theme='light'] .my-routes td{border-color:#e1e7f0;background:rgba(255,255,255,.72);color:#3a465c}
body[data-theme='light'] .my-routes th{color:#7a879c}
body[data-theme='light'] .my-routes tbody tr:hover td{border-color:#c6d2eb;background:rgba(247,249,255,.94)}
body[data-theme='light'] .route-url{color:#375fb0}
body[data-theme='light'] .route-note-text{color:#526b9f}
body[data-theme='light'] .route-note-text.empty{color:#97a4b7}
body[data-theme='light'] .route-state{border-color:#bfe9d1;background:#eaf8f0;color:#218451}
body[data-theme='light'] .route-state.off{border-color:#f1d99c;background:#fff8e7;color:#a46b13}
body[data-theme='light'] .route-state.error-state,
body[data-theme='light'] .route-error{color:#b85f6d}
body[data-theme='light'] .route-state.error-state{border-color:#f2c8d0;background:#fff5f6}
body[data-theme='light'] button.delete-route{border-color:#f2c8d0;background:#fff5f6;color:#b85f6d}
body[data-theme='light'] button.delete-route:hover{border-color:#e8aeb9;background:#ffedf0;color:#9f4252;box-shadow:0 8px 18px rgba(190,80,100,.1)}
.theme-toggle{display:inline-grid;place-items:center;width:40px;height:40px;min-height:40px;margin:0;padding:0;border:1px solid var(--line);border-radius:11px;background:rgba(15,23,42,.62);box-shadow:none;color:var(--muted);font-size:17px;line-height:1;animation:none}
.theme-toggle:before{display:none!important}
.theme-toggle:hover{border-color:rgba(167,139,250,.4);background:rgba(30,41,59,.78);color:#fff;box-shadow:none;transform:translateY(-1px)}
body[data-theme='light'] .theme-toggle{color:#526b9f}
body[data-theme='light'] .theme-toggle:hover{color:#304a7d}
@media(max-width:760px){.theme-toggle{width:44px;height:44px;min-height:44px}}
"""


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
            checks_section = "<p class='hint'>线路已下发到所选节点。可点击上方“重新测试”重新检测各节点网络延迟。</p>"
            result_html = f"""
            <section class="result-card">
                <div class="result-header">
                    <span class="badge-success">✓ 线路已就绪</span>
                    <span class="hint">已分配节点域名：{html.escape(host)}</span>
                </div>
                <label>完整 HTTPS 访问地址</label>
                <div class="copy-field">
                    <input readonly value="{html.escape(https_url, quote=True)}">
                    <button type="button" class="copy-route btn-copy" data-copy="{html.escape(https_url, quote=True)}">复制</button>
                </div>
                {checks_section}
            </section>
            """
        except Exception as exc:
            result_html = f"<div class='error-banner'><span>⚠</span><span>{html.escape(str(exc))}。示例：https://emby.example.com</span></div>"

    node_cards_parts = []
    for node in nodes:
        meta_label = node["code"].lower() if node["is_local"] else (node["country_name"] or node["health"])
        node_cards_parts.append(
            f"<button type='button' title='{html.escape(node['name'], quote=True)}' aria-pressed={'true' if node['id'] == selected_node_id else 'false'} class='node-card{' selected' if node['id'] == selected_node_id else ''}' data-node-id='{node['id']}'>"
            f"<div class='node-card-flag'>{node['flag_markup']}</div>"
            f"<span class='node-card-name'>{html.escape(node['name'])}</span>"
            f"<div class='node-card-footer'><span class='node-card-loc'>{html.escape(meta_label)}</span><span class='latency' data-latency='{node['id']}'>待测试</span></div>"
            f"</button>"
        )
    node_cards = "".join(node_cards_parts) or "<p class='hint'>暂时没有可用节点。</p>"
    nodes_json = json.dumps(nodes, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    route_rows = []
    for route in panel.user_routes(int(user["id"])):
        state = "已暂停" if route["suspended_by_owner"] else ("已下发" if route["deployed"] else "部署失败")
        state_class = "state-paused" if route["suspended_by_owner"] else ("state-active" if route["deployed"] else "state-failed")
        error = f"<div class='route-error'>{html.escape(route['last_error'])}</div>" if route["last_error"] else ""
        note = str(route["notes"] or "")
        note_display = html.escape(note) if note else "未填写"
        note_class = "" if note else " empty"
        note_editor = f"<td class='route-note-cell'><div class='route-note-view'><span class='route-note-text{note_class}'>{note_display}</span><button type='button' class='note-edit' title='编辑备注' aria-label='编辑备注'>✎</button></div><form class='route-note-form' method='post' action='/my/routes/{route['id']}/note'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><input name='notes' maxlength='500' value='{html.escape(note, quote=True)}' placeholder='线路备注'><button type='submit' class='btn-save'>保存</button><button type='button' class='note-cancel'>取消</button></form></td>"
        route_rows.append(
            f"<tr>"
            f"<td><span class='route-url origin-url'>{html.escape(route['origin'])}</span></td>"
            f"<td><div class='route-link-cell'><span class='route-url public-url'>{html.escape(route['public_url'])}</span><button type='button' class='copy-route' data-copy='{html.escape(route['public_url'], quote=True)}'>复制</button></div></td>"
            f"<td><span class='node-tag'>{html.escape(route['node_name'])}</span></td>"
            f"{note_editor}"
            f"<td><span class='route-state {state_class}'>{state}</span>{error}</td>"
            f"<td class='action-cell'><form method='post' action='/my/routes/{route['id']}/delete'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='delete-route' title='删除此线路'>删除</button></form></td>"
            f"</tr>"
        )
    used_routes, route_quota = panel.user_route_usage(int(user["id"]))
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='empty-table'>你还没有创建线路，在上方输入源站地址即可快速生成。</td></tr>"
    expiry_label = panel._display_expiry(user["expires_at"])
    admin_link = "<a class='action-pill admin-pill' href='/_admin'>⚡ 管理后台</a>" if int(user["is_admin"] or 0) else ""
    csp_nonce = secrets.token_urlsafe(16)

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emby Relay · 节点与线路管理</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<link rel="shortcut icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<style>
:root{{
  --bg-page:#f8fafc;
  --bg-glow1:rgba(99,102,241,0.08);
  --bg-glow2:rgba(34,211,238,0.06);
  --panel:rgba(255,255,255,0.85);
  --panel-card:#ffffff;
  --panel-card-hover:#fafcff;
  --border:rgba(226,232,240,0.85);
  --border-strong:rgba(203,213,225,0.9);
  --text-main:#0f172a;
  --text-muted:#475569;
  --text-faint:#94a3b8;
  --primary:#6366f1;
  --primary-hover:#4f46e5;
  --primary-light:rgba(99,102,241,0.08);
  --accent:#06b6d4;
  --success:#10b981;
  --success-bg:rgba(16,185,129,0.1);
  --danger:#ef4444;
  --danger-bg:rgba(239,68,68,0.08);
  --shadow-sm:0 1px 2px rgba(0,0,0,0.04);
  --shadow-md:0 10px 30px -4px rgba(15,23,42,0.06), 0 4px 12px -2px rgba(15,23,42,0.03);
  --shadow-lg:0 20px 45px -10px rgba(15,23,42,0.08);
  --card-border-selected:#6366f1;
  --card-glow-selected:rgba(99,102,241,0.18);
}}
body[data-theme='dark']{{
  --bg-page:#06080f;
  --bg-glow1:rgba(139,92,246,0.18);
  --bg-glow2:rgba(34,211,238,0.12);
  --panel:rgba(15,23,42,0.78);
  --panel-card:rgba(20,28,48,0.85);
  --panel-card-hover:rgba(30,41,69,0.9);
  --border:rgba(255,255,255,0.09);
  --border-strong:rgba(255,255,255,0.16);
  --text-main:#f8fafc;
  --text-muted:#94a3b8;
  --text-faint:#64748b;
  --primary:#818cf8;
  --primary-hover:#6366f1;
  --primary-light:rgba(129,140,248,0.15);
  --accent:#22d3ee;
  --success:#34d399;
  --success-bg:rgba(52,211,153,0.15);
  --danger:#f87171;
  --danger-bg:rgba(248,113,113,0.15);
  --shadow-sm:0 1px 2px rgba(0,0,0,0.3);
  --shadow-md:0 10px 30px -4px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06);
  --shadow-lg:0 25px 60px -10px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,255,255,0.08);
  --card-border-selected:#818cf8;
  --card-glow-selected:rgba(129,140,248,0.3);
}}
*{{box-sizing:border-box}}
html{{min-height:100%;background:var(--bg-page)}}
body{{
  position:relative;
  margin:0;
  min-height:100vh;
  overflow-x:hidden;
  background:radial-gradient(ellipse 80% 50% at 50% -10%,var(--bg-glow1),transparent 65%),
             radial-gradient(ellipse 60% 40% at 90% 90%,var(--bg-glow2),transparent 60%),
             var(--bg-page);
  color:var(--text-main);
  font:14px/1.6 Inter,"PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  transition:background .25s ease,color .25s ease;
}}
body:before{{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  opacity:0.4;
  background-image:linear-gradient(rgba(148,163,184,0.06) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(148,163,184,0.06) 1px,transparent 1px);
  background-size:32px 32px;
}}
main{{
  position:relative;
  z-index:1;
  max-width:1040px;
  margin:0 auto;
  padding:24px 20px 64px;
}}
/* TopBar */
.topbar{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  margin-bottom:36px;
  padding:12px 18px;
  border:1px solid var(--border);
  border-radius:18px;
  background:var(--panel);
  box-shadow:var(--shadow-md);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
}}
.brand{{
  display:flex;
  align-items:center;
  gap:12px;
  text-decoration:none;
}}
.brand-icon{{
  display:grid;
  place-items:center;
  width:36px;
  height:36px;
  border:1px solid rgba(196,181,253,0.3);
  border-radius:11px;
  background:linear-gradient(135deg,rgba(99,102,241,0.2),rgba(34,211,238,0.1));
  box-shadow:inset 0 1px rgba(255,255,255,0.2),0 0 16px rgba(99,102,241,0.15);
  color:#a78bfa;
  font-size:16px;
}}
.brand-title{{
  display:flex;
  flex-direction:column;
  line-height:1.2;
}}
.brand-title strong{{
  font-size:16px;
  font-weight:800;
  letter-spacing:-0.02em;
  background:linear-gradient(90deg,var(--text-main),var(--primary));
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}}
.brand-title small{{
  margin-top:2px;
  color:var(--text-faint);
  font-size:11px;
  font-weight:600;
  letter-spacing:0.02em;
}}
.topbar-right{{
  display:flex;
  align-items:center;
  gap:10px;
  flex-wrap:wrap;
}}
.user-pills{{
  display:flex;
  align-items:center;
  gap:8px;
}}
.pill{{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:5px 11px;
  border:1px solid var(--border);
  border-radius:999px;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:12px;
  font-weight:600;
  box-shadow:var(--shadow-sm);
}}
.pill-quota b{{
  color:var(--primary);
}}
.pill-live i{{
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--success);
  box-shadow:0 0 0 3px var(--success-bg);
}}
.action-pill{{
  display:inline-flex;
  align-items:center;
  gap:5px;
  height:32px;
  padding:0 12px;
  border:1px solid var(--border);
  border-radius:999px;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:12px;
  font-weight:650;
  text-decoration:none;
  cursor:pointer;
  transition:all .18s ease;
}}
.action-pill:hover{{
  border-color:var(--primary);
  color:var(--primary);
  background:var(--primary-light);
}}
.admin-pill{{
  border-color:rgba(139,92,246,0.3);
  color:var(--primary);
}}
button.theme-toggle{{
  width:34px;
  height:34px;
  padding:0;
  display:grid;
  place-items:center;
  border:1px solid var(--border);
  border-radius:50%;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:15px;
  cursor:pointer;
  transition:all .18s ease;
}}
button.theme-toggle:hover{{
  border-color:var(--primary);
  color:var(--primary);
  transform:scale(1.05);
}}
button.logout-btn{{
  height:32px;
  padding:0 12px;
  border:1px solid var(--border);
  border-radius:999px;
  background:transparent;
  color:var(--text-faint);
  font-size:12px;
  font-weight:600;
  cursor:pointer;
  transition:all .18s ease;
}}
button.logout-btn:hover{{
  border-color:var(--danger);
  color:var(--danger);
  background:var(--danger-bg);
}}
/* Hero Header */
.hero{{
  text-align:center;
  margin:20px auto 32px;
  max-width:680px;
}}
.hero-tag{{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:4px 12px;
  margin-bottom:14px;
  border:1px solid var(--border);
  border-radius:999px;
  background:var(--panel);
  color:var(--primary);
  font-size:11px;
  font-weight:700;
  letter-spacing:0.04em;
  text-transform:uppercase;
  box-shadow:var(--shadow-sm);
}}
.hero h1{{
  margin:0 0 10px;
  color:var(--text-main);
  font-size:clamp(26px,4vw,38px);
  font-weight:800;
  line-height:1.2;
  letter-spacing:-0.035em;
}}
.hero h1 span{{
  background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 50%,#06b6d4 100%);
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}}
.hero p{{
  margin:0 auto;
  color:var(--text-muted);
  font-size:14px;
  line-height:1.6;
  max-width:540px;
}}
/* Section Panel */
.panel-box{{
  position:relative;
  margin-top:24px;
  padding:26px 28px;
  border:1px solid var(--border);
  border-radius:24px;
  background:var(--panel);
  box-shadow:var(--shadow-md);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
}}
.section-header{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  margin-bottom:18px;
}}
.section-header h2{{
  margin:0;
  color:var(--text-main);
  font-size:16px;
  font-weight:750;
  letter-spacing:-0.01em;
}}
.section-header span{{
  color:var(--text-faint);
  font-size:12px;
}}
/* Node Cards */
.nodes-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(148px,1fr));
  gap:12px;
  margin-bottom:18px;
}}
.node-card{{
  position:relative;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:space-between;
  min-height:92px;
  padding:12px 10px 10px;
  text-align:center;
  border:1.5px solid var(--border);
  border-radius:16px;
  background:var(--panel-card);
  cursor:pointer;
  transition:all .18s cubic-bezier(0.4,0,0.2,1);
  box-shadow:var(--shadow-sm);
}}
.node-card:hover{{
  border-color:var(--border-strong);
  background:var(--panel-card-hover);
  transform:translateY(-2px);
  box-shadow:var(--shadow-md);
}}
.node-card.selected{{
  border-color:var(--card-border-selected);
  background:var(--panel-card);
  box-shadow:0 0 0 2px var(--card-border-selected),0 10px 24px -4px var(--card-glow-selected);
  transform:translateY(-2px);
}}
.node-card.selected:after{{
  content:"✓";
  position:absolute;
  top:6px;
  right:7px;
  width:16px;
  height:16px;
  display:grid;
  place-items:center;
  border-radius:50%;
  background:var(--primary);
  color:#fff;
  font-size:10px;
  font-weight:800;
}}
.node-card-flag{{
  display:grid;
  place-items:center;
  min-height:22px;
}}
.flag-icon{{
  display:block;
  width:30px;
  height:20px;
  border-radius:3px;
  box-shadow:0 1px 4px rgba(0,0,0,0.15);
}}
.node-card-name{{
  display:block;
  margin:6px 0 4px;
  color:var(--text-main);
  font-size:12px;
  font-weight:750;
  line-height:1.3;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  max-width:100%;
}}
.node-card-footer{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  width:100%;
  gap:6px;
  padding-top:4px;
  border-top:1px dashed var(--border);
}}
.node-card-loc{{
  color:var(--text-faint);
  font-size:10px;
  font-weight:600;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
}}
.latency{{
  font-size:10px;
  font-weight:750;
  color:var(--text-faint);
  flex:0 0 auto;
}}
.latency.fast{{color:var(--success);}}
.latency.medium{{color:#f59e0b;}}
.latency.slow{{color:#ef4444;}}
.latency.error{{color:var(--danger);}}
/* Node Action bar */
.node-tools{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding-bottom:18px;
  border-bottom:1px solid var(--border);
  margin-bottom:20px;
}}
.btn-probe{{
  height:36px;
  padding:0 14px;
  border:1px solid var(--border);
  border-radius:10px;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:12px;
  font-weight:700;
  cursor:pointer;
  transition:all .18s ease;
}}
.btn-probe:hover{{
  border-color:var(--primary);
  color:var(--primary);
  background:var(--primary-light);
}}
/* Route Form */
.route-form label{{
  display:block;
  margin-bottom:8px;
  color:var(--text-main);
  font-size:13px;
  font-weight:700;
}}
.form-row{{
  display:flex;
  gap:10px;
}}
input{{
  width:100%;
  min-width:0;
  height:48px;
  padding:0 16px;
  outline:0;
  border:1px solid var(--border);
  border-radius:12px;
  background:var(--panel-card);
  color:var(--text-main);
  font:inherit;
  font-size:14px;
  box-shadow:var(--shadow-sm);
  transition:border-color .18s ease,box-shadow .18s ease,background .18s ease;
}}
input::placeholder{{
  color:var(--text-faint);
}}
input:hover{{
  border-color:var(--border-strong);
}}
input:focus{{
  border-color:var(--primary);
  box-shadow:0 0 0 3px var(--primary-light);
}}
.btn-generate{{
  flex:0 0 auto;
  height:48px;
  padding:0 24px;
  border:0;
  border-radius:12px;
  background:linear-gradient(135deg,#6366f1 0%,#7c3aed 50%,#06b6d4 100%);
  color:#fff;
  font:inherit;
  font-size:14px;
  font-weight:750;
  cursor:pointer;
  box-shadow:0 8px 24px -4px rgba(99,102,241,0.35);
  transition:all .18s ease;
}}
.btn-generate:hover{{
  transform:translateY(-1px);
  box-shadow:0 12px 28px -2px rgba(99,102,241,0.45);
}}
.btn-generate:active{{
  transform:translateY(0);
}}
.form-note-row{{
  margin-top:12px;
}}
.form-note-row input{{
  height:42px;
  font-size:13px;
}}
.form-hint{{
  margin:12px 0 0;
  color:var(--text-faint);
  font-size:12px;
  line-height:1.5;
}}
/* Result Section */
.result-card{{
  margin-top:20px;
  padding:22px 24px;
  border:1.5px solid rgba(16,185,129,0.35);
  border-radius:20px;
  background:var(--panel);
  box-shadow:0 12px 32px -4px rgba(16,185,129,0.12);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
}}
.result-header{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
  flex-wrap:wrap;
}}
.badge-success{{
  display:inline-flex;
  align-items:center;
  padding:4px 10px;
  border-radius:999px;
  background:var(--success-bg);
  color:var(--success);
  font-size:12px;
  font-weight:750;
}}
.copy-field{{
  display:flex;
  gap:10px;
  align-items:center;
  margin-top:8px;
}}
.copy-field input{{
  font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
  font-size:13px;
  font-weight:600;
  color:var(--primary);
  background:var(--panel-card);
}}
.btn-copy{{
  flex:0 0 auto;
  height:48px;
  padding:0 20px;
  border:1px solid var(--border);
  border-radius:12px;
  background:var(--panel-card);
  color:var(--text-main);
  font:inherit;
  font-size:13px;
  font-weight:700;
  cursor:pointer;
  transition:all .18s ease;
}}
.btn-copy:hover{{
  border-color:var(--primary);
  color:var(--primary);
  background:var(--primary-light);
}}
.error-banner{{
  display:flex;
  align-items:center;
  gap:10px;
  margin-top:20px;
  padding:14px 18px;
  border:1px solid rgba(239,68,68,0.3);
  border-radius:16px;
  background:var(--danger-bg);
  color:var(--danger);
  font-size:13px;
  font-weight:600;
}}
/* My Routes Table */
.routes-scroll{{
  overflow-x:auto;
  -webkit-overflow-scrolling:touch;
}}
table{{
  width:100%;
  min-width:760px;
  margin-top:10px;
  border-collapse:collapse;
}}
th{{
  padding:10px 12px;
  border-bottom:1.5px solid var(--border);
  color:var(--text-faint);
  font-size:12px;
  font-weight:700;
  text-align:left;
}}
td{{
  padding:12px 12px;
  border-bottom:1px solid var(--border);
  color:var(--text-muted);
  font-size:13px;
  vertical-align:middle;
}}
tr:last-child td{{
  border-bottom:0;
}}
tbody tr:hover td{{
  background:var(--primary-light);
}}
.route-url{{
  display:inline-block;
  max-width:230px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
  font-size:12px;
  font-weight:600;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  vertical-align:middle;
}}
.origin-url{{
  color:var(--text-muted);
}}
.public-url{{
  color:var(--primary);
}}
.route-link-cell{{
  display:flex;
  align-items:center;
  gap:8px;
}}
button.copy-route{{
  flex:0 0 auto;
  height:26px;
  padding:0 8px;
  border:1px solid var(--border);
  border-radius:6px;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:11px;
  font-weight:600;
  cursor:pointer;
  transition:all .18s ease;
}}
button.copy-route:hover{{
  border-color:var(--primary);
  color:var(--primary);
  background:var(--primary-light);
}}
.node-tag{{
  display:inline-block;
  padding:3px 8px;
  border-radius:6px;
  background:var(--panel-card);
  border:1px solid var(--border);
  color:var(--text-main);
  font-size:11px;
  font-weight:700;
}}
.route-state{{
  display:inline-flex;
  align-items:center;
  gap:5px;
  padding:3px 9px;
  border-radius:999px;
  font-size:11px;
  font-weight:700;
}}
.state-active{{
  background:var(--success-bg);
  color:var(--success);
}}
.state-failed{{
  background:var(--danger-bg);
  color:var(--danger);
}}
.state-paused{{
  background:rgba(148,163,184,0.12);
  color:var(--text-faint);
}}
.route-error{{
  margin-top:4px;
  color:var(--danger);
  font-size:11px;
}}
.route-note-cell{{
  min-width:140px;
}}
.route-note-view{{
  display:inline-flex;
  align-items:center;
  gap:6px;
}}
.route-note-text{{
  max-width:150px;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  color:var(--text-main);
  font-size:12px;
}}
.route-note-text.empty{{
  color:var(--text-faint);
}}
button.note-edit{{
  display:grid;
  place-items:center;
  width:22px;
  height:22px;
  padding:0;
  border:1px solid var(--border);
  border-radius:6px;
  background:var(--panel-card);
  color:var(--text-faint);
  font-size:11px;
  cursor:pointer;
  transition:all .18s ease;
}}
button.note-edit:hover{{
  border-color:var(--primary);
  color:var(--primary);
}}
.route-note-form{{
  display:none;
  align-items:center;
  gap:5px;
}}
.route-note-form.is-open{{
  display:flex;
}}
.route-note-form input{{
  width:130px;
  height:30px;
  padding:0 8px;
  font-size:12px;
  border-radius:6px;
}}
.btn-save{{
  height:30px;
  padding:0 9px;
  border:0;
  border-radius:6px;
  background:var(--primary);
  color:#fff;
  font-size:11px;
  font-weight:700;
  cursor:pointer;
}}
.note-cancel{{
  height:30px;
  padding:0 8px;
  border:1px solid var(--border);
  border-radius:6px;
  background:var(--panel-card);
  color:var(--text-muted);
  font-size:11px;
  cursor:pointer;
}}
button.delete-route{{
  height:28px;
  padding:0 10px;
  border:1px solid rgba(239,68,68,0.25);
  border-radius:8px;
  background:var(--danger-bg);
  color:var(--danger);
  font-size:11px;
  font-weight:700;
  cursor:pointer;
  transition:all .18s ease;
}}
button.delete-route:hover{{
  border-color:var(--danger);
  background:var(--danger);
  color:#fff;
}}
.empty-table{{
  padding:32px 16px;
  text-align:center;
  color:var(--text-faint);
  font-size:13px;
}}
@media(max-width:768px){{
  main{{padding:16px 14px 48px;}}
  .topbar{{flex-direction:column;align-items:flex-start;gap:12px;padding:14px;}}
  .topbar-right{{width:100%;justify-content:space-between;}}
  .panel-box{{padding:18px 16px;border-radius:20px;}}
  .form-row{{flex-direction:column;}}
  .btn-generate{{width:100%;}}
  .nodes-grid{{grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;}}
  .node-card{{min-height:82px;padding:10px 8px 8px;}}
}}
</style>
</head>
<body data-theme="light">
<main>
  <!-- TopBar -->
  <header class="topbar">
    <a href="/" class="brand">
      <span class="brand-icon">✦</span>
      <span class="brand-title">
        <strong>Emby Relay</strong>
        <small>节点与线路管理</small>
      </span>
    </a>
    <div class="topbar-right">
      <div class="user-pills">
        <span class="pill pill-user">👤 {html.escape(user['username'])}</span>
        <span class="pill pill-quota">🗂 额度 <b>{used_routes}</b>/{route_quota} 条</span>
        <span class="pill pill-live"><i></i>{html.escape(expiry_label)}</span>
      </div>
      <button type="button" class="theme-toggle" id="user-theme-toggle" title="切换主题" aria-label="切换主题">☾</button>
      <a class="action-pill" href="/account">🔐 账号安全</a>
      {admin_link}
      <form class="logout-form" method="post" action="/logout" style="margin:0">
        <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
        <button type="submit" class="logout-btn">退出</button>
      </form>
    </div>
  </header>

  <!-- Hero Header -->
  <section class="hero">
    <span class="hero-tag">✦ 智能媒体反代</span>
    <h1>让每一次播放 <span>走更合适的线路</span></h1>
    <p>选择最优节点生成专属反代入口，智能优化连接质量与流式播放体验。</p>
  </section>

  <!-- Workspace Box -->
  <section class="panel-box">
    <div class="section-header">
      <h2>选择节点</h2>
      <span>延迟由当前浏览器实时测量</span>
    </div>
    <div class="nodes-grid" id="nodes">
      {node_cards}
    </div>
    <div class="node-tools">
      <button type="button" class="btn-probe" id="test-nodes">⚡ 重新测试延迟</button>
      <span class="hint" style="margin:0;color:var(--text-faint);font-size:12px;">生成后，线路将实时下发到所选节点。</span>
    </div>

    <form class="route-form" method="post">
      <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
      <input type="hidden" name="node_id" id="node-id" value="{selected_node_id}">
      <label>原始网站地址 (源站)</label>
      <div class="form-row">
        <input required name="url" placeholder="https://emby.example.com" value="{html.escape(raw_url)}">
        <button type="submit" class="btn-generate">生成访问地址</button>
      </div>
      <div class="form-note-row">
        <input name="route_note" maxlength="500" placeholder="线路备注（可选，例如：主力影视库）" value="{html.escape(raw_route_note, quote=True)}">
      </div>
      <p class="form-hint">线路会自动归属到你的账号；系统将清理来源特征与代理链路标识，保障隐私并支持完整流式媒体播放。</p>
    </form>
  </section>

  {result_html}

  <!-- My Routes Section -->
  <section class="panel-box">
    <div class="section-header">
      <h2>我的线路</h2>
      <span>删除线路后会立即释放额度</span>
    </div>
    <div class="routes-scroll">
      <table>
        <thead>
          <tr>
            <th>原线路（源站）</th>
            <th>反代线路（访问地址）</th>
            <th>节点</th>
            <th>备注</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {my_routes_html}
        </tbody>
      </table>
    </div>
  </section>
</main>

<script nonce="{csp_nonce}">
const nodes={nodes_json};
let selected={selected_node_id};

function pick(id){{
  selected=id;
  document.getElementById('node-id').value=id;
  document.querySelectorAll('.node-card').forEach(card=>{{
    const active=Number(card.dataset.nodeId)===id;
    card.classList.toggle('selected',active);
    card.setAttribute('aria-pressed',String(active));
  }});
}}

document.querySelectorAll('.node-card').forEach(card=>card.addEventListener('click',()=>pick(Number(card.dataset.nodeId))));

async function probe(node){{
  const label=document.querySelector('[data-latency="'+node.id+'"]');
  if(!label) return;
  label.textContent='测速中…';
  label.className='latency';
  const start=performance.now();
  try{{
    await fetch(node.probe_url+'?t='+Date.now(),{{mode:'no-cors',cache:'no-store'}});
    const ms=Math.round(performance.now()-start);
    label.textContent=ms+' ms';
    if(ms<120){{
      label.className='latency fast';
    }}else if(ms<250){{
      label.className='latency medium';
    }}else{{
      label.className='latency slow';
    }}
  }}catch(e){{
    label.textContent='无法连接';
    label.className='latency error';
  }}
}}

function probeAll(){{nodes.forEach(probe);}}
document.getElementById('test-nodes')?.addEventListener('click',probeAll);
if(nodes.length){{probeAll();}}

async function copyText(value){{
  try{{
    if(navigator.clipboard&&window.isSecureContext){{
      await navigator.clipboard.writeText(value);
      return true;
    }}
    const field=document.createElement('textarea');
    field.value=value;
    field.readOnly=true;
    field.style.cssText='position:fixed;opacity:0';
    document.body.append(field);
    field.select();
    const copied=document.execCommand('copy');
    field.remove();
    return copied;
  }}catch(e){{
    return false;
  }}
}}

document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{{
  const label=button.textContent;
  const ok=await copyText(button.dataset.copy);
  button.textContent=ok?'✓ 已复制':'复制失败';
  setTimeout(()=>button.textContent=label,1400);
}}));

document.querySelectorAll('.route-note-cell').forEach(cell=>{{
  const view=cell.querySelector('.route-note-view');
  const form=cell.querySelector('.route-note-form');
  const input=form?.querySelector('input[name="notes"]');
  cell.querySelector('.note-edit')?.addEventListener('click',()=>{{
    view.style.display='none';
    form.classList.add('is-open');
    input?.focus();
    input?.select();
  }});
  cell.querySelector('.note-cancel')?.addEventListener('click',()=>{{
    form.classList.remove('is-open');
    view.style.display='';
  }});
}});

const userThemeKey='emby-relay-user-theme';
const userThemeToggle=document.getElementById('user-theme-toggle');
let savedUserTheme='';
try{{savedUserTheme=localStorage.getItem(userThemeKey)||'';}}catch(e){{}}

function applyUserTheme(theme){{
  const resolved=theme==='dark'?'dark':'light';
  document.body.dataset.theme=resolved;
  if(userThemeToggle){{
    const dark=resolved==='dark';
    userThemeToggle.textContent=dark?'☼':'☾';
    userThemeToggle.setAttribute('aria-label',dark?'切换到白色主题':'切换到黑色主题');
    userThemeToggle.title=dark?'切换到白色主题':'切换到黑色主题';
  }}
  try{{localStorage.setItem(userThemeKey,resolved);}}catch(e){{}}
}}

applyUserTheme(savedUserTheme||'light');
userThemeToggle?.addEventListener('click',()=>applyUserTheme(document.body.dataset.theme==='dark'?'light':'dark'));
</script>
</body>
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
