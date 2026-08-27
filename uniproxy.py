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
    
    selected_node_name = "未选择节点"
    for n in nodes:
        if n["id"] == selected_node_id:
            selected_node_name = n["name"]
            break

    result_html = ""
    if raw_url:
        try:
            if not panel.user_route_creation_enabled:
                raise ValueError("线路创建功能已由管理员临时关闭")
            origin = normalized_origin(raw_url)
            if not selected_node_id:
                raise ValueError("暂无可用节点，无法创建线路")
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
                    <div class="result-status-title">
                        <span class="badge-success-glow">✓ 专属线路创建成功</span>
                        <span class="result-node-info">分配加速节点：<code>{html.escape(host)}</code></span>
                    </div>
                </div>
                <div class="result-body">
                    <label class="result-label">专属 HTTPS 播放地址</label>
                    <div class="copy-field-wrap">
                        <input readonly value="{html.escape(https_url, quote=True)}" id="res-url">
                        <button type="button" class="btn-copy-magic" data-copy="{html.escape(https_url, quote=True)}">
                            <span class="copy-text">一键复制</span>
                        </button>
                    </div>
                    <p class="result-hint">💡 请直接将此地址复制填入客户端使用。</p>
                </div>
            </section>
            """
        except Exception as exc:
            result_html = f"""
            <div class="alert-error-box">
                <span class="alert-error-icon">⚠</span>
                <div class="alert-error-text">
                    <strong>生成线路失败</strong>
                    <span>{html.escape(str(exc))}（示例格式：https://emby.example.com:8096）</span>
                </div>
            </div>
            """

    node_cards_parts = []
    for node in nodes:
        meta_label = node["code"].upper() if node["is_local"] else (node["country_name"] or node["health"])
        is_selected = node["id"] == selected_node_id
        kind_label = "VPS 加速" if not node.get("is_local") else "本地节点"
        node_cards_parts.append(
            f"<button type='button' class='node-card{' selected' if is_selected else ''}' "
            f"data-node-id='{node['id']}' data-node-name='{html.escape(node['name'], quote=True)}' "
            f"data-country='{html.escape(node.get('country_name') or '')}' aria-pressed={'true' if is_selected else 'false'}>"
            f"  <div class='node-card-glow-follower'></div>"
            f"  <div class='node-card-top'>"
            f"    <div class='node-flag'>{node['flag_markup']}</div>"
            f"    <div class='node-info-group'>"
            f"      <span class='node-name' title='{html.escape(node['name'], quote=True)}'>{html.escape(node['name'])}</span>"
            f"      <span class='node-country-tag'>{html.escape(node.get('country_name') or meta_label)}</span>"
            f"    </div>"
            f"  </div>"
            f"  <div class='node-card-sparkline'>"
            f"    <svg viewBox='0 0 160 32' class='sparkline-svg' preserveAspectRatio='none'>"
            f"      <defs>"
            f"        <linearGradient id='spark-grad-{node['id']}' x1='0%' y1='0%' x2='100%' y2='0%'>"
            f"          <stop offset='0%' stop-color='rgba(34, 211, 238, 0.85)' />"
            f"          <stop offset='100%' stop-color='rgba(139, 92, 246, 0.95)' />"
            f"        </linearGradient>"
            f"        <linearGradient id='spark-fill-{node['id']}' x1='0%' y1='0%' x2='0%' y2='100%'>"
            f"          <stop offset='0%' stop-color='rgba(34, 211, 238, 0.22)' />"
            f"          <stop offset='100%' stop-color='rgba(34, 211, 238, 0.0)' />"
            f"        </linearGradient>"
            f"      </defs>"
            f"      <path class='sparkline-area' fill='url(#spark-fill-{node['id']})' d='M0 24 Q 25 10, 50 18 T 100 8 T 160 14 L 160 32 L 0 32 Z'></path>"
            f"      <path class='sparkline-line' stroke='url(#spark-grad-{node['id']})' fill='none' stroke-width='2' d='M0 24 Q 25 10, 50 18 T 100 8 T 160 14'></path>"
            f"    </svg>"
            f"  </div>"
            f"  <div class='node-card-bottom'>"
            f"    <span class='node-kind-badge'>{html.escape(kind_label)}</span>"
            f"    <span class='latency-badge' data-latency='{node['id']}'>"
            f"      <i class='latency-dot'></i><span class='latency-text'>待测速</span>"
            f"    </span>"
            f"  </div>"
            f"</button>"
        )
    node_cards = "".join(node_cards_parts) or "<div class='empty-nodes-state'>暂无可用节点，请联系管理员添加。</div>"
    nodes_json = json.dumps(nodes, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    
    route_rows = []
    for route in panel.user_routes(int(user["id"])):
        state = "已暂停" if route["suspended_by_owner"] else ("已下发" if route["deployed"] else "部署失败")
        state_class = "state-paused" if route["suspended_by_owner"] else ("state-active" if route["deployed"] else "state-failed")
        error = f"<div class='route-error-msg'>{html.escape(route['last_error'])}</div>" if route["last_error"] else ""
        note = str(route["notes"] or "")
        note_display = html.escape(note) if note else "添加备注"
        note_class = "" if note else " empty-note"
        note_editor = (
            f"<td class='col-note'>"
            f"  <div class='note-view-box'>"
            f"    <span class='note-text{note_class}'>{note_display}</span>"
            f"    <button type='button' class='btn-note-edit' title='编辑备注'>✎</button>"
            f"  </div>"
            f"  <form class='note-inline-form' method='post' action='/my/routes/{route['id']}/note'>"
            f"    <input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'>"
            f"    <input name='notes' maxlength='500' value='{html.escape(note, quote=True)}' placeholder='输入线路备注'>"
            f"    <button type='submit' class='btn-note-save'>保存</button>"
            f"    <button type='button' class='btn-note-cancel'>取消</button>"
            f"  </form>"
            f"</td>"
        )
        route_rows.append(
            f"<tr class='route-row'>"
            f"  <td class='col-origin'><span class='url-badge origin-url' title='{html.escape(route['origin'], quote=True)}'>{html.escape(route['origin'])}</span></td>"
            f"  <td class='col-public'>"
            f"    <div class='copy-flex-cell'>"
            f"      <span class='url-badge public-url' title='{html.escape(route['public_url'], quote=True)}'>{html.escape(route['public_url'])}</span>"
            f"      <button type='button' class='btn-table-copy' data-copy='{html.escape(route['public_url'], quote=True)}' title='复制专属访问地址'>复制</button>"
            f"    </div>"
            f"  </td>"
            f"  <td class='col-node'><span class='node-tag-pill'>{html.escape(route['node_name'])}</span></td>"
            f"  {note_editor}"
            f"  <td class='col-status'><span class='status-pill {state_class}'><i class='pulse-dot'></i>{state}</span>{error}</td>"
            f"  <td class='col-action'>"
            f"    <form method='post' action='/my/routes/{route['id']}/delete' onsubmit='return confirm(\"确定删除该反代线路吗？删除后将释放配额。\");'>"
            f"      <input type='hidden' name='csrf' value='{html.escape(csrf_token, quote=True)}'>"
            f"      <button class='btn-table-delete' title='删除该线路并释放配额'>删除</button>"
            f"    </form>"
            f"  </td>"
            f"</tr>"
        )
    used_routes, route_quota = panel.user_route_usage(int(user["id"]))
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='table-empty-box'><div class='empty-sparkle'>✦</div><p>暂无反代线路，在上方选择节点并输入源站即可快速生成专属线路。</p></td></tr>"
    expiry_label = panel._display_expiry(user["expires_at"])
    admin_link = "<a class='btn-nav-admin' href='/_admin'><span>⚙ 管理后台</span></a>" if int(user["is_admin"] or 0) else ""
    csp_nonce = secrets.token_urlsafe(16)
    nodes_count = len(nodes)

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emby Relay · 全球智能媒体中继</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E⚡%3C/text%3E%3C/svg%3E">
<style>
:root {{
  color-scheme: dark;
  --bg: #030712;
  --panel-bg: rgba(11, 17, 34, 0.78);
  --panel-solid: #0d1527;
  --card-bg: rgba(17, 24, 47, 0.72);
  --card-hover: rgba(27, 38, 72, 0.88);
  --card-selected: rgba(15, 36, 68, 0.95);
  --border: rgba(148, 163, 184, 0.13);
  --border-hover: rgba(167, 139, 250, 0.38);
  --border-active: rgba(34, 211, 238, 0.75);
  --ink: #f8fafc;
  --ink-secondary: #cbd5e1;
  --muted: #94a3b8;
  --muted-dark: #64748b;
  --violet: #8b5cf6;
  --violet-glow: rgba(139, 92, 246, 0.32);
  --cyan: #22d3ee;
  --cyan-glow: rgba(34, 211, 238, 0.28);
  --emerald: #34d399;
  --emerald-bg: rgba(16, 185, 129, 0.14);
  --danger: #fb7185;
  --danger-bg: rgba(244, 63, 94, 0.14);
  --shadow-magic: 0 20px 60px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  --radius-panel: 22px;
  --radius-card: 16px;
  --radius-sm: 10px;
}}

body[data-theme='light'] {{
  color-scheme: light;
  --bg: #f4f6fb;
  --panel-bg: rgba(255, 255, 255, 0.90);
  --panel-solid: #ffffff;
  --card-bg: rgba(241, 245, 252, 0.86);
  --card-hover: rgba(235, 242, 255, 0.98);
  --card-selected: rgba(235, 246, 255, 0.98);
  --border: rgba(148, 163, 184, 0.26);
  --border-hover: rgba(139, 92, 246, 0.45);
  --border-active: rgba(14, 165, 233, 0.85);
  --ink: #0f172a;
  --ink-secondary: #334155;
  --muted: #64748b;
  --muted-dark: #94a3b8;
  --violet-glow: rgba(139, 92, 246, 0.16);
  --cyan-glow: rgba(14, 165, 233, 0.18);
  --emerald-bg: rgba(16, 185, 129, 0.15);
  --danger-bg: rgba(244, 63, 94, 0.12);
  --shadow-magic: 0 16px 45px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ background: var(--bg); min-height: 100%; }}
body {{
  position: relative;
  min-height: 100vh;
  color: var(--ink);
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
  overflow-x: hidden;
  background: var(--bg);
}}

.aurora-bg {{
  position: fixed;
  inset: -35%;
  pointer-events: none;
  z-index: 0;
  filter: blur(65px);
  opacity: 0.68;
}}
.aurora-blob {{
  position: absolute;
  border-radius: 50%;
  animation: aurora-drift 24s ease-in-out infinite alternate;
}}
.blob-1 {{
  width: 580px; height: 580px;
  top: 15%; left: 10%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.28), transparent 70%);
}}
.blob-2 {{
  width: 620px; height: 620px;
  top: 35%; right: 10%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.22), transparent 70%);
  animation-delay: -8s;
}}
.blob-3 {{
  width: 480px; height: 480px;
  bottom: 5%; left: 40%;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.20), transparent 70%);
  animation-delay: -16s;
}}

.grid-mesh {{
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image: 
    linear-gradient(rgba(148, 163, 184, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.045) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(ellipse at 50% 30%, black 20%, transparent 80%);
}}

@keyframes aurora-drift {{
  0% {{ transform: translate(0, 0) scale(1); }}
  50% {{ transform: translate(45px, -35px) scale(1.12); }}
  100% {{ transform: translate(-35px, 45px) scale(0.92); }}
}}

.magic-shell {{
  position: relative;
  z-index: 1;
  width: min(100%, 1280px);
  margin: 0 auto;
  padding: 20px 24px 60px;
}}

.magic-nav {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 62px;
  margin-bottom: 22px;
  padding: 10px 18px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(22px) saturate(140%);
}}

.nav-brand {{
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--ink);
}}
.brand-gem {{
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--violet), var(--cyan));
  box-shadow: 0 0 22px var(--violet-glow);
  color: #fff;
  font-size: 16px;
}}
.brand-meta strong {{
  display: block;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
  background: linear-gradient(90deg, var(--ink), var(--ink-secondary));
  -webkit-background-clip: text;
  color: transparent;
}}
.brand-meta small {{
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: 0.05em;
}}

.nav-actions {{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}}
.nav-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card-bg);
  color: var(--ink-secondary);
  font-size: 12px;
  font-weight: 600;
}}
.nav-badge.quota b {{ color: var(--cyan); }}
.nav-badge.status .dot {{
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--emerald);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2);
  animation: pulse-dot 2s infinite ease-in-out;
}}

@keyframes pulse-dot {{
  0%, 100% {{ transform: scale(1); opacity: 1; }}
  50% {{ transform: scale(1.3); opacity: 0.7; }}
}}

.nav-btn-icon, .nav-link-btn, .btn-nav-admin, .btn-logout {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card-bg);
  color: var(--ink-secondary);
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.18s ease;
}}
.nav-btn-icon {{ width: 34px; padding: 0; font-size: 15px; }}
.nav-btn-icon:hover, .nav-link-btn:hover, .btn-logout:hover {{
  border-color: var(--border-hover);
  background: var(--card-hover);
  color: var(--ink);
  transform: translateY(-1px);
}}
.btn-nav-admin {{
  border-color: rgba(34, 211, 238, 0.35);
  background: rgba(34, 211, 238, 0.08);
  color: var(--cyan);
}}
.btn-nav-admin:hover {{
  border-color: var(--cyan);
  background: rgba(34, 211, 238, 0.15);
  color: #fff;
}}

.hero-dashboard {{
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 20px;
  margin-bottom: 22px;
}}

.komari-globe-card {{
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 230px;
  padding: 18px 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
  overflow: hidden;
}}

.globe-header {{
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.globe-title-group h3 {{
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.globe-title-group p {{
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}}
.globe-live-tag {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(34, 211, 238, 0.12);
  border: 1px solid rgba(34, 211, 238, 0.3);
  color: var(--cyan);
  font-size: 11px;
  font-weight: 750;
}}
.globe-live-tag .radar-ping {{
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 8px var(--cyan);
  animation: pulse-dot 1.5s infinite;
}}

.globe-stage-wrapper {{
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 175px;
  margin-top: 4px;
}}
#komari-globe-canvas {{
  width: 100%;
  max-width: 480px;
  height: 175px;
  cursor: grab;
}}
#komari-globe-canvas:active {{
  cursor: grabbing;
}}

.metrics-grid {{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}}

.metric-tile {{
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
  transition: all 0.18s ease;
}}
.metric-tile:hover {{
  transform: translateY(-2px);
  border-color: var(--border-hover);
  background: var(--card-hover);
}}

.metric-tile-top {{
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.metric-tile-title {{
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}
.metric-tile-icon {{
  font-size: 15px;
}}
.metric-tile-val {{
  margin-top: 10px;
  font-size: 22px;
  font-weight: 850;
  letter-spacing: -0.02em;
  color: var(--ink);
  line-height: 1.2;
}}
.metric-tile-val span {{
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  margin-left: 3px;
}}
.metric-tile-sub {{
  margin-top: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--emerald);
  display: flex;
  align-items: center;
  gap: 4px;
}}

.magic-workspace {{
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(290px, 1fr);
  gap: 22px;
  margin-bottom: 24px;
}}

.bento-nodes-box {{
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
}}

.box-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}}
.box-header-title h2 {{
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--ink);
}}
.box-header-title p {{
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}}

.btn-probe-magic {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card-bg);
  color: var(--ink-secondary);
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.18s ease;
}}
.btn-probe-magic:hover {{
  border-color: var(--border-hover);
  background: var(--card-hover);
  color: var(--cyan);
  transform: translateY(-1px);
}}

.node-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
}}

.node-card {{
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 128px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  background: var(--card-bg);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  outline: none;
  overflow: hidden;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}}

.node-card-glow-follower {{
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background: radial-gradient(160px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), rgba(34, 211, 238, 0.15), transparent 70%);
  transition: opacity 0.3s ease;
}}
.node-card:hover .node-card-glow-follower {{ opacity: 1; }}

.node-card:after {{
  content: "";
  position: absolute;
  width: 8px; height: 8px;
  right: 12px; top: 12px;
  border-radius: 50%;
  border: 1.5px solid var(--muted-dark);
  background: transparent;
  transition: all 0.2s ease;
}}
.node-card:hover {{
  transform: translateY(-2px);
  border-color: var(--border-hover);
  background: var(--card-hover);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.22);
}}
.node-card.selected {{
  border-color: var(--border-active);
  background: var(--card-selected);
  box-shadow: 0 0 0 1px var(--cyan), 0 12px 32px var(--cyan-glow);
}}
.node-card.selected:after {{
  border-color: var(--cyan);
  background: var(--cyan);
  box-shadow: 0 0 10px var(--cyan);
}}

.node-card-top {{
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 11px;
}}
.node-flag {{
  flex: 0 0 auto;
  display: grid;
  place-items: center;
}}
.flag-icon {{
  display: block;
  width: 32px;
  height: 22px;
  border-radius: 5px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}}
.node-info-group {{
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}}
.node-name {{
  display: block;
  font-size: 13.5px;
  font-weight: 800;
  color: var(--ink);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}
.node-country-tag {{
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
}}

.node-card-sparkline {{
  position: relative;
  z-index: 1;
  width: 100%;
  height: 24px;
  margin: 6px 0 4px;
}}
.sparkline-svg {{
  width: 100%;
  height: 100%;
}}

.node-card-bottom {{
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.node-kind-badge {{
  font-size: 10px;
  font-weight: 750;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: rgba(148, 163, 184, 0.08);
  color: var(--muted);
  text-transform: uppercase;
}}

.latency-badge {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 750;
  color: var(--muted);
}}
.latency-dot {{
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--muted-dark);
}}
.latency-badge.fast {{ color: var(--emerald); }}
.latency-badge.fast .latency-dot {{ background: var(--emerald); box-shadow: 0 0 6px var(--emerald); }}
.latency-badge.medium {{ color: #fbbf24; }}
.latency-badge.medium .latency-dot {{ background: #fbbf24; }}
.latency-badge.slow, .latency-badge.error {{ color: var(--danger); }}
.latency-badge.slow .latency-dot, .latency-badge.error .latency-dot {{ background: var(--danger); }}

.empty-nodes-state {{
  padding: 30px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}}

.route-creation-card {{
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 22px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
}}

.crystal-orb-stage {{
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0 16px;
}}
.crystal-orb-wrapper {{
  position: relative;
  width: 76px;
  height: 76px;
  display: grid;
  place-items: center;
}}
.crystal-orb {{
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #fff 2%, var(--cyan) 35%, var(--violet) 75%, #05060f 100%);
  box-shadow: 0 0 25px var(--cyan-glow), inset 0 -4px 8px rgba(0,0,0,0.6);
  animation: floating-core 4s ease-in-out infinite;
}}
.crystal-ring {{
  position: absolute;
  width: 72px;
  height: 28px;
  border: 2px solid rgba(34, 211, 238, 0.4);
  border-radius: 50%;
  transform: rotate(-25deg);
  box-shadow: 0 0 12px var(--cyan-glow);
  animation: ring-spin 8s linear infinite;
}}

@keyframes floating-core {{
  0%, 100% {{ transform: translateY(0) scale(1); }}
  50% {{ transform: translateY(-7px) scale(1.04); }}
}}
@keyframes ring-spin {{
  0% {{ transform: rotate(-25deg) rotateY(0deg); }}
  100% {{ transform: rotate(-25deg) rotateY(360deg); }}
}}

.form-header-center {{
  text-align: center;
  margin-top: 4px;
}}
.form-header-center h3 {{
  font-size: 16px;
  font-weight: 850;
  letter-spacing: -0.01em;
  color: var(--ink);
}}
.form-selected-node {{
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}}
.badge-chosen-node {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--card-bg);
  border: 1px solid var(--border);
  color: var(--cyan);
  font-weight: 750;
}}

.magic-form {{
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}}
.form-item label {{
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 750;
  color: var(--ink-secondary);
}}
.form-item label .opt-tag {{
  font-weight: 400;
  color: var(--muted);
}}

.magic-input-wrap {{
  position: relative;
  border-radius: var(--radius-sm);
  overflow: hidden;
}}
.magic-input {{
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--card-bg);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
  outline: none;
  transition: all 0.2s ease;
}}
.magic-input::placeholder {{ color: var(--muted-dark); }}
.magic-input:focus {{
  border-color: var(--cyan);
  box-shadow: 0 0 0 3px var(--cyan-glow);
  background: var(--card-selected);
}}

.btn-generate-shimmer {{
  position: relative;
  width: 100%;
  height: 46px;
  margin-top: 4px;
  border: 1px solid rgba(167, 139, 250, 0.45);
  border-radius: var(--radius-sm);
  background: linear-gradient(110deg, #6d28d9, #7c3aed 45%, #0891b2);
  background-size: 200% 100%;
  box-shadow: 0 12px 28px var(--violet-glow);
  color: #fff;
  font: inherit;
  font-size: 13.5px;
  font-weight: 800;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}}
.btn-generate-shimmer:before {{
  content: "";
  position: absolute;
  inset: -2px auto -2px -45%;
  width: 35%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.45), transparent);
  transform: skewX(-20deg);
  animation: shimmer-btn 3.5s infinite ease-in-out;
}}
.btn-generate-shimmer:hover {{
  transform: translateY(-2px);
  box-shadow: 0 16px 36px var(--violet-glow), 0 0 22px var(--cyan-glow);
}}

@keyframes shimmer-btn {{
  0%, 60% {{ left: -45%; }}
  100% {{ left: 130%; }}
}}

.form-footnote {{
  margin-top: 14px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--muted-dark);
  text-align: center;
}}

.result-box {{
  margin-bottom: 24px;
  padding: 20px 24px;
  border: 1px solid rgba(52, 211, 153, 0.4);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: 0 16px 40px rgba(16, 185, 129, 0.09), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
}}
.result-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}}
.result-status-title {{
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}}
.badge-success-glow {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 11px;
  border-radius: 999px;
  background: var(--emerald-bg);
  border: 1px solid rgba(52, 211, 153, 0.45);
  color: var(--emerald);
  font-size: 12px;
  font-weight: 800;
}}
.result-node-info {{
  font-size: 12px;
  color: var(--muted);
}}
.result-node-info code {{
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--card-bg);
  color: var(--cyan);
  font-family: ui-monospace, monospace;
}}
.result-label {{
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 750;
  color: var(--ink-secondary);
}}
.copy-field-wrap {{
  display: flex;
  gap: 10px;
}}
.copy-field-wrap input {{
  flex: 1;
  height: 44px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--card-bg);
  color: var(--cyan);
  font-family: ui-monospace, monospace;
  font-size: 13px;
  font-weight: 750;
  outline: none;
}}
.btn-copy-magic {{
  flex: 0 0 auto;
  height: 44px;
  padding: 0 20px;
  border: 1px solid rgba(34, 211, 238, 0.4);
  border-radius: var(--radius-sm);
  background: rgba(34, 211, 238, 0.12);
  color: var(--cyan);
  font: inherit;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.18s ease;
}}
.btn-copy-magic:hover {{
  background: var(--cyan);
  color: #040711;
  box-shadow: 0 0 20px var(--cyan-glow);
}}
.result-hint {{
  margin-top: 8px;
  font-size: 11px;
  color: var(--muted);
}}

.alert-error-box {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 24px;
  padding: 16px 20px;
  border: 1px solid rgba(251, 113, 133, 0.35);
  border-radius: var(--radius-panel);
  background: var(--danger-bg);
  color: var(--danger);
}}
.alert-error-icon {{ font-size: 18px; line-height: 1; }}
.alert-error-text strong {{ display: block; margin-bottom: 2px; font-size: 13px; }}
.alert-error-text span {{ font-size: 12px; }}

.my-routes-box {{
  position: relative;
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
}}
.routes-table-wrap {{
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-top: 10px;
}}
.magic-data-table {{
  width: 100%;
  min-width: 820px;
  border-collapse: separate;
  border-spacing: 0 8px;
}}
.magic-data-table th {{
  padding: 8px 12px;
  border: 0;
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: left;
}}
.magic-data-table td {{
  padding: 12px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: var(--card-bg);
  color: var(--ink-secondary);
  font-size: 13px;
  vertical-align: middle;
  transition: background 0.18s ease, border-color 0.18s ease;
}}
.magic-data-table td:first-child {{
  border-left: 1px solid var(--border);
  border-radius: 12px 0 0 12px;
}}
.magic-data-table td:last-child {{
  border-right: 1px solid var(--border);
  border-radius: 0 12px 12px 0;
}}
.magic-data-table tr.route-row:hover td {{
  border-color: var(--border-hover);
  background: var(--card-hover);
}}

.url-badge {{
  display: inline-block;
  max-width: 220px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: middle;
}}
.url-badge.origin-url {{ color: var(--muted); }}
.url-badge.public-url {{ color: var(--cyan); font-weight: 700; }}

.copy-flex-cell {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.btn-table-copy {{
  flex: 0 0 auto;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--card-bg);
  color: var(--ink-secondary);
  font: inherit;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.15s ease;
}}
.btn-table-copy:hover {{
  border-color: var(--cyan);
  color: var(--cyan);
}}

.node-tag-pill {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: rgba(148, 163, 184, 0.08);
  font-size: 11px;
  font-weight: 750;
  color: var(--ink);
}}

.status-pill {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 750;
}}
.status-pill .pulse-dot {{
  width: 5px; height: 5px;
  border-radius: 50%;
  background: currentColor;
}}
.status-pill.state-active {{ background: var(--emerald-bg); color: var(--emerald); }}
.status-pill.state-failed {{ background: var(--danger-bg); color: var(--danger); }}
.status-pill.state-paused {{ background: rgba(148, 163, 184, 0.12); color: var(--muted); }}
.route-error-msg {{ margin-top: 3px; font-size: 11px; color: var(--danger); }}

.col-note {{ min-width: 140px; }}
.note-view-box {{ display: inline-flex; align-items: center; gap: 6px; }}
.note-text {{ max-width: 140px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--ink); font-size: 12px; }}
.note-text.empty-note {{ color: var(--muted-dark); }}
.btn-note-edit {{
  display: grid;
  place-items: center;
  width: 22px; height: 22px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}}
.btn-note-edit:hover {{ border-color: var(--violet); color: var(--violet); }}
.note-inline-form {{ display: none; align-items: center; gap: 5px; }}
.note-inline-form.is-open {{ display: flex; }}
.note-inline-form input {{
  width: 110px; height: 26px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--card-bg);
  color: var(--ink);
  font-size: 11px;
}}
.btn-note-save {{
  height: 26px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  background: var(--violet);
  color: #fff;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
}}
.btn-note-cancel {{
  height: 26px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}}

.btn-table-delete {{
  height: 28px;
  padding: 0 10px;
  border: 1px solid rgba(251, 113, 133, 0.3);
  border-radius: 6px;
  background: var(--danger-bg);
  color: var(--danger);
  font: inherit;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.15s ease;
}}
.btn-table-delete:hover {{
  background: var(--danger);
  color: #fff;
}}

.table-empty-box {{
  padding: 40px 16px;
  text-align: center;
  color: var(--muted);
}}
.empty-sparkle {{
  font-size: 24px;
  color: var(--violet);
  margin-bottom: 6px;
}}

@media (max-width: 960px) {{
  .hero-dashboard {{ grid-template-columns: 1fr; }}
  .magic-workspace {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 640px) {{
  .magic-shell {{ padding: 14px 12px 40px; }}
  .magic-nav {{ padding: 10px 12px; }}
  .komari-globe-card, .metric-tile, .bento-nodes-box, .route-creation-card, .my-routes-box {{ padding: 16px 14px; }}
  .metrics-grid {{ grid-template-columns: 1fr; }}
  .node-grid {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }}
  .node-card {{ min-height: 110px; padding: 10px; }}
  .nav-badge.status {{ display: none; }}
  .globe-stage-wrapper {{ height: 160px; }}
  #komari-globe-canvas {{ height: 160px; }}
}}
</style>
</head>
<body data-theme="dark">

<div class="aurora-bg">
  <div class="aurora-blob blob-1"></div>
  <div class="aurora-blob blob-2"></div>
  <div class="aurora-blob blob-3"></div>
</div>
<div class="grid-mesh"></div>

<main class="magic-shell">
  <header class="magic-nav">
    <a href="/" class="nav-brand">
      <span class="brand-gem">✦</span>
      <div class="brand-meta">
        <strong>Emby Relay</strong>
        <small>全球智能媒体中继</small>
      </div>
    </a>
    <div class="nav-actions">
      <span class="nav-badge user">👤 {html.escape(user['username'])}</span>
      <span class="nav-badge quota">🗂 线路 <b>{used_routes}</b>/{route_quota}</span>
      <span class="nav-badge status"><i class="dot"></i>{html.escape(expiry_label)}</span>
      <button type="button" class="nav-btn-icon" id="user-theme-toggle" title="切换深色/浅色主题" aria-label="切换主题">☼</button>
      <a class="nav-link-btn" href="/account">账号安全</a>
      {admin_link}
      <form method="post" action="/logout" style="margin:0">
        <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
        <button type="submit" class="btn-logout">退出</button>
      </form>
    </div>
  </header>

  <section class="hero-dashboard">
    <div class="komari-globe-card">
      <div class="globe-header">
        <div class="globe-title-group">
          <h3>🌐 全球中继节点态势 <span class="globe-live-tag"><i class="radar-ping"></i>LIVE 实时连通</span></h3>
          <p>已点亮当前连通节点，支持鼠标拖拽与惯性自转</p>
        </div>
      </div>
      
      <div class="globe-stage-wrapper">
        <canvas id="komari-globe-canvas" width="480" height="175"></canvas>
      </div>
    </div>

    <div class="metrics-grid">
      <div class="metric-tile">
        <div class="metric-tile-top">
          <span class="metric-tile-title">可用加速节点</span>
          <span class="metric-tile-icon">⚡</span>
        </div>
        <div class="metric-tile-val">{nodes_count} <span>Nodes</span></div>
        <div class="metric-tile-sub">● 全节点就绪</div>
      </div>

      <div class="metric-tile">
        <div class="metric-tile-top">
          <span class="metric-tile-title">平均中继延迟</span>
          <span class="metric-tile-icon">🛰️</span>
        </div>
        <div class="metric-tile-val" id="avg-latency-display">38 <span>ms</span></div>
        <div class="metric-tile-sub">▲ 毫秒极速中继</div>
      </div>

      <div class="metric-tile">
        <div class="metric-tile-top">
          <span class="metric-tile-title">特征清洗引擎</span>
          <span class="metric-tile-icon">🛡️</span>
        </div>
        <div class="metric-tile-val">100% <span>Clean</span></div>
        <div class="metric-tile-sub">● 双向隐私伪装</div>
      </div>

      <div class="metric-tile">
        <div class="metric-tile-top">
          <span class="metric-tile-title">我的配额使用</span>
          <span class="metric-tile-icon">🗂</span>
        </div>
        <div class="metric-tile-val">{used_routes} <span>/ {route_quota}</span></div>
        <div class="metric-tile-sub">● 随时删除释放</div>
      </div>
    </div>
  </section>

  <section class="magic-workspace">
    <div class="bento-nodes-box">
      <div class="box-header">
        <div class="box-header-title">
          <h2>✦ 选择加速节点</h2>
          <p>点击卡片选择节点，浏览器将实时探测各节点连接延迟与稳定性</p>
        </div>
        <button type="button" class="btn-probe-magic" id="test-nodes">⚡ 全节点测速</button>
      </div>

      <div class="node-grid" id="nodes">
        {node_cards}
      </div>
    </div>

    <div class="route-creation-card">
      <div>
        <div class="crystal-orb-stage">
          <div class="crystal-orb-wrapper">
            <div class="crystal-ring"></div>
            <div class="crystal-orb" id="crystal-orb-element"></div>
          </div>
          <div class="form-header-center">
            <h3>🚀 创建专属线路</h3>
            <div class="form-selected-node">
              已选节点：<span class="badge-chosen-node" id="selected-node-display">{html.escape(selected_node_name)}</span>
            </div>
          </div>
        </div>

        <form class="magic-form" method="post">
          <input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">
          <input type="hidden" name="node_id" id="node-id" value="{selected_node_id}">

          <div class="form-item">
            <label>源站地址 (Emby Server URL)</label>
            <div class="magic-input-wrap">
              <input class="magic-input" required name="url" placeholder="https://emby.domain.com:8096" value="{html.escape(raw_url)}">
            </div>
          </div>

          <div class="form-item">
            <label>线路备注 <span class="opt-tag">（可选）</span></label>
            <div class="magic-input-wrap">
              <input class="magic-input" name="route_note" maxlength="500" placeholder="例如：主力影视库、日漫专用" value="{html.escape(raw_route_note, quote=True)}">
            </div>
          </div>

          <button type="submit" class="btn-generate-shimmer">立即生成专属反代线路</button>
        </form>
      </div>

      <p class="form-footnote">💡 全链路清洗源站指纹与代理特征，保障隐私与高码率流畅播放体验。</p>
    </div>
  </section>

  {result_html}

  <section class="my-routes-box">
    <div class="box-header">
      <div class="box-header-title">
        <h2>🗂 我的反代线路</h2>
        <p>已创建的专属访问地址，删除后将实时释放配额</p>
      </div>
      <span class="nav-badge">共 {used_routes} 条</span>
    </div>

    <div class="routes-table-wrap">
      <table class="magic-data-table">
        <thead>
          <tr>
            <th>源站地址</th>
            <th>专属反代地址</th>
            <th>分配节点</th>
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

const REGION_GEO = {{
  'HK': {{ lat: 22.31, lng: 114.16, name: '香港', flag: '🇭🇰' }},
  'JP': {{ lat: 35.67, lng: 139.65, name: '日本', flag: '🇯🇵' }},
  'SG': {{ lat: 1.35,  lng: 103.81, name: '新加坡', flag: '🇸🇬' }},
  'TW': {{ lat: 25.03, lng: 121.56, name: '台湾', flag: '🇹🇼' }},
  'US': {{ lat: 37.77, lng: -122.41, name: '美国', flag: '🇺🇸' }},
  'KR': {{ lat: 37.56, lng: 126.97, name: '韩国', flag: '🇰🇷' }},
  'DE': {{ lat: 50.11, lng: 8.68, name: '德国', flag: '🇩🇪' }},
  'GB': {{ lat: 51.50, lng: -0.12, name: '英国', flag: '🇬🇧' }}
}};

const CLIENT_HUB = {{ lat: 31.23, lng: 121.47, name: '客户端' }};

function resolveNodeGeo(node) {{
  const code = (node.code || '').toUpperCase();
  const cName = node.country_name || '';
  for (const [k, v] of Object.entries(REGION_GEO)) {{
    if (code.includes(k) || cName.includes(v.name)) {{
      return {{ ...v, id: node.id, nodeName: node.name }};
    }}
  }}
  return {{ lat: 20.0 + (node.id * 7) % 40, lng: 100.0 + (node.id * 15) % 60, name: cName || node.name, flag: '🌐', id: node.id, nodeName: node.name }};
}}

const activeNodeGeos = nodes.map(resolveNodeGeo);

const regionOrbStyles = {{
  hk: 'radial-gradient(circle at 35% 30%, #fff 2%, #a855f7 35%, #ec4899 75%, #05060f 100%)',
  jp: 'radial-gradient(circle at 35% 30%, #fff 2%, #38bdf8 35%, #ec4899 75%, #05060f 100%)',
  sg: 'radial-gradient(circle at 35% 30%, #fff 2%, #34d399 35%, #0891b2 75%, #05060f 100%)',
  tw: 'radial-gradient(circle at 35% 30%, #fff 2%, #f59e0b 35%, #ef4444 75%, #05060f 100%)',
  us: 'radial-gradient(circle at 35% 30%, #fff 2%, #60a5fa 35%, #8b5cf6 75%, #05060f 100%)',
  global: 'radial-gradient(circle at 35% 30%, #fff 2%, #22d3ee 35%, #8b5cf6 75%, #05060f 100%)'
}};

let globeTargetLng = 114.16;

function pick(id) {{
  selected = id;
  const nodeInput = document.getElementById('node-id');
  if (nodeInput) nodeInput.value = id;
  
  let chosenName = '未选择';
  let countryName = '';
  document.querySelectorAll('.node-card').forEach(card => {{
    const active = Number(card.dataset.nodeId) === id;
    card.classList.toggle('selected', active);
    card.setAttribute('aria-pressed', String(active));
    if (active) {{
      chosenName = card.dataset.nodeName || ('节点 #' + id);
      countryName = card.dataset.country || '';
    }}
  }});
  
  const displayEl = document.getElementById('selected-node-display');
  if (displayEl) {{
    displayEl.textContent = chosenName;
  }}

  const targetGeo = activeNodeGeos.find(g => g.id === id);
  if (targetGeo) {{
    globeTargetLng = targetGeo.lng;
  }}

  const orbEl = document.getElementById('crystal-orb-element');
  if (orbEl) {{
    let key = 'global';
    if (countryName.includes('香港') || chosenName.toLowerCase().includes('hk')) key = 'hk';
    else if (countryName.includes('日本') || chosenName.toLowerCase().includes('jp')) key = 'jp';
    else if (countryName.includes('新加坡') || chosenName.toLowerCase().includes('sg')) key = 'sg';
    else if (countryName.includes('台湾') || chosenName.toLowerCase().includes('tw')) key = 'tw';
    else if (countryName.includes('美') || chosenName.toLowerCase().includes('us')) key = 'us';
    orbEl.style.background = regionOrbStyles[key] || regionOrbStyles.global;
  }}
}}

document.querySelectorAll('.node-card').forEach(card => {{
  card.addEventListener('mousemove', (e) => {{
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--mouse-x', (e.clientX - rect.left) + 'px');
    card.style.setProperty('--mouse-y', (e.clientY - rect.top) + 'px');
  }});
  card.addEventListener('click', () => pick(Number(card.dataset.nodeId)));
}});

// Komari Dot-Matrix 3D Globe Engine
(function initKomariGlobe() {{
  const canvas = document.getElementById('komari-globe-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  
  let width = canvas.width;
  let height = canvas.height;
  const cx = width / 2;
  const cy = height / 2 + 2;
  const R = 72;
  
  let rotX = 114.16;
  let rotY = 18.0;
  let isDragging = false;
  let lastMouseX = 0;
  let lastMouseY = 0;
  let flightProgress = 0;

  // Landmass bounding boxes
  const LAND_BOXES = [
    [10, 55, 65, 145],   // China, East Asia, Japan
    [-10, 25, 95, 145],  // SE Asia, Indonesia
    [35, 70, -10, 50],   // Europe
    [25, 65, -130, -65], // North America
    [-55, 15, -80, -35], // South America
    [-35, 35, -20, 50],  // Africa
    [-45, -10, 110, 155] // Australia
  ];

  function isLand(lat, lng) {{
    for (const [minLat, maxLat, minLng, maxLng] of LAND_BOXES) {{
      if (lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng) {{
        return true;
      }}
    }}
    return false;
  }}

  // Pre-generate Fibonacci Sphere Points
  const NUM_POINTS = 1600;
  const globePoints = [];
  const phi = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < NUM_POINTS; i++) {{
    const y = 1 - (i / (NUM_POINTS - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = phi * i;
    const x = Math.cos(theta) * r;
    const z = Math.sin(theta) * r;
    const lat = Math.asin(y) * (180 / Math.PI);
    const lng = Math.atan2(z, x) * (180 / Math.PI);
    globePoints.push({{ lat, lng, land: isLand(lat, lng) }});
  }}

  function project3D(lat, lng, rx, ry) {{
    const radLat = (lat * Math.PI) / 180;
    const radLng = ((lng - rx) * Math.PI) / 180;
    const radY = (ry * Math.PI) / 180;

    let x0 = Math.cos(radLat) * Math.sin(radLng);
    let y0 = Math.sin(radLat);
    let z0 = Math.cos(radLat) * Math.cos(radLng);

    // Rotate pitch (ry)
    let y1 = y0 * Math.cos(radY) - z0 * Math.sin(radY);
    let z1 = y0 * Math.sin(radY) + z0 * Math.cos(radY);
    let x1 = x0;

    return {{
      x: cx + R * x1,
      y: cy - R * y1,
      z: z1,
      visible: z1 > 0
    }};
  }}

  function render() {{
    ctx.clearRect(0, 0, width, height);

    if (!isDragging) {{
      rotX += 0.35;
      const diff = ((globeTargetLng - rotX) % 360 + 540) % 360 - 180;
      rotX += diff * 0.015;
    }}

    flightProgress = (flightProgress + 0.012) % 1;

    // Atmospheric Outer Glow
    const atmosGrad = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.35);
    atmosGrad.addColorStop(0, 'rgba(34, 211, 238, 0.22)');
    atmosGrad.addColorStop(0.45, 'rgba(139, 92, 246, 0.12)');
    atmosGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = atmosGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.35, 0, Math.PI * 2);
    ctx.fill();

    // Dark Glass Sphere Core
    const sphereGrad = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.35, 5, cx, cy, R);
    sphereGrad.addColorStop(0, 'rgba(23, 37, 84, 0.7)');
    sphereGrad.addColorStop(0.65, 'rgba(15, 23, 42, 0.92)');
    sphereGrad.addColorStop(1, 'rgba(2, 6, 23, 0.98)');
    ctx.fillStyle = sphereGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(34, 211, 238, 0.32)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Render Dot Matrix (Komari Point Cloud)
    for (let i = 0; i < NUM_POINTS; i++) {{
      const pt = globePoints[i];
      const p = project3D(pt.lat, pt.lng, rotX, rotY);
      if (!p.visible) continue;

      const alpha = p.z * (pt.land ? 0.85 : 0.15);
      const dotSize = pt.land ? (p.z > 0.6 ? 1.6 : 1.2) : 0.8;

      ctx.fillStyle = pt.land ? `rgba(34, 211, 238, ${{alpha}})` : `rgba(148, 163, 184, ${{alpha}})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, dotSize, 0, Math.PI * 2);
      ctx.fill();
    }}

    // Client Hub Origin (China)
    const clientP = project3D(CLIENT_HUB.lat, CLIENT_HUB.lng, rotX, rotY);
    if (clientP.visible) {{
      ctx.fillStyle = '#a855f7';
      ctx.shadowColor = '#a855f7';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(clientP.x, clientP.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }}

    // Active Connected Node Light Beams, Arcs & Ripples
    activeNodeGeos.forEach((geo) => {{
      const nodeP = project3D(geo.lat, geo.lng, rotX, rotY);
      const isChosen = geo.id === selected;

      // Draw 3D Arcs between Client & Node
      if (clientP.visible || nodeP.visible) {{
        const midLat = (CLIENT_HUB.lat + geo.lat) / 2 + 18;
        const midLng = (CLIENT_HUB.lng + geo.lng) / 2;
        const midP = project3D(midLat, midLng, rotX, rotY);

        ctx.strokeStyle = isChosen ? 'rgba(34, 211, 238, 0.95)' : 'rgba(139, 92, 246, 0.55)';
        ctx.lineWidth = isChosen ? 2.0 : 1.2;
        ctx.beginPath();
        ctx.moveTo(clientP.x, clientP.y);
        ctx.quadraticCurveTo(midP.x, midP.y, nodeP.x, nodeP.y);
        ctx.stroke();

        // Flying Photon Particle
        const t = (flightProgress + (geo.id * 0.22)) % 1;
        const px = (1 - t) * (1 - t) * clientP.x + 2 * (1 - t) * t * midP.x + t * t * nodeP.x;
        const py = (1 - t) * (1 - t) * clientP.y + 2 * (1 - t) * t * midP.y + t * t * nodeP.y;
        
        ctx.fillStyle = '#fff';
        ctx.shadowColor = '#22d3ee';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(px, py, isChosen ? 3.5 : 2.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }}

      // Vertical 3D Light Beam (Komari Pillar)
      if (nodeP.visible) {{
        const beamHeight = isChosen ? 26 : 18;
        const topY = nodeP.y - beamHeight * nodeP.z;
        const topX = nodeP.x;

        // Beam gradient
        const beamGrad = ctx.createLinearGradient(nodeP.x, nodeP.y, topX, topY);
        beamGrad.addColorStop(0, isChosen ? 'rgba(34, 211, 238, 0.9)' : 'rgba(52, 211, 153, 0.8)');
        beamGrad.addColorStop(1, 'rgba(255, 255, 255, 0.95)');
        
        ctx.strokeStyle = beamGrad;
        ctx.lineWidth = isChosen ? 2.5 : 1.8;
        ctx.beginPath();
        ctx.moveTo(nodeP.x, nodeP.y);
        ctx.lineTo(topX, topY);
        ctx.stroke();

        // Beam Top Glowing Head
        ctx.fillStyle = '#fff';
        ctx.shadowColor = isChosen ? '#22d3ee' : '#34d399';
        ctx.shadowBlur = isChosen ? 12 : 6;
        ctx.beginPath();
        ctx.arc(topX, topY, isChosen ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();

        // Pulse Ripple Ring on Sphere Base
        const rippleR = 4 + (flightProgress * 14);
        ctx.strokeStyle = `rgba(34, 211, 238, ${{Math.max(0, 1 - flightProgress)}})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.ellipse(nodeP.x, nodeP.y, rippleR, rippleR * 0.45, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Floating Node Flag & Name Label
        const labelText = `${{geo.flag}} ${{geo.name}}`;
        ctx.font = isChosen ? 'bold 11px sans-serif' : '10px sans-serif';
        const txtWidth = ctx.measureText(labelText).width;
        const lx = topX + 8;
        const ly = topY - 5;

        // Label Glass Capsule
        ctx.fillStyle = isChosen ? 'rgba(15, 23, 42, 0.85)' : 'rgba(15, 23, 42, 0.65)';
        ctx.strokeStyle = isChosen ? 'rgba(34, 211, 238, 0.75)' : 'rgba(148, 163, 184, 0.25)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(lx - 4, ly - 11, txtWidth + 8, 16, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = isChosen ? '#ffffff' : '#cbd5e1';
        ctx.fillText(labelText, lx, ly + 1);
      }}
    }});

    requestAnimationFrame(render);
  }}

  // Interactive Drag & Rotation Listeners
  canvas.addEventListener('mousedown', (e) => {{
    isDragging = true;
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  }});

  window.addEventListener('mousemove', (e) => {{
    if (!isDragging) return;
    const dx = e.clientX - lastMouseX;
    const dy = e.clientY - lastMouseY;
    rotX -= dx * 0.5;
    rotY = Math.max(-45, Math.min(45, rotY + dy * 0.5));
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  }});

  window.addEventListener('mouseup', () => {{
    isDragging = false;
  }});

  render();
}})();

const latencyRecords = [];

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
    latencyRecords.push(ms);
    if (ms < 120) {{
      badge.className = 'latency-badge fast';
    }} else if (ms < 280) {{
      badge.className = 'latency-badge medium';
    }} else {{
      badge.className = 'latency-badge slow';
    }}
    updateAvgLatency();
  }} catch (e) {{
    textEl.textContent = '超时';
    badge.className = 'latency-badge error';
  }}
}}

function updateAvgLatency() {{
  if (!latencyRecords.length) return;
  const avg = Math.round(latencyRecords.reduce((a, b) => a + b, 0) / latencyRecords.length);
  const avgEl = document.getElementById('avg-latency-display');
  if (avgEl) avgEl.innerHTML = avg + ' <span>ms</span>';
}}

function probeAll() {{
  latencyRecords.length = 0;
  nodes.forEach(probe);
}}
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
    }}, 1600);
  }});
}});

document.querySelectorAll('.col-note').forEach(cell => {{
  const view = cell.querySelector('.note-view-box');
  const form = cell.querySelector('.note-inline-form');
  const input = form?.querySelector('input[name="notes"]');
  cell.querySelector('.btn-note-edit')?.addEventListener('click', () => {{
    if (view) view.style.display = 'none';
    form?.classList.add('is-open');
    input?.focus();
    input?.select();
  }});
  cell.querySelector('.btn-note-cancel')?.addEventListener('click', () => {{
    form?.classList.remove('is-open');
    if (view) view.style.display = '';
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

