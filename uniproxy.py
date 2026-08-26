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
        state_class = "off" if route["suspended_by_owner"] else ("" if route["deployed"] else "error-state")
        error = f"<br><span class='route-error'>{html.escape(route['last_error'])}</span>" if route["last_error"] else ""
        note = str(route["notes"] or "")
        note_display = html.escape(note) if note else "未填写"
        note_class = "" if note else " empty"
        note_editor = f"<td class='route-note-cell'><div class='route-note-view'><span class='route-note-text{note_class}'>{note_display}</span><button type='button' class='note-edit' title='编辑备注' aria-label='编辑备注'>✎</button></div><form class='route-note-form' method='post' action='/my/routes/{route['id']}/note'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><input name='notes' maxlength='500' value='{html.escape(note, quote=True)}' placeholder='线路备注'><button type='submit'>保存</button><button type='button' class='note-cancel'>取消</button></form></td>"
        route_rows.append(
            f"<tr><td><span class='route-url'>{html.escape(route['origin'])}</span></td>"
            f"<td><div class='route-link-cell'><span class='route-url'>{html.escape(route['public_url'])}</span><button type='button' class='copy-route' data-copy='{html.escape(route['public_url'], quote=True)}'>复制</button></div></td>"
            f"<td>{html.escape(route['node_name'])}</td>{note_editor}<td><span class='route-state {state_class}'>{state}</span>{error}</td><td><form method='post' action='/my/routes/{route['id']}/delete'>"
            f"<input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='delete-route'>删除</button></form></td></tr>"
        )
    used_routes, route_quota = panel.user_route_usage(int(user["id"]))
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='hint'>你还没有创建线路。</td></tr>"
    expiry_label = panel._display_expiry(user["expires_at"])
    admin_link = "<a class='admin-link' href='/_admin'>管理后台</a>" if int(user["is_admin"] or 0) else ""
    csp_nonce = secrets.token_urlsafe(16)

    body = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emby Relay · 线路面板</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<link rel="shortcut icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;overflow-x:hidden;color:#24334d;background:linear-gradient(145deg,#f8fbff 0%,#f4f7fe 47%,#eef7f8 100%);font-family:"PingFang SC","Microsoft YaHei",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}body:before,body:after{{content:"";position:fixed;z-index:-1;pointer-events:none;border-radius:50%;filter:blur(8px)}}body:before{{width:42vw;height:42vw;left:-15vw;top:-16vw;background:radial-gradient(circle,rgba(174,195,255,.45),rgba(174,195,255,0) 70%)}}body:after{{width:46vw;height:46vw;right:-14vw;bottom:-23vw;background:radial-gradient(circle,rgba(172,228,221,.42),rgba(172,228,221,0) 70%)}}
    main{{max-width:980px;margin:0 auto;padding:30px 24px 62px}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:55px}}.brand{{display:flex;align-items:center;gap:10px;color:#33455f;font-weight:750;letter-spacing:.04em;font-size:15px}}.brand-mark{{display:grid;place-items:center;width:34px;height:34px;border:1px solid #d9e3f7;border-radius:12px;color:#6079b7;background:linear-gradient(145deg,#fff,#edf3ff);box-shadow:0 8px 20px rgba(96,121,183,.12)}}.live{{display:flex;gap:8px;align-items:center;color:#61718a;font-size:12px;padding:8px 12px;border:1px solid rgba(192,205,226,.7);border-radius:999px;background:rgba(255,255,255,.65);box-shadow:0 5px 16px rgba(73,99,143,.06)}}.live i{{width:7px;height:7px;border-radius:50%;background:#61bd8a;box-shadow:0 0 0 4px rgba(97,189,138,.12)}}.account-actions{{display:flex;align-items:center;gap:8px}}.account-actions a{{color:#526b9f;font-size:12px;text-decoration:none}}.logout-form{{margin:0}}button.logout{{height:34px;padding:0 10px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#617595;font-size:12px}}
.hero{{max-width:710px;margin:0 auto 34px;text-align:center}}h1{{margin:9px 0 16px;color:#293b59;font-size:clamp(38px,6vw,64px);line-height:1.15;letter-spacing:-.055em;font-weight:780}}h1 span{{color:#657dbc}}.eyebrow{{display:inline-flex;align-items:center;gap:7px;color:#6682bb;font-size:13px;font-weight:700;letter-spacing:.08em}}.eyebrow:before{{content:"";width:18px;height:1px;background:#a9b9dd}}.subtitle,.hint{{color:#71809a;line-height:1.8}}.subtitle{{max-width:570px;margin:0 auto;font-size:15px}}.workspace,.result{{position:relative;overflow:hidden;margin-top:20px;padding:27px 28px;border:1px solid rgba(208,219,238,.88);border-radius:22px;background:rgba(255,255,255,.7);box-shadow:0 20px 55px rgba(75,98,142,.1);backdrop-filter:blur(18px)}}.workspace:after{{content:"";position:absolute;width:260px;height:260px;right:-145px;top:-180px;border-radius:50%;background:radial-gradient(circle,rgba(181,202,249,.25),rgba(181,202,249,0) 68%);pointer-events:none}}
.section-line{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}}.section-line h2{{margin:0;color:#405572;font-size:15px;letter-spacing:.01em}}.section-line span{{font-size:12px;color:#8795aa}}.nodes{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;max-width:540px;margin:0 auto 17px}}.node-card{{display:flex;flex-direction:column;justify-content:center;gap:5px;min-height:82px;padding:8px 10px;text-align:center;color:#18243a;border:2px solid #edf0f5;border-radius:16px;background:rgba(255,255,255,.94);cursor:pointer;transition:transform .18s,border-color .18s,box-shadow .18s,background .18s}}.node-card:hover{{transform:translateY(-2px);border-color:#cbd8ef;box-shadow:0 8px 18px rgba(87,111,157,.1)}}.node-card.selected{{border-color:#2763ff;background:#fbfdff;box-shadow:0 0 0 1px #2763ff,0 8px 18px rgba(39,99,255,.1)}}.node-title{{display:flex;align-items:center;justify-content:center;min-height:24px}}.node-flag{{display:grid;place-items:center;line-height:1}}.flag-icon{{display:block;width:30px;height:20px;border-radius:3px;box-shadow:0 1px 4px rgba(55,72,104,.22)}}.node-name{{display:block;overflow:hidden;color:#485e7d;font-size:11px;font-weight:700;line-height:1.35;white-space:nowrap;text-overflow:ellipsis}}.node-meta{{display:flex;align-items:center;justify-content:space-between;gap:8px}}.node-card small{{overflow:hidden;color:#8a96a8;font-size:10px;white-space:nowrap;text-overflow:ellipsis}}.latency{{flex:0 0 auto;color:#667b9f;font-size:10px;font-weight:700}}
    .tools{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 7px}}button{{height:47px;padding:0 20px;border:1px solid #607abc;border-radius:12px;background:linear-gradient(135deg,#6d84bd,#5873ae);box-shadow:0 10px 20px rgba(82,108,165,.2);color:#fff;font-family:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:transform .16s,box-shadow .16s}}button:hover{{transform:translateY(-1px);box-shadow:0 13px 23px rgba(82,108,165,.28)}}button.secondary{{height:38px;padding:0 13px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#617595}}button.copy-route{{height:30px;margin:6px 0 0 7px;padding:0 9px;border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#526b9f;font-size:11px}}.copy-field{{display:flex;gap:8px;align-items:center}}.copy-field button.copy-route{{height:42px;flex:0 0 auto;margin:6px 0 0;padding:0 14px;font-size:13px}}.route-form{{padding-top:20px;border-top:1px solid #e6ebf4}}.route-note-field{{margin-top:10px}}label{{display:block;margin:0 0 9px;color:#536882;font-size:13px;font-weight:720}}.row{{display:flex;gap:10px}}input{{width:100%;min-width:0;padding:13px 15px;outline:0;color:#30435f;border:1px solid #d8e1ef;border-radius:12px;background:#fff;font:15px inherit;transition:border-color .18s,box-shadow .18s}}input::placeholder{{color:#a5b0c1}}input:focus{{border-color:#8fa7dc;box-shadow:0 0 0 4px rgba(143,167,220,.16)}}.row button{{min-width:116px}}.hint{{margin:10px 0 0;font-size:12px}}.error{{padding:14px;border:1px solid #f2c8d0;border-radius:13px;color:#b85f6d;background:#fff5f6}}.result{{border-color:#c9daf1}}.result input{{margin-top:6px}}.result .eyebrow{{margin-bottom:15px}}.my-routes{{margin-top:20px;padding:22px 24px;border:1px solid rgba(208,219,238,.88);border-radius:20px;background:rgba(255,255,255,.7);box-shadow:0 18px 48px rgba(75,98,142,.08)}}.my-routes h2{{margin:0;color:#405572;font-size:16px}}.routes-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}.my-routes table{{width:100%;min-width:800px;margin-top:14px;border-collapse:collapse}}.my-routes th,.my-routes td{{padding:10px 7px;border-bottom:1px solid #e4ebf5;text-align:left;vertical-align:top;font-size:12px}}.route-url{{color:#315fbd;word-break:break-all}}.route-note-cell{{min-width:170px}}.route-note-view{{display:inline-flex;align-items:center;gap:6px;max-width:210px}}.route-note-text{{overflow:hidden;color:#526b9f;white-space:nowrap;text-overflow:ellipsis}}.route-note-text.empty{{color:#97a4b7}}button.note-edit{{width:25px;height:25px;margin:0;padding:0;border:1px solid #d7e0ef;border-radius:7px;background:#f9fbff;box-shadow:none;color:#526b9f;font-size:13px;line-height:1}}button.note-edit:hover{{transform:none;background:#eef3fb;box-shadow:none}}.route-note-form{{display:none;align-items:center;gap:5px}}.route-note-form.is-open{{display:flex}}.route-note-form input{{width:145px;height:32px;padding:6px 8px;font-size:12px}}.route-note-form button{{height:30px;padding:0 9px;font-size:11px}}.route-note-form .note-cancel{{border-color:#d7e0ef;background:#f9fbff;box-shadow:none;color:#617595}}button.delete-route{{height:32px;padding:0 9px;border-color:#f2c8d0;background:#fff5f6;box-shadow:none;color:#b85f6d;font-size:12px}}.route-error{{color:#b85f6d}}
@media(max-width:650px){{main{{padding:20px 14px 40px}}.topbar{{margin-bottom:38px}}.brand{{font-size:14px}}.hero{{margin-bottom:25px}}.workspace,.result{{padding:19px 16px;border-radius:18px}}.section-line{{align-items:flex-start;flex-direction:column;gap:5px}}.nodes{{gap:10px}}.node-card{{min-height:78px;padding:8px 7px;border-radius:15px}}.node-title{{min-height:22px}}.flag-icon{{width:27px;height:18px}}.node-meta{{display:flex}}.node-card small,.node-name,.latency{{font-size:9px}}.row{{flex-direction:column}}.row button{{width:100%}}.tools{{align-items:flex-start;flex-direction:column}}}}
</style>
<style>{DASHBOARD_UI_CSS}</style>
    <body data-theme="light"><main class="app-shell"><nav class="topbar"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true">✦</span><span class="brand-copy"><strong>Emby Relay</strong><small>节点与线路管理</small></span></a><div class="account-actions"><div class="live"><i></i>{html.escape(user['username'])} · {used_routes}/{route_quota} 条 · {html.escape(expiry_label)}</div>{admin_link}<a href="/account">账号安全</a><button type="button" class="theme-toggle" id="user-theme-toggle" aria-label="切换到黑色主题" title="切换到黑色主题">☾</button><form class="logout-form" method="post" action="/logout"><input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}"><button class="logout">退出</button></form></div></nav>
<header class="hero"><div class="hero-copy"><span class="eyebrow">Private Media Access</span><h1>为播放选择<br><span>更合适的线路。</span></h1><p class="subtitle">测试节点延迟，为你的媒体站点生成独立访问地址。线路之间互不影响，可以随时切换。</p></div><div class="hero-stats"><div class="stat"><span class="stat-label">线路额度</span><strong>{used_routes} / {route_quota}</strong><small>已创建 / 可创建</small></div><div class="stat"><span class="stat-label">账号有效期</span><strong>{html.escape(expiry_label)}</strong><small>当前账户状态正常</small></div></div></header>
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
document.querySelectorAll('.route-note-cell').forEach(cell=>{{const view=cell.querySelector('.route-note-view');const form=cell.querySelector('.route-note-form');const input=form?.querySelector('input[name="notes"]');cell.querySelector('.note-edit')?.addEventListener('click',()=>{{view.hidden=true;form.classList.add('is-open');input?.focus();input?.select();}});cell.querySelector('.note-cancel')?.addEventListener('click',()=>{{form.classList.remove('is-open');view.hidden=false;}});}});
const userThemeKey='emby-relay-user-theme';
const userThemeToggle=document.getElementById('user-theme-toggle');
let savedUserTheme='';
try{{savedUserTheme=localStorage.getItem(userThemeKey)||'';}}catch(e){{}}
function applyUserTheme(theme){{const resolved=theme==='dark'?'dark':'light';document.body.dataset.theme=resolved;if(userThemeToggle){{const dark=resolved==='dark';userThemeToggle.textContent=dark?'☼':'☾';userThemeToggle.setAttribute('aria-label',dark?'切换到白色主题':'切换到黑色主题');userThemeToggle.title=dark?'切换到白色主题':'切换到黑色主题';}}try{{localStorage.setItem(userThemeKey,resolved);}}catch(e){{}}}}
applyUserTheme(savedUserTheme||'light');
userThemeToggle?.addEventListener('click',()=>applyUserTheme(document.body.dataset.theme==='dark'?'light':'dark'));
</script>
</main></body>
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
