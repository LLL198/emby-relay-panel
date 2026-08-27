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
            result_html = f"""
            <section class="result-box">
                <div class="result-header">
                    <span class="badge-success">✓ 线路创建成功</span>
                    <span class="result-meta">分配节点：<code>{html.escape(host)}</code></span>
                </div>
                <div class="result-content">
                    <label class="result-label">专属 HTTPS 访问地址</label>
                    <div class="copy-group">
                        <input readonly value="{html.escape(https_url, quote=True)}" id="res-url">
                        <button type="button" class="btn-copy" data-copy="{html.escape(https_url, quote=True)}">
                            <span class="copy-text">复制地址</span>
                        </button>
                    </div>
                </div>
            </section>
            """
        except Exception as exc:
            result_html = f"<div class='alert-error'><span class='alert-icon'>⚠</span><div class='alert-msg'><strong>生成失败</strong><span>{html.escape(str(exc))}。示例：https://emby.example.com:8096</span></div></div>"

    node_cards_parts = []
    for node in nodes:
        meta_label = node["code"].lower() if node["is_local"] else (node["country_name"] or node["health"])
        is_selected = node["id"] == selected_node_id
        node_cards_parts.append(
            f"<button type='button' class='node-card{' selected' if is_selected else ''}' data-node-id='{node['id']}' aria-pressed={'true' if is_selected else 'false'}>"
            f"  <div class='node-card-top'>"
            f"    <div class='node-flag'>{node['flag_markup']}</div>"
            f"    <span class='node-name'>{html.escape(node['name'])}</span>"
            f"  </div>"
            f"  <div class='node-card-bottom'>"
            f"    <span class='node-location'>{html.escape(meta_label)}</span>"
            f"    <span class='latency-badge' data-latency='{node['id']}'><i class='latency-dot'></i><span class='latency-text'>待测速</span></span>"
            f"  </div>"
            f"</button>"
        )
    node_cards = "".join(node_cards_parts) or "<div class='empty-state'>暂无可用节点，请联系管理员添加。</div>"
    nodes_json = json.dumps(nodes, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    route_rows = []
    for route in panel.user_routes(int(user["id"])):
        state = "已暂停" if route["suspended_by_owner"] else ("已下发" if route["deployed"] else "部署失败")
        state_class = "state-paused" if route["suspended_by_owner"] else ("state-active" if route["deployed"] else "state-failed")
        error = f"<div class='route-error'>{html.escape(route['last_error'])}</div>" if route["last_error"] else ""
        note = str(route["notes"] or "")
        note_display = html.escape(note) if note else "添加备注"
        note_class = "" if note else " empty"
        note_editor = f"<td class='col-note'><div class='note-view'><span class='note-text{note_class}'>{note_display}</span><button type='button' class='btn-note-edit' title='编辑备注'>✎</button></div><form class='note-form' method='post' action='/my/routes/{route['id']}/note'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><input name='notes' maxlength='500' value='{html.escape(note, quote=True)}' placeholder='线路备注'><button type='submit' class='btn-note-save'>保存</button><button type='button' class='btn-note-cancel'>取消</button></form></td>"
        route_rows.append(
            f"<tr class='route-row'>"
            f"<td class='col-origin'><span class='url-text text-muted' title='{html.escape(route['origin'], quote=True)}'>{html.escape(route['origin'])}</span></td>"
            f"<td class='col-public'><div class='copy-inline'><span class='url-text text-primary' title='{html.escape(route['public_url'], quote=True)}'>{html.escape(route['public_url'])}</span><button type='button' class='btn-mini-copy' data-copy='{html.escape(route['public_url'], quote=True)}' title='复制访问地址'>复制</button></div></td>"
            f"<td class='col-node'><span class='tag-node'>{html.escape(route['node_name'])}</span></td>"
            f"{note_editor}"
            f"<td class='col-status'><span class='status-tag {state_class}'><i class='dot'></i>{state}</span>{error}</td>"
            f"<td class='col-action'><form method='post' action='/my/routes/{route['id']}/delete'><input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'><button class='btn-delete' title='删除该线路并释放额度'>删除</button></form></td>"
            f"</tr>"
        )
    used_routes, route_quota = panel.user_route_usage(int(user["id"]))
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='table-empty'><div class='empty-icon'>✦</div><p>暂无反代线路，在上方输入源站地址即可快速生成。</p></td></tr>"
    expiry_label = panel._display_expiry(user["expires_at"])
    admin_link = "<a class='btn-nav-admin' href='/_admin'><span>管理后台</span></a>" if int(user["is_admin"] or 0) else ""
    csp_nonce = secrets.token_urlsafe(16)

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emby Relay · 节点与线路管理</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E⚡%3C/text%3E%3C/svg%3E">
<style>
:root{{
  --bg:#09090b;
  --card:#121215;
  --card-subtle:#18181b;
  --border:#27272a;
  --border-hover:#3f3f46;
  --border-active:#3b82f6;
  --text:#fafafa;
  --text-secondary:#a1a1aa;
  --text-muted:#71717a;
  --primary:#3b82f6;
  --primary-hover:#2563eb;
  --primary-subtle:rgba(59,130,246,0.1);
  --success:#10b981;
  --success-bg:rgba(16,185,129,0.12);
  --danger:#ef4444;
  --danger-bg:rgba(239,68,68,0.12);
  --warning:#f59e0b;
  --radius-sm:6px;
  --radius-md:10px;
  --radius-lg:14px;
}}
body[data-theme='light']{{
  --bg:#f8fafc;
  --card:#ffffff;
  --card-subtle:#f1f5f9;
  --border:#e2e8f0;
  --border-hover:#cbd5e1;
  --border-active:#2563eb;
  --text:#0f172a;
  --text-secondary:#475569;
  --text-muted:#94a3b8;
  --primary:#2563eb;
  --primary-hover:#1d4ed8;
  --primary-subtle:rgba(37,99,235,0.08);
  --success:#059669;
  --success-bg:rgba(5,150,105,0.1);
  --danger:#dc2626;
  --danger-bg:rgba(220,38,38,0.1);
  --warning:#d97706;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{min-height:100%;background:var(--bg)}}
body{{
  min-height:100vh;
  background:var(--bg);
  color:var(--text);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  transition:background .2s ease,color .2s ease;
}}
.app-header{{
  position:sticky;top:0;z-index:40;display:flex;align-items:center;justify-content:space-between;
  height:56px;padding:0 24px;border-bottom:1px solid var(--border);background:var(--card);
}}
.nav-brand{{display:flex;align-items:center;gap:8px;text-decoration:none;}}
.brand-icon{{display:grid;place-items:center;width:28px;height:28px;border-radius:6px;background:var(--primary);color:#fff;font-size:14px;font-weight:700;}}
.brand-title{{font-size:15px;font-weight:700;color:var(--text);letter-spacing:-0.01em;}}
.nav-right{{display:flex;align-items:center;gap:10px;}}
.nav-chip{{
  display:inline-flex;align-items:center;height:30px;padding:0 10px;
  border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card-subtle);
  color:var(--text-secondary);font-size:12px;font-weight:500;
}}
.nav-chip b{{color:var(--primary);font-weight:700;margin-left:3px;}}
.btn-icon{{
  display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--border);
  border-radius:var(--radius-sm);background:var(--card-subtle);color:var(--text-secondary);
  font-size:14px;cursor:pointer;transition:all .15s ease;
}}
.btn-icon:hover{{border-color:var(--border-hover);color:var(--text);}}
.nav-link{{
  display:inline-flex;align-items:center;height:30px;padding:0 10px;border:1px solid var(--border);
  border-radius:var(--radius-sm);background:var(--card-subtle);color:var(--text-secondary);
  font-size:12px;font-weight:500;text-decoration:none;transition:all .15s ease;
}}
.nav-link:hover{{border-color:var(--border-hover);color:var(--text);}}
.btn-nav-admin{{
  display:inline-flex;align-items:center;height:30px;padding:0 10px;border:1px solid var(--border-active);
  border-radius:var(--radius-sm);background:var(--primary-subtle);color:var(--primary);
  font-size:12px;font-weight:600;text-decoration:none;transition:all .15s ease;
}}
.btn-nav-admin:hover{{background:var(--primary);color:#fff;}}
.btn-logout{{
  height:30px;padding:0 10px;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:transparent;color:var(--text-muted);font:inherit;font-size:12px;font-weight:500;
  cursor:pointer;transition:all .15s ease;
}}
.btn-logout:hover{{border-color:var(--danger);color:var(--danger);}}
.main-container{{max-width:1000px;margin:0 auto;padding:28px 20px 60px;display:grid;gap:24px;}}
.panel-card{{
  padding:24px;border:1px solid var(--border);border-radius:var(--radius-lg);
  background:var(--card);
}}
.panel-header{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px;}}
.panel-title{{font-size:16px;font-weight:700;color:var(--text);letter-spacing:-0.01em;}}
.panel-subtitle{{margin-top:2px;font-size:12px;color:var(--text-muted);}}
.btn-secondary{{
  display:inline-flex;align-items:center;gap:5px;height:32px;padding:0 12px;
  border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card-subtle);
  color:var(--text-secondary);font:inherit;font-size:12px;font-weight:600;cursor:pointer;
  transition:all .15s ease;
}}
.btn-secondary:hover{{border-color:var(--border-hover);color:var(--text);}}
.node-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:20px;}}
.node-card{{
  display:flex;flex-direction:column;justify-content:space-between;min-height:84px;padding:12px;
  text-align:left;border:1.5px solid var(--border);border-radius:var(--radius-md);
  background:var(--card-subtle);cursor:pointer;transition:all .15s ease;
}}
.node-card:hover{{border-color:var(--border-hover);}}
.node-card.selected{{border-color:var(--primary);background:var(--primary-subtle);}}
.node-card-top{{display:flex;align-items:center;gap:8px;}}
.node-flag{{display:grid;place-items:center;}}
.node-flag img, .node-flag span{{width:24px;height:16px;border-radius:2px;}}
.node-name{{font-size:13px;font-weight:700;color:var(--text);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}}
.node-card-bottom{{display:flex;align-items:center;justify-content:space-between;margin-top:12px;}}
.node-location{{font-size:11px;color:var(--text-muted);}}
.latency-badge{{
  display:inline-flex;align-items:center;gap:4px;padding:2px 6px;border-radius:999px;
  background:rgba(148,163,184,0.1);color:var(--text-muted);font-size:10px;font-weight:600;
}}
.latency-dot{{width:5px;height:5px;border-radius:50%;background:currentColor;}}
.latency-badge.fast{{background:var(--success-bg);color:var(--success);}}
.latency-badge.medium{{background:rgba(245,158,11,0.12);color:var(--warning);}}
.latency-badge.slow,.latency-badge.error{{background:var(--danger-bg);color:var(--danger);}}
.panel-divider{{height:1px;background:var(--border);margin:20px 0;}}
.form-group{{margin-bottom:16px;}}
.form-label{{display:block;margin-bottom:6px;font-size:13px;font-weight:600;color:var(--text);}}
.label-optional{{font-weight:400;color:var(--text-muted);font-size:12px;}}
.form-input{{
  width:100%;height:42px;padding:0 14px;outline:0;border:1px solid var(--border);
  border-radius:var(--radius-sm);background:var(--card-subtle);color:var(--text);
  font:inherit;font-size:13px;transition:border-color .15s ease,box-shadow .15s ease;
}}
.form-input:focus{{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-subtle);}}
.btn-primary{{
  width:100%;height:44px;border:0;border-radius:var(--radius-sm);background:var(--primary);
  color:#fff;font:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:background .15s ease;
}}
.btn-primary:hover{{background:var(--primary-hover);}}
.result-box{{
  padding:20px 24px;border:1.5px solid var(--success);border-radius:var(--radius-lg);
  background:var(--card);
}}
.result-header{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;}}
.badge-success{{
  display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:999px;
  background:var(--success-bg);color:var(--success);font-size:12px;font-weight:700;
}}
.result-meta code{{
  padding:2px 6px;border-radius:4px;background:var(--card-subtle);border:1px solid var(--border);
  color:var(--primary);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;
}}
.result-label{{display:block;margin-bottom:6px;font-size:12px;font-weight:600;color:var(--text-secondary);}}
.copy-group{{display:flex;gap:8px;}}
.copy-group input{{
  width:100%;height:42px;padding:0 12px;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:var(--card-subtle);color:var(--primary);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
  font-size:13px;font-weight:600;outline:0;
}}
.btn-copy{{
  flex:0 0 auto;height:42px;padding:0 18px;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:var(--card-subtle);color:var(--text);font:inherit;font-size:13px;font-weight:600;
  cursor:pointer;transition:all .15s ease;
}}
.btn-copy:hover{{border-color:var(--primary);color:var(--primary);}}
.alert-error{{
  display:flex;align-items:flex-start;gap:10px;padding:14px 18px;border:1px solid rgba(239,68,68,0.3);
  border-radius:var(--radius-md);background:var(--danger-bg);color:var(--danger);font-size:13px;
}}
.alert-icon{{font-size:16px;line-height:1.2;}}
.alert-msg strong{{display:block;margin-bottom:2px;font-weight:700;}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}
.data-table{{width:100%;min-width:760px;border-collapse:collapse;margin-top:8px;}}
.data-table th{{
  padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text-muted);
  font-size:12px;font-weight:600;text-align:left;
}}
.data-table td{{
  padding:12px;border-bottom:1px solid var(--border);color:var(--text-secondary);
  font-size:13px;vertical-align:middle;
}}
.data-table tr.route-row:hover td{{background:var(--card-subtle);}}
.data-table tr:last-child td{{border-bottom:0;}}
.url-text{{
  display:inline-block;max-width:220px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
  font-size:12px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;vertical-align:middle;
}}
.text-muted{{color:var(--text-muted);}}
.text-primary{{color:var(--primary);font-weight:600;}}
.copy-inline{{display:flex;align-items:center;gap:6px;}}
.btn-mini-copy{{
  flex:0 0 auto;height:24px;padding:0 8px;border:1px solid var(--border);border-radius:4px;
  background:var(--card);color:var(--text-secondary);font:inherit;font-size:11px;font-weight:600;
  cursor:pointer;transition:all .15s ease;
}}
.btn-mini-copy:hover{{border-color:var(--primary);color:var(--primary);}}
.tag-node{{
  display:inline-block;padding:2px 8px;border-radius:4px;border:1px solid var(--border);
  background:var(--card-subtle);color:var(--text);font-size:11px;font-weight:600;
}}
.status-tag{{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;}}
.status-tag .dot{{width:5px;height:5px;border-radius:50%;background:currentColor;}}
.status-tag.state-active{{background:var(--success-bg);color:var(--success);}}
.status-tag.state-failed{{background:var(--danger-bg);color:var(--danger);}}
.status-tag.state-paused{{background:rgba(148,163,184,0.12);color:var(--text-muted);}}
.route-error{{margin-top:3px;color:var(--danger);font-size:11px;}}
.col-note{{min-width:140px;}}
.note-view{{display:inline-flex;align-items:center;gap:6px;}}
.note-text{{max-width:150px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:var(--text);font-size:12px;font-weight:500;}}
.note-text.empty{{color:var(--text-muted);}}
.btn-note-edit{{
  display:grid;place-items:center;width:22px;height:22px;padding:0;border:1px solid var(--border);
  border-radius:4px;background:var(--card);color:var(--text-muted);font-size:11px;cursor:pointer;
}}
.btn-note-edit:hover{{border-color:var(--primary);color:var(--primary);}}
.note-form{{display:none;align-items:center;gap:5px;}}
.note-form.is-open{{display:flex;}}
.note-form input{{width:120px;height:28px;padding:0 6px;font-size:12px;border-radius:4px;border:1px solid var(--border);background:var(--card);color:var(--text);}}
.btn-note-save{{height:28px;padding:0 8px;border:0;border-radius:4px;background:var(--primary);color:#fff;font-size:11px;font-weight:600;cursor:pointer;}}
.btn-note-cancel{{height:28px;padding:0 6px;border:1px solid var(--border);border-radius:4px;background:var(--card);color:var(--text-muted);font-size:11px;cursor:pointer;}}
.btn-delete{{
  height:28px;padding:0 10px;border:1px solid rgba(239,68,68,0.3);border-radius:var(--radius-sm);
  background:var(--danger-bg);color:var(--danger);font:inherit;font-size:11px;font-weight:600;
  cursor:pointer;transition:all .15s ease;
}}
.btn-delete:hover{{background:var(--danger);color:#fff;}}
.count-tag{{padding:2px 8px;border-radius:999px;background:var(--card-subtle);border:1px solid var(--border);font-size:11px;font-weight:600;color:var(--text-muted);}}
.table-empty{{padding:40px 16px;text-align:center;color:var(--text-muted);font-size:13px;}}
.empty-icon{{font-size:20px;color:var(--primary);margin-bottom:6px;}}
.empty-state{{padding:24px 16px;text-align:center;color:var(--text-muted);font-size:13px;}}
@media(max-width:768px){{
  .app-header{{padding:0 16px;}}
  .main-container{{padding:16px 12px 48px;gap:16px;}}
  .panel-card{{padding:18px 14px;}}
  .node-grid{{grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;}}
  .nav-right .nav-chip.expiry{{display:none;}}
}}
</style>
</head>
<body data-theme="dark">
<header class="app-header">
  <a href="/" class="nav-brand">
    <span class="brand-icon">⚡</span>
    <span class="brand-title">Emby Relay</span>
  </a>
  <div class="nav-right">
    <span class="nav-chip">👤 {html.escape(user['username'])}</span>
    <span class="nav-chip">线路 <b>{used_routes}</b>/{route_quota}</span>
    <span class="nav-chip expiry">{html.escape(expiry_label)}</span>
    <button type="button" class="btn-icon" id="user-theme-toggle" title="切换主题" aria-label="切换主题">☼</button>
    <a class="nav-link" href="/account">账号安全</a>
    {admin_link}
    <form method="post" action="/logout" style="margin:0">
      <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
      <button type="submit" class="btn-logout">退出</button>
    </form>
  </div>
</header>

<main class="main-container">
  <section class="panel-card">
    <div class="panel-header">
      <div>
        <h2 class="panel-title">选择节点</h2>
        <p class="panel-subtitle">点击选择目标加速节点</p>
      </div>
      <button type="button" class="btn-secondary" id="test-nodes">⚡ 探测延迟</button>
    </div>

    <div class="node-grid" id="nodes">
      {node_cards}
    </div>

    <div class="panel-divider"></div>

    <form method="post">
      <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
      <input type="hidden" name="node_id" id="node-id" value="{selected_node_id}">
      
      <div class="form-group">
        <label class="form-label">源站地址 (Emby Server URL)</label>
        <input class="form-input" required name="url" placeholder="https://emby.example.com:8096" value="{html.escape(raw_url)}">
      </div>
      
      <div class="form-group">
        <label class="form-label">线路备注 <span class="label-optional">（可选）</span></label>
        <input class="form-input" name="route_note" maxlength="500" placeholder="例如：主力影视库、日漫专用" value="{html.escape(raw_route_note, quote=True)}">
      </div>
      
      <button type="submit" class="btn-primary">立即生成反代线路</button>
    </form>
  </section>

  {result_html}

  <section class="panel-card">
    <div class="panel-header">
      <div>
        <h2 class="panel-title">我的反代线路</h2>
        <p class="panel-subtitle">已创建的专属访问地址列表</p>
      </div>
      <span class="count-tag">{used_routes} 条</span>
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>原线路（源站）</th>
            <th>专属反代地址</th>
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
const nodes = {nodes_json};
let selected = {selected_node_id};

function pick(id) {{
  selected = id;
  const nodeInput = document.getElementById('node-id');
  if (nodeInput) nodeInput.value = id;
  document.querySelectorAll('.node-card').forEach(card => {{
    const active = Number(card.dataset.nodeId) === id;
    card.classList.toggle('selected', active);
    card.setAttribute('aria-pressed', String(active));
  }});
}}

document.querySelectorAll('.node-card').forEach(card => {{
  card.addEventListener('click', () => pick(Number(card.dataset.nodeId)));
}});

async function probe(node) {{
  const badge = document.querySelector('[data-latency="' + node.id + '"]');
  if (!badge) return;
  const textEl = badge.querySelector('.latency-text') || badge;
  textEl.textContent = '…';
  badge.className = 'latency-badge';
  const start = performance.now();
  try {{
    await fetch(node.probe_url + '?t=' + Date.now(), {{ mode: 'no-cors', cache: 'no-store' }});
    const ms = Math.round(performance.now() - start);
    textEl.textContent = ms + ' ms';
    if (ms < 120) {{
      badge.className = 'latency-badge fast';
    }} else if (ms < 280) {{
      badge.className = 'latency-badge medium';
    }} else {{
      badge.className = 'latency-badge slow';
    }}
  }} catch (e) {{
    textEl.textContent = '超时';
    badge.className = 'latency-badge error';
  }}
}}

function probeAll() {{ nodes.forEach(probe); }}
document.getElementById('test-nodes')?.addEventListener('click', probeAll);
if (nodes.length) {{ probeAll(); }}

async function copyText(value) {{
  try {{
    if (navigator.clipboard && window.isSecureContext) {{
      await navigator.clipboard.writeText(value);
      return true;
    }}
    const field = document.createElement('textarea');
    field.value = value;
    field.readOnly = true;
    field.style.cssText = 'position:fixed;opacity:0';
    document.body.append(field);
    field.select();
    const copied = document.execCommand('copy');
    field.remove();
    return copied;
  }} catch (e) {{
    return false;
  }}
}}

document.querySelectorAll('[data-copy]').forEach(button => {{
  button.addEventListener('click', async () => {{
    const copyTextSpan = button.querySelector('.copy-text');
    const oldText = copyTextSpan ? copyTextSpan.textContent : button.textContent;
    const ok = await copyText(button.dataset.copy);
    if (copyTextSpan) {{
      copyTextSpan.textContent = ok ? '已复制 ✓' : '复制失败';
    }} else {{
      button.textContent = ok ? '已复制 ✓' : '复制失败';
    }}
    setTimeout(() => {{
      if (copyTextSpan) copyTextSpan.textContent = oldText;
      else button.textContent = oldText;
    }}, 1500);
  }});
}});

document.querySelectorAll('.col-note').forEach(cell => {{
  const view = cell.querySelector('.note-view');
  const form = cell.querySelector('.note-form');
  const input = form?.querySelector('input[name="notes"]');
  cell.querySelector('.btn-note-edit')?.addEventListener('click', () => {{
    view.style.display = 'none';
    form.classList.add('is-open');
    input?.focus();
    input?.select();
  }});
  cell.querySelector('.btn-note-cancel')?.addEventListener('click', () => {{
    form.classList.remove('is-open');
    view.style.display = '';
  }});
}});

const userThemeKey = 'emby-relay-user-theme';
const userThemeToggle = document.getElementById('user-theme-toggle');
let savedUserTheme = '';
try {{ savedUserTheme = localStorage.getItem(userThemeKey) || ''; }} catch (e) {{}}

function applyUserTheme(theme) {{
  const resolved = theme === 'light' ? 'light' : 'dark';
  document.body.dataset.theme = resolved;
  if (userThemeToggle) {{
    const isDark = resolved === 'dark';
    userThemeToggle.textContent = isDark ? '☼' : '☾';
    userThemeToggle.setAttribute('aria-label', isDark ? '切换到浅色主题' : '切换到深色主题');
    userThemeToggle.title = isDark ? '切换到浅色主题' : '切换到深色主题';
  }}
  try {{ localStorage.setItem(userThemeKey, resolved); }} catch (e) {{}}
}}

applyUserTheme(savedUserTheme || 'dark');
userThemeToggle?.addEventListener('click', () => {{
  applyUserTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
}});
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
