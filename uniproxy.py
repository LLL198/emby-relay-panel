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






WORLD_LAND_POLYGONS_JS = r'''const WORLD_LAND_POLYGONS = [[[[-59.57,-80.04],[-60.2,-81.0],[-62.2,-80.9],[-64.5,-80.9],[-65.7,-80.6],[-64.0,-80.3],[-61.9,-80.4],[-60.6,-79.6],[-59.6,-80.0]]],[[[-159.21,-79.5],[-161.1,-79.6],[-162.4,-79.3],[-163.7,-78.6],[-161.2,-78.4],[-159.5,-79.0],[-159.2,-79.5]]],[[[-45.15,-78.05],[-43.9,-78.5],[-43.4,-79.5],[-44.9,-80.3],[-46.5,-80.6],[-48.4,-80.8],[-50.5,-81.0],[-52.9,-81.0],[-54.2,-80.6],[-51.9,-80.0],[-50.4,-79.2],[-49.3,-78.5],[-48.1,-78.0],[-46.7,-77.8],[-45.1,-78.0]]],[[[-121.21,-73.5],[-119.9,-73.7],[-118.7,-73.5],[-120.2,-74.1],[-121.6,-74.0],[-122.6,-73.7],[-121.2,-73.5]]],[[[-125.56,-73.48],[-124.0,-73.9],[-125.9,-73.7],[-127.3,-73.5],[-125.6,-73.5]]],[[[-98.98,-71.93],[-97.9,-72.1],[-96.8,-72.0],[-98.2,-72.5],[-99.4,-72.4],[-100.8,-72.5],[-101.8,-72.3],[-100.4,-71.9],[-99.0,-71.9]]],[[[-68.45,-70.96],[-68.8,-72.2],[-70.0,-72.3],[-71.1,-72.5],[-72.4,-72.5],[-74.2,-72.4],[-75.0,-71.7],[-73.9,-71.3],[-72.1,-71.2],[-71.7,-69.5],[-70.2,-68.9],[-69.5,-69.6],[-68.7,-70.5],[-68.5,-71.0]]],[[[-180.0,-84.71],[-179.1,-84.1],[-177.3,-84.5],[-176.2,-84.1],[-174.4,-84.5],[-173.1,-84.1],[-169.9,-83.9],[-168.5,-84.2],[-167.0,-84.6],[-164.2,-84.8],[-161.9,-85.1],[-158.1,-85.4],[-155.2,-85.1],[-150.9,-85.3],[-148.5,-85.6],[-145.9,-85.3],[-143.1,-85.0],[-146.8,-84.5],[-150.1,-84.3],[-153.6,-83.7],[-153.0,-82.8],[-154.5,-81.8],[-156.8,-81.1],[-154.4,-81.2],[-152.1,-81.0],[-150.7,-81.3],[-148.9,-81.0],[-147.2,-80.7],[-148.1,-79.7],[-149.5,-79.4],[-151.6,-79.3],[-153.4,-79.2],[-155.3,-79.1],[-157.3,-78.4],[-158.4,-76.9],[-157.0,-77.3],[-155.3,-77.2],[-153.7,-77.1],[-151.3,-77.4],[-150.0,-77.2],[-148.8,-76.9],[-147.6,-76.6],[-146.1,-76.5],[-146.2,-75.4],[-144.9,-75.2],[-142.8,-75.3],[-141.6,-75.1],[-140.2,-75.1],[-138.9,-75.0],[-137.5,-74.7],[-136.4,-74.5],[-135.2,-74.3],[-133.8,-74.4],[-132.3,-74.3],[-130.9,-74.5],[-129.6,-74.5],[-128.2,-74.3],[-126.9,-74.4],[-125.4,-74.5],[-124.0,-74.5],[-122.6,-74.5],[-121.1,-74.5],[-119.7,-74.5],[-118.7,-74.2],[-117.5,-74.0],[-116.2,-74.2],[-115.0,-74.1],[-113.9,-73.7],[-113.0,-74.4],[-111.3,-74.4],[-110.1,-74.8],[-108.7,-74.9],[-107.6,-75.2],[-106.2,-75.1],[-104.9,-75.0],[-103.4,-75.0],[-102.0,-75.1],[-100.6,-75.3],[-101.2,-74.2],[-102.5,-74.1],[-103.3,-73.4],[-101.6,-72.8],[-100.3,-72.8],[-99.1,-72.9],[-98.1,-73.2],[-96.3,-73.6],[-95.0,-73.5],[-93.7,-73.3],[-92.4,-73.2],[-91.4,-73.4],[-90.1,-73.3],[-89.2,-72.6],[-87.3,-73.2],[-86.0,-73.1],[-83.9,-73.5],[-82.7,-73.6],[-81.5,-73.8],[-80.3,-73.1],[-79.3,-73.5],[-77.9,-73.4],[-76.9,-73.6],[-74.9,-73.9],[-73.8,-73.7],[-72.8,-73.4],[-71.6,-73.3],[-70.2,-73.2],[-68.9,-73.0],[-67.4,-72.5],[-67.6,-71.2],[-68.5,-70.1],[-68.0,-69.0],[-67.4,-68.2],[-67.2,-66.9],[-66.1,-66.2],[-64.6,-65.6],[-63.6,-64.9],[-62.0,-64.6],[-60.7,-64.1],[-59.2,-63.7],[-57.8,-63.3],[-58.6,-64.2],[-59.8,-64.2],[-61.3,-64.5],[-62.5,-65.1],[-62.1,-66.2],[-63.7,-66.5],[-64.9,-67.2],[-65.7,-68.0],[-64.8,-68.7],[-63.2,-69.2],[-62.6,-70.0],[-61.8,-70.7],[-61.4,-72.0],[-60.7,-73.2],[-61.4,-74.1],[-63.3,-74.6],[-64.3,-75.3],[-65.9,-75.6],[-67.2,-75.8],[-68.5,-76.0],[-69.8,-76.2],[-72.2,-76.7],[-74.0,-76.6],[-75.6,-76.7],[-77.2,-76.7],[-75.4,-77.3],[-74.3,-77.6],[-76.5,-78.1],[-77.9,-78.4],[-76.8,-79.5],[-75.4,-80.3],[-73.2,-80.4],[-71.4,-80.7],[-70.0,-81.0],[-68.2,-81.3],[-65.7,-81.5],[-63.2,-81.8],[-61.5,-82.0],[-59.7,-82.4],[-58.7,-82.8],[-57.0,-82.9],[-55.4,-82.6],[-53.6,-82.3],[-51.5,-82.0],[-49.8,-81.7],[-47.3,-81.7],[-44.8,-81.8],[-42.8,-82.1],[-40.8,-81.4],[-38.2,-81.3],[-36.3,-81.1],[-34.4,-80.9],[-32.3,-80.8],[-30.1,-80.6],[-28.6,-80.3],[-29.7,-79.6],[-31.6,-79.3],[-33.7,-79.5],[-35.6,-79.5],[-35.8,-78.3],[-33.9,-77.9],[-32.2,-77.7],[-31.0,-77.4],[-29.8,-77.1],[-28.9,-76.7],[-27.5,-76.5],[-26.2,-76.4],[-23.9,-76.2],[-22.5,-76.1],[-21.2,-75.9],[-20.0,-75.7],[-18.9,-75.4],[-17.5,-75.1],[-15.7,-74.5],[-16.1,-73.5],[-14.4,-73.0],[-13.3,-72.7],[-12.3,-72.4],[-11.0,-71.5],[-9.1,-71.3],[-7.4,-71.7],[-5.8,-71.0],[-4.3,-71.5],[-3.0,-71.3],[-1.8,-71.2],[-0.7,-71.2],[0.9,-71.3],[1.9,-71.1],[3.0,-71.0],[4.1,-70.8],[5.2,-70.6],[6.3,-70.5],[7.7,-69.9],[9.5,-70.0],[10.8,-70.8],[11.9,-70.6],[13.4,-70.0],[14.7,-70.0],[15.9,-70.0],[17.0,-69.9],[18.2,-69.9],[19.3,-69.9],[20.4,-70.0],[21.4,-70.1],[22.6,-70.7],[23.7,-70.5],[24.8,-70.5],[26.0,-70.5],[27.1,-70.5],[28.1,-70.3],[29.1,-70.2],[31.0,-69.8],[32.8,-69.4],[33.9,-68.5],[34.9,-68.7],[36.2,-69.2],[37.2,-69.2],[38.6,-69.8],[39.7,-69.5],[40.9,-68.9],[42.0,-68.6],[44.1,-68.3],[45.7,-67.8],[47.4,-67.7],[49.0,-67.1],[50.8,-66.9],[51.8,-66.2],[53.6,-65.9],[55.4,-65.9],[57.2,-66.2],[58.1,-67.0],[59.9,-67.4],[61.4,-68.0],[63.2,-67.8],[65.0,-67.6],[66.9,-67.9],[68.9,-67.9],[69.7,-69.0],[68.6,-69.9],[68.0,-70.7],[69.1,-70.7],[68.4,-71.4],[69.9,-72.3],[71.0,-72.1],[71.9,-71.3],[73.1,-70.7],[73.9,-69.9],[75.6,-69.7],[76.6,-69.6],[77.6,-69.5],[78.4,-68.7],[80.1,-68.1],[81.5,-67.5],[82.8,-67.2],[84.7,-67.2],[86.8,-67.2],[88.0,-66.2],[88.8,-67.0],[90.6,-67.2],[92.6,-67.2],[94.2,-67.1],[95.8,-67.4],[97.8,-67.2],[99.7,-67.2],[100.9,-66.6],[102.8,-65.6],[104.2,-66.0],[106.2,-66.9],[108.1,-67.0],[109.2,-66.8],[110.2,-66.7],[111.7,-66.1],[112.9,-66.1],[114.4,-66.1],[115.6,-66.7],[116.7,-66.7],[118.6,-67.2],[119.8,-67.3],[120.9,-67.2],[122.3,-66.6],[124.1,-66.6],[125.2,-66.7],[127.0,-66.6],[128.8,-66.8],[130.8,-66.4],[131.8,-66.4],[132.9,-66.4],[134.8,-66.2],[135.7,-65.6],[136.6,-66.8],[138.6,-66.9],[139.9,-66.9],[142.1,-66.8],[144.4,-66.8],[145.5,-66.9],[146.7,-67.9],[147.7,-68.1],[148.8,-68.4],[150.1,-68.6],[151.5,-68.7],[152.5,-68.9],[153.6,-68.9],[155.2,-68.8],[156.8,-69.4],[158.0,-69.5],[159.2,-69.6],[160.8,-70.2],[162.7,-70.7],[163.8,-70.7],[164.9,-70.8],[166.1,-70.8],[167.3,-70.8],[168.4,-71.0],[169.5,-71.2],[170.5,-71.4],[170.6,-72.4],[169.8,-73.2],[168.0,-73.8],[166.1,-74.4],[165.0,-75.2],[163.8,-75.9],[163.5,-77.1],[164.3,-77.8],[166.6,-78.3],[165.2,-78.9],[163.7,-79.1],[161.8,-79.2],[160.9,-79.7],[160.3,-80.6],[161.1,-81.3],[162.5,-82.1],[163.7,-82.4],[165.1,-82.7],[166.6,-83.0],[168.9,-83.3],[172.3,-84.0],[173.2,-84.4],[176.0,-84.2],[178.3,-84.5],[-180.0,-84.7]]],[[[-67.75,-53.85],[-66.5,-54.5],[-65.0,-54.7],[-66.5,-55.2],[-68.2,-55.6],[-69.2,-55.5],[-71.0,-55.0],[-72.3,-54.5],[-73.3,-54.0],[-74.7,-52.8],[-72.4,-53.7],[-71.1,-54.1],[-70.3,-52.9],[-69.3,-52.5],[-68.2,-53.1],[-67.8,-53.9]]],[[[-58.55,-51.1],[-59.4,-52.2],[-60.7,-52.3],[-60.0,-51.2],[-58.5,-51.1]]],[[[70.28,-49.71],[68.7,-49.8],[68.9,-48.6],[70.5,-49.1],[70.3,-49.7]]],[[[145.4,-40.79],[146.4,-41.1],[147.7,-40.8],[148.4,-42.1],[147.9,-43.2],[146.9,-43.6],[145.4,-42.7],[144.7,-41.2],[145.4,-40.8]]],[[[173.02,-40.92],[174.2,-41.4],[173.2,-43.0],[172.3,-43.9],[171.2,-44.9],[170.6,-45.9],[169.3,-46.6],[167.8,-46.3],[166.7,-46.2],[167.1,-45.1],[168.3,-44.1],[169.7,-43.6],[171.1,-42.5],[171.9,-41.5],[172.8,-40.5],[173.0,-40.9]]],[[[174.61,-36.16],[175.3,-37.2],[176.8,-37.9],[178.0,-37.6],[178.3,-38.6],[177.2,-39.1],[176.9,-40.1],[176.0,-41.3],[174.7,-41.3],[174.9,-39.9],[173.8,-39.5],[174.6,-38.8],[174.7,-37.4],[173.8,-36.1],[173.1,-35.2],[174.3,-35.3],[174.6,-36.2]]],[[[167.12,-22.16],[165.5,-21.7],[164.2,-20.4],[165.5,-20.8],[166.6,-21.7],[167.1,-22.2]]],[[[-180.0,-16.56],[179.4,-16.8],[-180.0,-16.1],[-180.0,-16.6]]],[[[167.8,-16.5],[167.5,-16.6],[167.2,-16.2],[167.2,-15.9],[167.8,-16.5]]],[[[50.06,-13.56],[50.2,-14.8],[50.2,-16.0],[49.5,-17.1],[49.0,-19.1],[48.5,-20.5],[47.9,-22.4],[47.5,-23.8],[47.1,-24.9],[45.4,-25.6],[44.0,-25.0],[43.7,-23.6],[43.2,-22.1],[43.9,-21.2],[44.4,-20.1],[44.2,-19.0],[44.0,-17.4],[44.5,-16.2],[45.5,-16.0],[46.9,-15.2],[47.7,-14.6],[48.3,-13.8],[48.9,-12.5],[50.1,-13.6]]],[[[143.56,-13.76],[144.6,-14.2],[145.4,-15.0],[145.5,-16.3],[146.2,-17.8],[146.4,-19.0],[147.5,-19.5],[148.8,-20.4],[149.7,-22.3],[150.7,-22.4],[150.9,-23.5],[152.1,-24.5],[152.9,-25.3],[153.2,-26.6],[153.6,-28.1],[153.3,-29.5],[153.1,-30.9],[152.4,-32.5],[151.3,-33.8],[150.7,-35.2],[150.1,-36.4],[150.0,-37.4],[148.3,-37.8],[147.4,-38.2],[146.3,-39.0],[144.9,-38.4],[143.6,-38.8],[142.2,-38.4],[140.6,-38.0],[139.8,-36.6],[139.1,-35.7],[138.2,-34.4],[136.8,-35.3],[137.5,-34.1],[137.8,-32.9],[137.0,-33.8],[136.0,-34.9],[135.2,-34.0],[134.1,-32.9],[133.0,-32.0],[131.3,-31.5],[129.5,-31.6],[128.2,-31.9],[127.1,-32.3],[125.1,-32.7],[124.0,-33.5],[122.8,-33.9],[121.3,-33.8],[119.9,-34.0],[119.0,-34.5],[118.0,-35.1],[116.6,-35.0],[115.6,-34.4],[115.7,-33.3],[115.8,-32.2],[115.2,-30.6],[115.0,-29.5],[114.6,-28.5],[114.0,-27.3],[113.3,-26.1],[113.7,-25.0],[113.5,-23.8],[113.7,-22.5],[114.7,-21.8],[116.0,-21.1],[117.2,-20.6],[118.2,-20.4],[119.2,-19.9],[120.9,-19.7],[121.7,-18.7],[122.3,-17.8],[123.0,-16.4],[123.9,-17.1],[124.4,-15.6],[125.2,-14.7],[126.1,-14.1],[127.1,-13.8],[128.4,-14.9],[129.6,-15.0],[129.9,-13.6],[130.6,-12.5],[131.7,-12.3],[132.6,-11.6],[134.4,-12.0],[135.9,-12.0],[136.9,-12.3],[136.3,-13.3],[135.8,-14.2],[136.3,-15.6],[137.6,-16.2],[138.6,-16.8],[140.2,-17.7],[141.1,-16.8],[141.4,-15.8],[141.6,-14.6],[141.7,-12.9],[141.9,-11.9],[142.5,-10.7],[142.9,-11.8],[143.5,-12.8],[143.6,-13.8]]],[[[162.1,-10.5],[162.4,-10.8],[161.7,-10.8],[161.3,-10.2],[161.9,-10.4],[162.1,-10.5]]],[[[120.71,-10.24],[119.0,-9.6],[120.4,-9.7],[120.7,-10.2]]],[[[124.44,-10.14],[125.0,-8.9],[126.0,-8.4],[127.3,-8.4],[125.9,-9.1],[124.4,-10.1]]],[[[117.9,-8.09],[119.1,-8.7],[118.0,-8.9],[116.7,-9.0],[117.6,-8.4],[117.9,-8.1]]],[[[122.9,-8.09],[121.2,-8.9],[119.9,-8.8],[121.3,-8.5],[122.9,-8.1]]],[[[159.88,-8.34],[158.6,-7.8],[159.6,-8.0],[159.9,-8.3]]],[[[108.62,-6.78],[110.5,-6.9],[112.6,-7.0],[114.5,-7.8],[115.7,-8.4],[114.6,-8.8],[113.5,-8.3],[111.5,-8.3],[109.4,-7.7],[108.3,-7.8],[106.5,-7.4],[105.4,-6.8],[106.0,-5.9],[107.3,-6.0],[108.5,-6.4],[108.6,-6.8]]],[[[155.88,-6.82],[154.7,-5.9],[156.0,-6.5],[155.9,-6.8]]],[[[151.98,-5.48],[150.8,-6.1],[149.7,-6.3],[148.3,-5.8],[149.3,-5.6],[150.1,-5.0],[151.7,-4.8],[152.0,-5.5]]],[[[127.2,-3.5],[126.9,-3.8],[126.2,-3.6],[126.0,-3.2],[127.0,-3.1],[127.2,-3.5]]],[[[130.47,-3.09],[129.2,-3.4],[127.9,-3.4],[129.4,-2.8],[130.5,-3.1]]],[[[153.14,-4.5],[152.4,-3.8],[151.4,-3.0],[152.6,-3.7],[153.1,-4.5]]],[[[134.14,-1.15],[134.4,-2.8],[135.5,-3.4],[136.3,-2.3],[137.4,-1.7],[139.2,-2.0],[141.0,-2.6],[142.7,-3.3],[144.6,-3.9],[145.8,-4.9],[147.7,-6.1],[147.2,-7.4],[148.1,-8.0],[148.7,-9.1],[150.0,-9.7],[150.7,-10.6],[148.9,-10.3],[147.9,-10.1],[146.6,-8.9],[144.7,-7.6],[143.3,-8.2],[142.6,-9.3],[141.0,-9.1],[140.1,-8.3],[138.9,-8.4],[137.6,-8.4],[138.7,-7.3],[138.4,-6.2],[136.0,-4.5],[133.7,-3.5],[132.0,-2.8],[133.1,-2.5],[131.8,-1.6],[130.5,-0.9],[131.9,-0.7],[134.0,-0.8],[134.1,-1.1]]],[[[125.24,1.42],[124.4,0.4],[122.7,0.4],[121.1,0.4],[120.0,-0.5],[120.9,-1.4],[123.3,-0.6],[122.4,-1.5],[122.5,-3.2],[123.2,-4.7],[122.6,-5.6],[122.7,-4.5],[121.7,-4.8],[120.9,-3.6],[120.4,-5.5],[119.4,-5.4],[119.5,-3.5],[118.8,-2.8],[119.3,-1.4],[119.8,0.1],[120.9,1.3],[122.9,0.9],[124.1,0.9],[125.1,1.6],[125.2,1.4]]],[[[128.69,1.13],[128.0,-0.2],[127.4,1.0],[127.9,2.2],[128.7,1.1]]],[[[105.82,-5.85],[104.7,-5.9],[103.9,-5.0],[102.6,-4.2],[101.4,-2.8],[100.1,-0.7],[99.3,0.2],[98.6,1.8],[97.7,2.5],[96.4,3.9],[95.4,5.0],[97.5,5.2],[98.4,4.3],[99.1,3.6],[100.6,2.1],[101.7,2.1],[102.5,1.4],[103.1,0.6],[103.4,-0.7],[104.4,-1.1],[104.9,-2.3],[106.1,-3.1],[105.9,-4.3],[105.8,-5.8]]],[[[117.87,1.83],[119.0,0.9],[117.8,0.8],[117.5,-0.8],[116.6,-1.5],[116.2,-4.0],[114.9,-4.1],[113.8,-3.4],[112.1,-3.5],[111.0,-3.0],[110.1,-1.6],[109.1,-0.5],[109.1,1.3],[110.4,1.7],[111.4,2.7],[113.0,3.1],[113.7,3.9],[114.6,4.9],[115.5,5.5],[116.7,6.9],[117.6,6.4],[118.3,5.7],[119.1,5.0],[117.9,4.1],[117.3,3.2],[118.0,2.3],[117.9,1.8]]],[[[126.38,8.41],[126.5,7.2],[125.4,6.8],[125.4,5.6],[124.2,6.2],[124.2,7.4],[122.8,7.5],[123.5,8.7],[124.6,8.5],[125.4,9.8],[126.3,8.8],[126.4,8.4]]],[[[81.22,6.2],[79.9,6.8],[79.7,8.2],[80.2,9.8],[81.3,8.6],[81.8,7.5],[81.6,6.5],[81.2,6.2]]],[[[-60.94,10.11],[-62.0,10.1],[-61.1,10.9],[-60.9,10.1]]],[[[123.98,10.28],[123.3,9.3],[122.4,9.7],[123.0,10.9],[124.1,11.2],[124.0,10.3]]],[[[118.5,9.32],[117.2,8.4],[118.4,9.7],[119.5,11.4],[119.0,10.0],[118.5,9.3]]],[[[121.88,11.89],[123.1,11.6],[122.0,10.4],[122.0,11.4],[121.9,11.9]]],[[[125.5,12.16],[125.8,11.1],[124.8,10.1],[124.3,11.5],[124.3,12.6],[125.5,12.2]]],[[[121.5,13.1],[121.3,12.2],[120.8,12.7],[120.3,13.5],[121.2,13.4],[121.5,13.1]]],[[[121.32,18.5],[122.3,18.2],[122.5,17.1],[121.7,15.9],[121.7,14.3],[122.7,14.3],[124.0,13.8],[124.1,12.5],[122.9,13.6],[121.1,13.6],[120.7,14.8],[119.9,16.4],[120.4,17.6],[121.3,18.5]]],[[[-76.9,17.87],[-78.3,18.2],[-76.9,18.4],[-76.9,17.9]]],[[[-72.58,19.87],[-70.8,19.9],[-69.8,19.3],[-68.8,19.0],[-69.6,18.4],[-70.7,18.4],[-71.4,17.6],[-72.4,18.2],[-73.5,18.2],[-72.3,18.7],[-73.4,19.6],[-72.6,19.9]]],[[[110.34,18.68],[108.7,18.5],[109.1,19.8],[110.2,20.1],[110.3,18.7]]],[[[-155.54,19.08],[-155.9,20.2],[-154.8,19.5],[-155.5,19.1]]],[[[-156.8,21.2],[-156.8,21.1],[-157.3,21.1],[-157.2,21.2],[-156.8,21.2]]],[[[-79.68,22.77],[-78.3,22.5],[-77.2,21.7],[-76.2,21.2],[-74.9,20.7],[-75.6,19.9],[-77.8,19.9],[-78.5,21.0],[-80.2,21.8],[-81.8,22.2],[-82.8,22.7],[-83.9,22.1],[-85.0,21.9],[-84.2,22.6],[-83.3,23.0],[-82.3,23.2],[-80.6,23.1],[-79.7,22.8]]],[[[121.18,22.79],[120.1,23.6],[120.7,24.5],[121.5,25.3],[121.2,22.8]]],[[[-77.8,26.6],[-78.9,26.4],[-79.0,26.8],[-78.5,26.9],[-77.8,26.8],[-77.8,26.6]]],[[[134.64,34.15],[134.2,33.2],[133.0,32.7],[132.9,34.1],[133.9,34.4],[134.6,34.1]]],[[[34.58,35.67],[33.0,34.6],[33.7,35.4],[34.6,35.7]]],[[[23.7,35.71],[25.0,35.4],[26.3,35.3],[24.7,34.9],[23.5,35.3],[23.7,35.7]]],[[[15.52,38.23],[15.3,37.1],[13.8,37.1],[12.4,37.6],[13.7,38.0],[14.8,38.1],[15.5,38.2]]],[[[9.21,41.21],[9.7,39.2],[8.4,39.2],[8.4,40.4],[9.2,41.2]]],[[[140.98,37.14],[140.8,35.8],[139.0,34.7],[137.2,34.6],[135.8,33.5],[135.1,34.6],[133.3,34.4],[132.2,33.9],[131.0,33.9],[132.0,33.1],[131.3,31.4],[130.2,31.4],[129.8,32.6],[130.4,33.6],[131.9,34.8],[134.6,35.7],[135.7,35.5],[136.7,37.3],[138.9,37.8],[140.1,39.4],[139.9,40.6],[141.4,41.4],[141.9,40.0],[141.0,38.2],[141.0,37.1]]],[[[9.56,42.15],[8.5,42.3],[9.4,43.0],[9.6,42.1]]],[[[143.91,44.17],[145.3,44.4],[145.5,43.3],[144.1,43.0],[143.2,42.0],[141.6,42.7],[141.1,41.6],[140.0,41.6],[140.3,43.3],[141.4,43.4],[141.7,44.8],[143.1,44.5],[143.9,44.2]]],[[[-63.66,46.55],[-62.0,46.4],[-64.1,46.4],[-63.7,46.5]]],[[[-61.81,49.11],[-63.6,49.4],[-64.5,49.9],[-62.9,49.7],[-61.8,49.3],[-61.8,49.1]]],[[[-123.51,48.51],[-125.7,48.8],[-126.8,49.5],[-128.1,50.0],[-126.7,50.4],[-125.4,50.0],[-123.9,49.1],[-123.5,48.5]]],[[[-56.13,50.69],[-56.8,49.8],[-55.5,49.9],[-54.5,49.6],[-53.5,49.2],[-53.0,48.2],[-53.1,46.7],[-54.2,46.8],[-55.4,46.9],[-56.2,47.6],[-57.3,47.6],[-59.3,47.6],[-58.4,49.1],[-57.4,50.7],[-55.9,51.6],[-56.1,50.7]]],[[[-132.71,54.04],[-132.1,53.0],[-131.2,52.2],[-132.2,52.6],[-133.1,53.4],[-132.7,54.0]]],[[[143.65,50.75],[144.7,49.0],[143.2,49.3],[142.6,47.9],[143.5,46.8],[142.1,46.0],[142.0,47.8],[141.9,48.9],[142.2,51.0],[141.6,51.9],[141.7,53.3],[142.6,53.8],[143.3,52.7],[143.7,50.8]]],[[[-6.79,52.26],[-8.6,51.7],[-10.0,51.8],[-9.2,52.9],[-9.7,53.9],[-8.3,54.7],[-6.7,55.2],[-5.7,54.6],[-6.0,53.1],[-6.8,52.3]]],[[[12.7,55.6],[12.1,54.8],[11.0,55.4],[10.9,55.8],[12.4,56.1],[12.7,55.6]]],[[[-153.01,57.12],[-154.0,56.7],[-154.7,57.5],[-153.2,58.0],[-152.1,57.6],[-153.0,57.1]]],[[[-3.0,58.63],[-4.1,57.5],[-3.0,57.7],[-2.0,57.7],[-3.1,56.0],[-2.1,55.9],[-1.1,54.6],[0.2,53.3],[1.7,52.7],[1.1,51.8],[0.6,50.8],[-0.8,50.8],[-2.5,50.5],[-3.6,50.2],[-5.2,50.0],[-4.3,51.2],[-5.3,52.0],[-4.2,52.3],[-4.6,53.5],[-3.1,53.4],[-3.6,54.6],[-4.8,54.8],[-5.0,55.8],[-6.2,56.8],[-5.8,57.8],[-5.0,58.6],[-3.0,58.6]]],[[[-165.58,59.91],[-166.8,59.9],[-165.7,60.3],[-165.6,59.9]]],[[[-81.9,62.71],[-83.1,62.2],[-81.9,62.9],[-81.9,62.7]]],[[[-171.73,63.78],[-170.5,63.7],[-168.7,63.3],[-170.3,63.2],[-171.6,63.3],[-171.7,63.8]]],[[[-85.16,65.66],[-83.9,65.1],[-82.8,64.8],[-81.6,64.5],[-80.1,63.7],[-82.5,63.6],[-84.1,63.6],[-85.5,63.0],[-87.2,63.5],[-86.3,64.0],[-85.9,65.7],[-85.2,65.7]]],[[[-14.51,66.46],[-13.6,65.1],[-14.9,64.4],[-17.8,63.7],[-20.0,63.6],[-22.8,64.0],[-21.8,64.4],[-24.0,64.9],[-22.2,65.1],[-24.3,65.6],[-22.1,66.4],[-20.6,65.7],[-19.1,66.3],[-17.8,66.0],[-16.2,66.5],[-14.5,66.5]]],[[[-75.87,67.15],[-77.0,67.1],[-76.8,68.2],[-75.1,68.0],[-75.9,67.2]]],[[[-180.0,68.96],[-177.6,68.2],[-174.9,67.2],[-174.3,66.3],[-171.9,66.9],[-169.9,66.0],[-170.9,65.5],[-172.5,65.4],[-172.9,64.2],[-174.7,64.6],[-176.0,64.9],[-177.2,65.5],[-178.4,65.4],[-179.9,65.9],[180.0,65.0],[178.7,64.5],[177.4,64.6],[178.3,64.1],[178.9,63.2],[177.4,62.5],[174.6,61.8],[172.2,61.0],[170.7,60.3],[168.9,60.6],[166.3,59.8],[164.9,59.7],[163.5,59.9],[162.0,58.2],[163.2,57.6],[163.1,56.2],[161.7,55.3],[160.4,54.4],[160.0,53.2],[158.5,53.0],[158.2,51.9],[156.8,51.0],[156.0,53.2],[155.4,55.4],[155.9,56.8],[156.8,57.4],[158.4,58.1],[160.2,59.3],[161.9,60.3],[163.7,61.1],[164.5,62.5],[163.3,62.5],[162.7,61.6],[160.1,60.5],[159.3,61.8],[156.7,61.4],[154.2,59.8],[155.0,59.1],[152.8,58.9],[151.3,58.8],[149.8,59.7],[148.6,59.2],[145.5,59.3],[142.2,59.0],[139.0,57.1],[135.1,54.7],[136.7,54.6],[138.2,53.8],[139.9,54.2],[141.3,53.1],[140.6,51.2],[140.5,50.0],[140.1,48.5],[138.6,47.0],[136.9,45.1],[135.5,44.0],[133.5,42.8],[132.3,43.3],[130.9,42.5],[130.0,41.9],[129.7,40.9],[128.6,40.2],[127.5,39.8],[128.3,38.6],[129.2,37.4],[129.5,35.6],[128.2,34.9],[126.5,34.4],[126.6,35.7],[126.1,36.7],[126.2,37.8],[125.0,38.0],[125.4,39.4],[124.3,39.9],[122.9,39.6],[121.0,38.9],[122.2,40.4],[120.8,40.6],[119.6,39.9],[118.0,39.2],[118.1,38.1],[118.9,37.5],[120.8,37.9],[121.7,37.5],[121.1,36.6],[119.7,35.6],[120.2,34.4],[120.6,33.4],[121.2,32.5],[121.9,31.7],[121.3,30.7],[122.1,29.8],[121.7,28.2],[120.4,27.1],[119.6,25.7],[118.7,24.6],[117.3,23.6],[115.9,22.8],[114.8,22.7],[113.8,22.6],[111.8,21.6],[110.8,21.4],[110.4,20.3],[109.6,21.0],[108.5,21.7],[106.7,20.7],[105.9,19.8],[106.4,18.0],[107.4,16.7],[108.3,16.1],[108.9,15.3],[109.3,13.4],[109.2,11.7],[108.4,11.0],[107.2,10.4],[106.4,9.5],[105.2,8.6],[105.1,9.9],[103.5,10.6],[102.6,12.2],[101.7,12.7],[101.0,13.4],[100.0,12.3],[99.5,10.8],[99.2,9.2],[100.3,8.3],[101.0,6.9],[102.1,6.2],[103.0,5.5],[103.4,4.2],[103.5,2.8],[104.2,1.6],[102.6,2.0],[101.4,2.8],[100.7,3.9],[100.2,5.3],[100.1,6.5],[99.5,7.3],[98.5,8.4],[98.5,9.9],[98.8,11.4],[98.5,13.1],[97.8,14.8],[97.6,16.1],[96.5,16.4],[95.4,15.7],[94.2,16.0],[94.5,17.3],[93.5,19.4],[92.4,20.7],[92.0,21.7],[91.4,22.8],[90.3,21.8],[89.0,22.1],[87.0,21.5],[86.5,20.1],[85.1,19.5],[83.9,18.3],[82.2,17.0],[80.8,15.9],[80.0,15.1],[80.2,13.8],[79.9,12.1],[79.9,10.4],[78.9,9.6],[77.9,8.2],[76.6,8.9],[76.1,10.3],[75.8,11.3],[74.9,12.7],[74.6,14.0],[73.5,16.0],[73.1,17.9],[72.8,19.2],[72.8,20.4],[71.2,20.8],[69.2,22.1],[68.2,23.7],[67.2,24.7],[66.4,25.4],[64.5,25.2],[62.9,25.2],[61.5,25.1],[59.6,25.4],[58.5,25.6],[57.4,25.7],[57.0,27.0],[55.7,27.0],[54.7,26.5],[53.5,26.8],[52.5,27.6],[51.5,27.9],[50.9,28.8],[50.1,30.1],[48.9,30.3],[48.2,29.5],[48.8,27.7],[50.1,26.7],[50.2,25.6],[50.8,24.8],[51.0,26.0],[51.4,24.6],[52.6,24.2],[54.0,24.1],[55.4,25.4],[56.4,26.4],[56.4,24.9],[57.4,23.9],[58.7,23.6],[59.5,22.7],[59.3,21.4],[58.5,20.4],[57.7,19.7],[56.6,18.6],[55.7,17.9],[54.8,16.9],[53.6,16.7],[52.4,16.4],[51.2,15.2],[49.6,14.7],[48.7,14.0],[47.4,13.6],[45.9,13.3],[45.0,12.7],[43.5,12.6],[43.2,13.8],[42.9,14.8],[42.8,15.9],[42.4,17.1],[41.2,18.7],[40.2,20.2],[39.1,21.3],[39.1,22.6],[38.5,23.7],[37.5,24.3],[36.9,25.6],[36.2,26.6],[35.1,28.1],[35.0,29.4],[34.4,28.3],[33.1,28.4],[32.4,29.9],[32.7,28.7],[33.4,27.7],[34.1,26.1],[34.8,25.0],[35.7,23.9],[36.7,22.2],[37.2,21.0],[37.1,19.8],[37.5,18.6],[38.4,18.0],[39.0,16.8],[39.8,15.4],[41.2,14.5],[42.3,13.3],[43.3,12.4],[43.5,11.3],[44.1,10.4],[45.6,10.7],[46.6,10.8],[48.0,11.2],[49.3,11.4],[50.3,11.7],[51.0,10.6],[50.5,9.2],[50.1,8.1],[49.5,6.8],[48.6,5.3],[47.7,4.2],[46.6,2.9],[45.6,2.0],[44.1,1.1],[43.1,0.3],[42.0,-0.9],[40.9,-2.1],[40.1,-3.3],[39.6,-4.3],[38.7,-5.9],[39.4,-6.8],[39.2,-8.0],[39.5,-9.1],[40.0,-10.1],[40.4,-11.8],[40.6,-14.2],[40.5,-15.4],[39.5,-16.7],[38.5,-17.1],[37.4,-17.6],[36.3,-18.7],[35.2,-19.6],[34.7,-20.5],[35.4,-21.8],[35.5,-23.1],[35.5,-24.1],[34.2,-24.8],[33.0,-25.4],[32.8,-26.7],[32.5,-28.3],[31.5,-29.3],[30.6,-30.4],[28.9,-32.2],[27.5,-33.2],[26.4,-33.6],[25.2,-33.8],[23.6,-33.8],[22.6,-33.9],[21.5,-34.3],[20.1,-34.8],[18.9,-34.4],[18.2,-33.3],[18.2,-31.7],[17.6,-30.7],[16.4,-28.6],[15.6,-27.8],[15.0,-26.1],[14.4,-23.9],[14.4,-22.7],[13.9,-21.7],[12.8,-19.7],[11.8,-18.1],[11.6,-16.7],[12.1,-14.9],[12.5,-13.6],[13.3,-12.5],[13.7,-11.3],[13.1,-9.8],[13.2,-8.6],[12.9,-7.6],[12.2,-6.3],[11.9,-5.0],[11.1,-4.0],[10.1,-3.0],[9.4,-2.1],[8.8,-1.1],[9.3,0.3],[9.7,2.3],[9.4,3.7],[8.5,4.5],[7.5,4.4],[5.9,4.3],[5.0,5.6],[3.6,6.3],[1.9,6.1],[-0.5,5.3],[-2.0,4.7],[-3.3,5.0],[-4.7,5.2],[-5.8,5.0],[-7.5,4.3],[-9.0,4.8],[-9.9,5.6],[-10.8,6.1],[-11.7,6.9],[-12.9,7.8],[-13.2,8.9],[-14.1,9.9],[-14.8,10.9],[-15.7,11.5],[-16.6,12.2],[-16.7,13.6],[-17.6,14.7],[-16.7,15.6],[-16.6,16.7],[-16.1,18.1],[-16.3,19.1],[-16.5,20.6],[-17.0,21.9],[-16.3,22.7],[-16.0,23.7],[-15.1,24.5],[-14.8,25.6],[-13.8,26.6],[-13.1,27.6],[-11.7,28.1],[-10.9,28.8],[-9.6,29.9],[-9.8,31.2],[-9.3,32.6],[-7.7,33.7],[-6.2,35.1],[-5.2,35.8],[-3.6,35.4],[-2.6,35.2],[-1.2,35.7],[-0.1,35.9],[1.5,36.6],[3.2,36.8],[4.8,36.9],[6.3,37.1],[7.3,37.1],[8.4,37.0],[9.5,37.4],[11.0,37.1],[10.6,36.0],[10.8,34.8],[10.3,33.8],[11.5,33.1],[12.7,32.8],[13.9,32.7],[15.2,32.3],[15.7,31.4],[18.0,30.8],[19.1,30.3],[20.1,31.0],[20.1,32.2],[21.5,32.8],[22.9,32.6],[23.9,32.0],[24.9,31.9],[26.5,31.6],[27.5,31.3],[28.9,30.9],[30.1,31.5],[31.7,31.4],[33.0,31.0],[34.3,31.2],[35.0,32.8],[35.5,33.9],[35.9,35.4],[36.2,36.6],[34.7,36.8],[32.5,36.1],[30.6,36.7],[29.7,36.1],[28.7,36.7],[27.6,36.7],[27.1,37.6],[26.8,39.0],[27.3,40.4],[28.8,40.5],[31.1,41.1],[32.4,41.7],[33.5,42.0],[35.2,42.0],[36.9,41.3],[38.4,41.0],[39.5,41.1],[41.5,41.5],[41.5,42.6],[40.3,43.1],[38.7,44.3],[37.5,44.7],[38.2,46.2],[39.1,47.0],[37.4,47.0],[35.8,46.6],[35.0,45.6],[36.5,45.5],[35.2,44.9],[33.9,44.4],[32.5,45.3],[33.6,45.9],[31.7,46.3],[30.4,46.0],[29.6,45.3],[28.6,43.7],[27.7,42.6],[28.1,41.6],[27.2,40.7],[26.4,40.1],[25.4,40.9],[23.7,40.7],[22.6,40.3],[23.4,39.2],[24.0,38.2],[22.8,37.3],[21.7,36.9],[21.1,38.3],[20.2,39.3],[19.4,40.2],[19.4,41.4],[18.9,42.3],[17.5,42.9],[16.0,43.5],[15.2,44.2],[14.3,45.2],[13.1,45.7],[12.4,44.9],[13.5,43.6],[15.1,42.0],[16.2,41.7],[17.5,40.9],[18.4,40.4],[16.9,40.4],[17.2,39.4],[16.1,38.0],[15.7,39.5],[14.7,40.6],[13.6,41.2],[12.1,41.7],[11.2,42.4],[10.2,43.9],[8.9,44.4],[7.8,43.8],[6.5,43.1],[4.6,43.4],[3.1,43.1],[3.0,41.9],[2.1,41.2],[0.8,41.0],[0.1,40.1],[0.1,38.7],[-0.7,37.6],[-2.1,36.7],[-3.4,36.7],[-5.0,36.3],[-6.2,36.4],[-7.5,37.1],[-8.9,36.9],[-8.8,38.3],[-9.4,39.4],[-8.8,40.8],[-9.0,41.9],[-9.4,43.0],[-8.0,43.8],[-6.8,43.6],[-5.4,43.6],[-4.3,43.4],[-1.9,43.4],[-1.2,46.0],[-2.2,47.1],[-4.5,48.0],[-3.3,48.9],[-1.6,48.6],[-1.9,49.8],[-1.0,49.4],[1.3,50.1],[2.5,51.1],[3.8,51.6],[4.7,53.1],[6.1,53.5],[7.1,53.7],[8.1,53.5],[8.6,54.4],[8.1,55.5],[8.1,56.5],[9.4,57.2],[10.6,57.7],[10.4,56.6],[9.7,55.5],[10.9,54.4],[12.0,54.2],[13.7,54.1],[14.8,54.0],[16.4,54.5],[17.6,54.9],[18.6,54.7],[19.7,54.4],[21.3,55.2],[21.1,56.8],[22.5,57.8],[23.3,57.0],[24.3,57.8],[23.4,58.6],[24.6,59.5],[25.9,59.6],[26.9,59.5],[28.0,59.5],[29.1,60.0],[28.1,60.5],[26.3,60.4],[24.5,60.1],[22.9,59.9],[21.3,60.7],[21.5,61.7],[21.1,62.6],[22.4,63.8],[24.7,64.9],[23.9,66.0],[22.2,65.7],[21.2,65.0],[19.8,63.6],[17.9,62.8],[17.1,61.3],[18.8,60.1],[17.9,59.0],[16.8,58.7],[16.4,57.0],[15.9,56.1],[14.7,56.2],[12.9,55.4],[11.8,57.4],[11.0,58.9],[8.4,58.3],[7.0,58.1],[5.7,58.6],[5.3,59.7],[5.0,62.0],[5.9,62.6],[8.6,63.5],[10.5,64.5],[12.4,65.9],[14.8,67.8],[16.4,68.6],[19.2,69.8],[21.4,70.3],[23.0,70.2],[24.6,71.0],[26.4,71.0],[28.2,71.2],[31.3,70.5],[30.0,70.2],[31.1,69.6],[32.1,69.9],[33.8,69.3],[36.5,69.1],[40.3,67.9],[41.1,66.8],[40.0,66.3],[38.4,66.0],[33.9,66.8],[34.8,65.9],[34.9,64.4],[36.2,64.1],[37.2,65.1],[39.6,64.5],[39.8,65.5],[42.1,66.5],[44.0,66.1],[43.7,67.3],[43.5,68.6],[46.2,68.2],[45.6,67.0],[47.9,66.9],[50.2,68.0],[53.7,68.9],[54.7,68.1],[57.3,68.5],[58.8,68.9],[59.9,68.3],[61.1,68.9],[60.0,69.5],[63.5,69.5],[64.9,69.2],[68.5,68.1],[68.2,69.1],[66.9,69.5],[66.7,70.7],[68.5,71.9],[69.2,72.8],[72.6,72.8],[71.8,71.4],[72.8,70.4],[72.6,69.0],[73.7,68.4],[71.3,66.3],[72.4,66.2],[73.9,66.8],[75.0,67.8],[74.9,69.0],[73.8,69.1],[74.4,70.6],[73.1,71.5],[74.9,72.1],[76.4,71.2],[77.6,72.3],[79.7,72.3],[81.5,71.8],[80.6,72.6],[80.5,73.7],[82.2,73.8],[84.7,73.8],[86.8,73.9],[87.2,75.1],[88.3,75.1],[90.3,75.6],[92.9,75.8],[95.9,76.1],[98.9,76.5],[100.8,76.4],[102.0,77.3],[104.3,77.7],[106.1,77.4],[104.7,77.1],[107.0,77.0],[108.2,76.7],[111.1,76.7],[113.3,76.2],[113.9,75.3],[112.8,75.0],[110.2,74.5],[112.1,73.8],[113.5,73.3],[115.6,73.8],[118.8,73.6],[123.2,73.0],[125.4,73.6],[127.0,73.6],[128.6,73.0],[128.5,72.0],[129.7,71.2],[131.3,70.8],[132.2,71.8],[133.9,71.4],[135.6,71.7],[137.5,71.3],[139.9,71.5],[139.2,72.4],[140.5,72.8],[149.5,72.2],[150.3,71.6],[153.0,70.8],[157.0,71.0],[159.0,70.9],[159.7,69.7],[160.9,69.4],[162.3,69.6],[164.1,69.7],[165.9,69.5],[167.8,69.6],[169.6,68.7],[170.8,69.0],[170.0,69.7],[173.6,69.8],[175.7,69.9],[178.6,69.4],[-180.0,69.0]],[[49.11,41.28],[50.1,40.5],[49.4,39.4],[48.9,38.3],[50.1,37.4],[52.3,36.7],[53.8,37.0],[53.9,39.0],[53.4,40.0],[52.9,40.9],[54.7,41.0],[53.7,42.1],[52.8,41.1],[52.7,42.4],[51.3,43.1],[50.9,44.0],[51.3,45.2],[53.0,45.3],[53.0,46.9],[51.2,47.0],[50.0,46.6],[48.6,45.8],[46.7,44.6],[47.6,43.7],[48.6,41.8],[49.1,41.3]]],[[[-95.65,69.11],[-97.6,69.1],[-99.8,69.4],[-98.2,70.1],[-97.2,69.9],[-96.3,69.5],[-95.7,69.1]]],[[[-180.0,71.5],[180.0,70.8],[178.9,70.8],[178.7,71.1],[-180.0,71.5]]],[[[-180.0,71.52],[-177.6,71.3],[-178.7,70.9],[-180.0,70.8],[-180.0,71.5]]],[[[-90.55,69.5],[-90.5,68.5],[-89.2,69.3],[-88.0,68.6],[-87.3,67.2],[-86.3,67.9],[-85.6,68.8],[-85.5,69.9],[-84.1,69.8],[-82.6,69.7],[-81.3,69.2],[-82.0,68.1],[-81.4,67.1],[-83.3,66.4],[-84.7,66.3],[-85.8,66.6],[-87.0,65.2],[-88.5,64.1],[-89.9,64.0],[-90.8,63.0],[-91.9,62.8],[-93.2,62.0],[-94.2,60.9],[-94.7,59.0],[-93.2,58.8],[-92.8,57.9],[-90.9,57.3],[-89.0,56.9],[-88.0,56.5],[-86.1,55.7],[-85.0,55.3],[-83.4,55.2],[-82.3,55.1],[-82.1,53.3],[-81.4,52.2],[-79.9,51.2],[-78.6,52.6],[-79.1,54.1],[-78.2,55.1],[-77.1,55.8],[-76.6,57.2],[-77.3,58.0],[-78.5,58.8],[-77.3,59.9],[-78.1,62.3],[-75.7,62.3],[-74.7,62.2],[-72.9,62.1],[-71.7,61.5],[-69.6,61.1],[-69.3,59.0],[-67.7,58.2],[-66.2,58.8],[-65.2,59.9],[-63.8,59.4],[-62.5,58.2],[-61.4,57.0],[-60.5,55.8],[-59.6,55.2],[-58.0,55.0],[-56.9,53.8],[-55.8,53.3],[-55.7,52.1],[-57.1,51.4],[-58.8,51.1],[-60.0,50.2],[-61.7,50.1],[-63.9,50.3],[-65.4,50.3],[-66.4,50.2],[-67.2,49.5],[-68.5,49.1],[-70.0,47.7],[-71.1,46.8],[-68.7,48.3],[-66.5,49.1],[-65.0,49.2],[-65.1,48.1],[-64.8,47.0],[-63.2,45.7],[-61.5,45.9],[-60.5,47.0],[-59.8,45.9],[-61.0,45.3],[-63.2,44.7],[-64.2,44.3],[-65.4,43.5],[-66.2,44.5],[-64.4,45.3],[-66.0,45.3],[-67.1,45.1],[-68.0,44.3],[-69.1,44.0],[-70.1,43.7],[-70.8,42.9],[-70.5,41.8],[-71.9,41.3],[-73.7,40.9],[-72.2,41.1],[-73.3,40.6],[-74.2,39.7],[-74.9,38.9],[-75.4,38.0],[-76.3,39.1],[-76.3,38.1],[-76.3,37.0],[-75.7,35.5],[-77.4,34.5],[-78.5,33.9],[-79.2,33.2],[-80.3,32.5],[-81.3,31.4],[-81.3,30.0],[-80.5,28.5],[-80.1,26.9],[-80.1,25.8],[-81.2,25.2],[-82.2,26.7],[-82.9,27.9],[-82.9,29.1],[-83.7,29.9],[-85.1,29.6],[-86.4,30.4],[-87.5,30.3],[-89.2,30.3],[-89.2,29.3],[-90.9,29.1],[-92.5,29.6],[-93.8,29.7],[-95.6,28.7],[-96.6,28.3],[-97.4,27.4],[-97.3,26.2],[-97.5,25.0],[-97.8,22.9],[-97.7,21.9],[-97.2,20.6],[-96.3,19.3],[-94.8,18.6],[-93.5,18.4],[-92.0,18.7],[-90.8,19.3],[-90.5,20.7],[-89.6,21.3],[-88.5,21.5],[-87.0,21.5],[-87.4,20.3],[-87.6,19.0],[-88.1,18.1],[-88.2,17.0],[-88.9,15.9],[-87.9,15.9],[-86.9,15.8],[-85.7,15.9],[-84.5,15.9],[-83.4,15.3],[-83.2,14.3],[-83.5,13.1],[-83.7,11.9],[-83.4,10.4],[-82.5,9.6],[-81.4,8.8],[-79.9,9.3],[-78.5,9.4],[-77.3,8.7],[-76.1,9.3],[-75.5,10.6],[-74.3,11.1],[-72.6,11.7],[-71.8,12.4],[-71.6,11.0],[-72.1,9.9],[-71.3,9.1],[-71.3,10.2],[-70.2,11.4],[-68.9,11.4],[-68.2,10.6],[-66.2,10.7],[-64.9,10.1],[-63.1,10.7],[-61.9,10.7],[-60.8,9.4],[-60.1,8.6],[-59.1,8.0],[-58.5,6.8],[-57.5,6.3],[-56.0,5.8],[-54.0,5.8],[-52.9,5.4],[-51.8,4.6],[-51.1,3.6],[-50.5,1.9],[-50.0,1.1],[-50.7,0.2],[-48.6,-0.2],[-48.6,-1.2],[-46.6,-0.9],[-44.9,-1.6],[-44.6,-2.7],[-43.4,-2.4],[-41.5,-2.9],[-40.0,-2.9],[-38.5,-3.7],[-37.2,-4.8],[-35.6,-5.2],[-34.9,-6.7],[-35.1,-9.0],[-37.0,-11.0],[-37.7,-12.2],[-38.4,-13.0],[-38.9,-15.7],[-39.2,-17.2],[-39.6,-18.3],[-39.8,-19.6],[-40.8,-20.9],[-41.0,-21.9],[-42.0,-23.0],[-43.1,-23.0],[-44.6,-23.4],[-46.5,-24.1],[-47.6,-24.9],[-48.5,-25.9],[-48.5,-27.2],[-48.7,-28.2],[-49.6,-29.2],[-50.7,-31.0],[-51.6,-31.8],[-52.7,-33.2],[-53.8,-34.4],[-54.9,-35.0],[-56.2,-34.9],[-57.1,-34.4],[-58.4,-33.9],[-57.2,-35.3],[-56.7,-36.4],[-57.8,-38.2],[-59.2,-38.7],[-61.2,-38.9],[-62.3,-38.8],[-62.3,-40.2],[-63.8,-41.2],[-64.7,-40.8],[-65.0,-42.1],[-63.8,-42.0],[-64.4,-42.9],[-65.3,-44.5],[-66.5,-45.0],[-67.6,-46.3],[-66.6,-47.0],[-66.0,-48.1],[-67.2,-48.7],[-67.8,-49.9],[-68.7,-50.3],[-68.8,-51.8],[-69.9,-52.5],[-70.8,-52.9],[-71.4,-53.9],[-72.6,-53.5],[-73.7,-52.8],[-75.0,-52.3],[-75.0,-51.0],[-75.6,-48.7],[-75.2,-47.7],[-74.1,-46.9],[-75.7,-46.6],[-74.7,-45.8],[-74.3,-44.1],[-73.2,-44.5],[-72.7,-42.4],[-73.7,-43.4],[-74.0,-41.8],[-73.7,-39.9],[-73.5,-38.3],[-73.6,-37.2],[-72.5,-35.5],[-71.9,-33.9],[-71.4,-32.4],[-71.7,-30.9],[-71.5,-28.9],[-70.9,-27.6],[-70.7,-25.7],[-70.4,-23.6],[-70.1,-21.4],[-70.2,-19.8],[-70.4,-18.4],[-71.4,-17.8],[-73.5,-16.4],[-75.2,-15.3],[-76.0,-14.7],[-76.3,-13.5],[-77.1,-12.2],[-78.1,-10.4],[-79.0,-8.4],[-79.8,-7.2],[-81.2,-6.1],[-81.4,-4.7],[-80.3,-3.4],[-80.0,-2.2],[-80.9,-1.1],[-80.0,0.4],[-78.9,1.4],[-78.4,2.6],[-77.5,3.3],[-77.3,4.7],[-77.3,5.8],[-77.9,7.2],[-78.4,8.1],[-79.1,9.0],[-80.2,8.3],[-80.4,7.3],[-81.5,7.7],[-82.4,8.3],[-83.5,8.4],[-84.3,9.5],[-85.3,9.8],[-85.7,10.8],[-86.5,11.8],[-87.7,12.9],[-88.8,13.3],[-89.8,13.5],[-91.2,13.9],[-92.2,14.5],[-93.4,15.6],[-94.7,16.2],[-96.0,15.8],[-97.3,15.9],[-99.0,16.6],[-100.8,17.2],[-101.9,17.9],[-103.5,18.3],[-105.0,19.3],[-105.7,20.4],[-105.3,21.4],[-106.0,22.8],[-106.9,23.8],[-107.9,24.6],[-109.3,25.6],[-109.8,26.7],[-110.6,27.9],[-111.8,28.5],[-112.8,30.0],[-113.2,31.2],[-114.2,31.5],[-114.7,30.2],[-113.6,29.1],[-112.8,27.8],[-111.6,26.7],[-111.3,25.7],[-110.7,24.8],[-109.8,23.8],[-110.0,22.8],[-111.0,24.0],[-112.2,24.7],[-112.3,26.0],[-113.5,26.8],[-114.5,27.1],[-114.2,28.1],[-114.9,29.3],[-115.9,30.2],[-116.7,31.6],[-117.1,32.5],[-117.9,33.6],[-119.1,34.1],[-120.4,34.5],[-121.7,36.2],[-122.5,37.5],[-123.7,39.0],[-124.4,40.3],[-124.2,42.0],[-124.1,43.7],[-123.9,45.5],[-124.1,46.9],[-124.7,48.2],[-123.1,48.0],[-122.6,47.1],[-122.5,48.2],[-124.9,50.0],[-127.4,50.8],[-128.0,51.7],[-129.1,52.8],[-130.5,54.3],[-131.1,55.2],[-132.2,56.4],[-133.5,57.2],[-134.1,58.1],[-136.6,58.2],[-137.8,58.5],[-139.9,59.5],[-142.6,60.1],[-144.0,60.0],[-145.9,60.5],[-147.1,60.9],[-148.2,60.7],[-149.7,59.7],[-151.7,59.2],[-151.4,60.7],[-150.3,61.0],[-151.9,60.7],[-154.0,59.4],[-154.2,58.1],[-155.3,57.7],[-156.3,57.4],[-158.1,56.5],[-159.6,55.6],[-161.2,55.4],[-162.2,55.0],[-164.8,54.4],[-163.8,55.0],[-161.8,55.9],[-160.6,56.0],[-158.7,57.0],[-157.7,57.6],[-157.0,58.9],[-158.2,58.6],[-159.7,58.9],[-161.4,58.7],[-161.9,59.6],[-163.8,59.8],[-165.3,60.5],[-166.1,61.5],[-164.9,62.6],[-163.8,63.2],[-162.3,63.5],[-160.8,63.8],[-161.4,64.8],[-162.4,64.6],[-163.6,64.6],[-165.0,64.5],[-166.4,64.7],[-168.1,65.7],[-166.7,66.1],[-164.5,66.6],[-161.7,66.1],[-162.5,66.7],[-163.7,67.1],[-165.4,68.0],[-166.8,68.4],[-164.4,68.9],[-163.2,69.4],[-161.9,70.3],[-159.0,70.9],[-156.6,71.4],[-155.1,71.2],[-153.9,70.9],[-152.2,70.8],[-150.7,70.4],[-147.6,70.2],[-145.7,70.1],[-143.6,70.2],[-142.1,69.8],[-141.0,69.7],[-139.1,69.5],[-137.5,69.0],[-136.5,68.9],[-134.4,69.6],[-132.9,69.5],[-131.4,69.9],[-129.8,70.2],[-128.4,70.0],[-127.5,70.4],[-125.8,69.5],[-124.4,70.2],[-123.1,69.6],[-121.5,69.8],[-119.9,69.4],[-117.6,69.0],[-116.2,68.8],[-113.9,68.4],[-115.3,67.9],[-113.5,67.7],[-110.8,67.8],[-108.9,67.4],[-107.8,67.9],[-108.8,68.3],[-107.0,68.7],[-105.3,68.6],[-104.3,68.0],[-103.2,68.1],[-101.5,67.7],[-99.9,67.8],[-98.4,67.8],[-97.7,68.6],[-96.1,68.2],[-94.7,68.1],[-94.2,69.1],[-95.3,69.7],[-96.5,70.1],[-96.4,71.2],[-95.2,71.9],[-93.9,71.8],[-92.9,71.3],[-91.5,70.2],[-92.4,69.7],[-90.5,69.5]]],[[[-114.17,73.12],[-112.4,73.0],[-111.0,72.5],[-109.9,73.0],[-108.2,71.7],[-108.4,73.1],[-106.5,73.1],[-105.4,72.7],[-104.8,71.7],[-102.8,70.5],[-101.0,70.0],[-102.7,69.5],[-104.2,68.9],[-106.0,69.2],[-107.1,69.1],[-109.0,68.8],[-112.0,68.6],[-113.3,68.5],[-115.2,69.3],[-117.3,70.0],[-115.1,70.2],[-113.7,70.2],[-112.4,70.4],[-114.3,70.6],[-116.5,70.5],[-117.9,70.5],[-116.1,71.3],[-117.7,71.3],[-119.4,71.6],[-118.6,72.3],[-115.2,73.3],[-114.2,73.1]]],[[[-104.5,73.4],[-105.4,72.8],[-106.9,73.5],[-106.6,73.6],[-105.3,73.6],[-104.5,73.4]]],[[[-76.34,73.1],[-77.3,72.9],[-78.4,72.9],[-79.5,72.7],[-80.9,73.3],[-78.1,73.7],[-76.3,73.1]]],[[[-86.56,73.16],[-85.8,72.5],[-84.8,73.3],[-82.3,73.8],[-80.6,72.7],[-78.8,72.3],[-77.8,72.8],[-75.6,72.2],[-74.2,71.8],[-72.2,71.6],[-71.2,70.9],[-68.8,70.5],[-67.0,69.2],[-68.8,68.7],[-66.5,68.1],[-64.9,67.8],[-63.4,66.9],[-61.9,66.9],[-63.9,65.0],[-65.2,65.4],[-66.7,66.4],[-68.0,66.3],[-67.1,65.1],[-65.7,64.7],[-64.7,63.4],[-66.3,63.0],[-68.8,63.8],[-67.4,62.9],[-66.3,62.3],[-68.9,62.3],[-71.0,62.9],[-72.2,63.4],[-73.4,64.2],[-74.8,64.7],[-77.7,64.2],[-77.9,65.3],[-76.0,65.3],[-74.0,65.5],[-72.7,67.3],[-74.8,68.5],[-76.9,68.9],[-78.2,69.8],[-79.5,69.9],[-81.3,69.7],[-84.9,70.0],[-87.1,70.3],[-88.7,70.4],[-89.9,71.2],[-90.2,72.2],[-89.4,73.1],[-88.4,73.5],[-85.8,73.8],[-86.6,73.2]]],[[[-100.36,73.84],[-99.2,73.6],[-97.4,73.8],[-98.0,73.0],[-96.5,72.6],[-98.4,71.3],[-100.0,71.7],[-102.5,72.5],[-100.4,72.7],[-101.5,73.4],[-100.4,73.8]]],[[[143.6,73.21],[142.1,73.2],[140.0,73.3],[142.1,73.9],[143.5,73.5],[143.6,73.2]]],[[[-93.2,72.77],[-94.3,72.0],[-95.4,72.1],[-96.0,72.9],[-95.5,73.9],[-94.5,74.1],[-92.4,74.1],[-90.5,73.9],[-92.0,73.0],[-93.2,72.8]]],[[[-120.46,71.4],[-123.1,70.9],[-125.9,71.9],[-124.8,73.0],[-123.9,73.7],[-124.9,74.3],[-121.5,74.5],[-120.1,74.2],[-117.6,74.2],[-116.6,73.9],[-115.5,73.5],[-116.8,73.2],[-119.2,72.5],[-120.5,71.8],[-120.5,71.4]]],[[[150.73,75.08],[149.6,74.7],[148.0,74.8],[146.1,75.2],[148.2,75.3],[150.7,75.1]]],[[[-93.61,74.98],[-95.6,74.7],[-96.8,74.9],[-94.8,75.7],[-93.6,75.0]]],[[[145.09,75.56],[144.3,74.8],[140.6,74.8],[139.0,74.6],[137.0,75.3],[138.8,76.1],[141.5,76.1],[145.1,75.6]]],[[[-98.5,76.72],[-97.7,75.7],[-99.8,74.9],[-100.9,75.1],[-102.5,75.6],[-101.5,76.3],[-100.0,76.7],[-98.6,76.6],[-98.5,76.7]]],[[[-108.21,76.2],[-106.9,76.0],[-105.9,76.0],[-106.3,75.0],[-109.7,74.8],[-112.2,74.4],[-113.7,74.4],[-111.8,75.2],[-116.3,75.0],[-117.7,75.2],[-116.3,76.2],[-112.6,76.1],[-110.8,75.5],[-109.1,75.5],[-110.5,76.4],[-108.5,76.7],[-108.2,76.2]]],[[[57.53,70.72],[53.7,70.8],[51.6,71.5],[52.5,72.2],[54.4,73.6],[55.9,74.6],[57.9,75.6],[61.2,76.2],[64.5,76.4],[66.2,76.8],[68.2,76.9],[64.6,75.7],[61.6,75.3],[58.5,74.3],[57.0,73.3],[55.4,72.4],[57.5,70.7]]],[[[-94.68,77.1],[-93.6,76.8],[-91.6,76.8],[-89.8,75.8],[-87.8,75.6],[-86.4,75.5],[-84.8,75.7],[-82.8,75.8],[-81.1,75.7],[-80.1,75.3],[-82.0,74.4],[-83.2,74.6],[-86.1,74.4],[-88.2,74.4],[-89.8,74.5],[-92.4,74.8],[-92.9,75.9],[-93.9,76.3],[-96.0,76.4],[-97.1,76.8],[-94.7,77.1]]],[[[-116.2,77.65],[-117.1,76.5],[-119.9,76.0],[-121.5,75.9],[-122.9,76.1],[-121.2,76.9],[-119.1,77.5],[-117.6,77.5],[-116.2,77.7]]],[[[-93.84,77.52],[-96.2,77.6],[-94.4,77.8],[-93.8,77.5]]],[[[-110.19,77.7],[-112.0,77.4],[-113.5,77.7],[-111.3,78.2],[-109.8,78.0],[-110.2,77.7]]],[[[24.72,77.85],[22.5,77.5],[20.7,77.7],[22.9,78.5],[24.7,77.8]]],[[[-109.66,78.6],[-110.9,78.4],[-112.5,78.4],[-111.5,78.8],[-109.7,78.6]]],[[[-95.83,78.06],[-97.3,77.8],[-98.5,78.5],[-97.3,78.8],[-95.6,78.4],[-95.8,78.1]]],[[[-100.06,78.33],[-101.3,78.0],[-103.0,78.3],[-105.2,78.4],[-104.2,78.7],[-105.4,78.9],[-103.5,79.2],[-100.8,78.8],[-100.1,78.3]]],[[[105.08,78.31],[99.4,77.9],[101.3,79.2],[102.8,79.3],[105.4,78.7],[105.1,78.3]]],[[[18.25,79.7],[21.5,79.0],[19.0,78.6],[17.6,77.6],[15.9,76.8],[13.8,77.4],[11.2,78.9],[10.4,79.7],[13.2,80.0],[15.1,79.7],[17.0,80.0],[18.2,79.7]]],[[[25.45,80.41],[27.4,80.1],[25.9,79.5],[23.0,79.4],[20.1,79.6],[18.5,79.9],[17.4,80.3],[20.5,80.6],[21.9,80.4],[22.9,80.7],[25.4,80.4]]],[[[51.14,80.55],[49.8,80.4],[48.8,80.2],[47.6,80.0],[46.5,80.2],[44.9,80.6],[46.8,80.8],[48.3,80.8],[50.0,80.9],[51.5,80.7],[51.1,80.5]]],[[[99.94,78.88],[97.8,78.8],[95.0,79.0],[93.3,79.4],[92.5,80.1],[91.2,80.3],[93.8,81.0],[95.9,81.2],[97.9,80.8],[100.2,79.8],[99.9,78.9]]],[[[-87.02,79.66],[-85.8,79.3],[-87.2,79.0],[-89.0,78.3],[-90.8,78.2],[-92.9,78.3],[-94.0,78.8],[-93.2,79.4],[-95.0,79.4],[-96.1,79.7],[-95.3,80.9],[-94.3,81.0],[-92.4,81.3],[-91.1,80.7],[-89.5,80.5],[-87.8,80.3],[-87.0,79.7]]],[[[-68.5,83.11],[-65.8,83.0],[-63.7,82.9],[-61.9,82.6],[-64.3,81.9],[-66.8,81.7],[-65.5,81.5],[-67.8,80.9],[-69.5,80.6],[-71.2,79.8],[-73.2,79.6],[-76.9,79.3],[-75.5,79.2],[-76.3,78.2],[-77.9,77.9],[-79.8,77.2],[-77.9,77.0],[-80.6,76.2],[-83.2,76.5],[-86.1,76.3],[-87.6,76.4],[-89.5,76.5],[-87.8,77.2],[-85.0,77.5],[-86.3,78.2],[-88.0,78.4],[-85.4,79.0],[-86.5,79.7],[-84.2,80.2],[-81.8,80.5],[-84.1,80.6],[-87.6,80.5],[-89.4,80.9],[-91.4,81.5],[-90.1,82.1],[-88.9,82.1],[-87.0,82.3],[-85.5,82.7],[-84.3,82.6],[-83.2,82.3],[-81.1,83.0],[-79.3,83.1],[-76.2,83.2],[-72.8,83.2],[-70.7,83.2],[-68.5,83.1]]],[[[-27.1,83.52],[-20.9,82.7],[-22.7,82.3],[-26.5,82.3],[-31.9,82.2],[-27.9,82.1],[-24.9,81.8],[-22.9,82.1],[-20.6,81.5],[-15.8,81.9],[-12.8,81.7],[-16.3,80.6],[-20.1,80.2],[-17.7,80.1],[-18.9,79.4],[-19.7,78.8],[-19.7,77.6],[-18.5,77.0],[-20.0,76.9],[-21.7,76.6],[-19.8,76.1],[-20.7,75.2],[-19.4,74.3],[-21.6,74.2],[-20.4,73.8],[-22.2,73.3],[-23.6,73.3],[-22.3,72.6],[-24.3,72.6],[-23.4,72.1],[-22.1,71.5],[-23.5,70.5],[-25.5,71.4],[-26.4,70.2],[-23.7,70.2],[-22.4,70.1],[-25.0,69.3],[-27.8,68.5],[-30.7,68.1],[-31.8,68.1],[-32.8,67.7],[-34.2,66.7],[-36.4,66.0],[-38.4,65.7],[-39.8,65.5],[-40.7,64.8],[-41.2,63.5],[-42.8,62.7],[-42.9,61.1],[-43.4,60.1],[-44.8,60.0],[-46.3,60.9],[-48.3,60.9],[-49.2,61.4],[-49.9,62.4],[-51.6,63.6],[-52.3,65.2],[-53.7,66.1],[-54.0,67.2],[-53.0,68.4],[-51.5,68.7],[-50.9,69.9],[-52.0,69.6],[-53.5,69.3],[-54.7,69.6],[-54.4,70.8],[-51.4,70.6],[-53.1,71.2],[-55.0,71.4],[-54.7,72.6],[-56.1,73.7],[-57.3,74.7],[-58.6,75.1],[-61.3,76.1],[-63.4,76.2],[-66.1,76.1],[-68.5,76.1],[-69.7,76.4],[-71.4,77.0],[-68.8,77.3],[-66.8,77.4],[-71.0,77.6],[-73.3,78.0],[-69.4,78.9],[-65.7,79.4],[-68.0,80.1],[-63.7,81.2],[-62.2,81.3],[-60.3,82.0],[-57.2,82.2],[-54.1,82.2],[-53.0,81.9],[-50.4,82.4],[-48.0,82.1],[-46.6,82.0],[-44.5,81.7],[-46.9,82.2],[-43.4,83.2],[-39.9,83.2],[-38.6,83.5],[-35.1,83.7],[-27.1,83.5]]]];'''

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
    selected_node_host = "暂无加速地址"
    selected_node_country = "全球"
    selected_node_flag = "🌐"
    for n in nodes:
        if n["id"] == selected_node_id:
            selected_node_name = n["name"]
            selected_node_host = n.get("host") or "已就绪"
            selected_node_country = n.get("country_name") or n.get("code") or "全球"
            selected_node_flag = n.get("flag") or "🌐"
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
        node_host = node.get("host") or ""
        node_cards_parts.append(
            f"<button type='button' class='node-card{' selected' if is_selected else ''}' "
            f"data-node-id='{node['id']}' data-node-name='{html.escape(node['name'], quote=True)}' "
            f"data-country='{html.escape(node.get('country_name') or '')}' "
            f"data-host='{html.escape(node_host, quote=True)}' "
            f"data-flag='{html.escape(node.get('flag') or '🌐')}' "
            f"aria-pressed={'true' if is_selected else 'false'}>"
            f"  <div class='node-card-glow-follower'></div>"
            f"  <div class='node-card-top'>"
            f"    <div class='node-flag'>{node['flag_markup']}</div>"
            f"    <div class='node-info-group'>"
            f"      <span class='node-name' title='{html.escape(node['name'], quote=True)}'>{html.escape(node['name'])}</span>"
            f"      <span class='node-country-tag'>{html.escape(node.get('country_name') or meta_label)}</span>"
            f"    </div>"
            f"  </div>"
            f"  <div class='node-host-bar' title='加速地址: {html.escape(node_host, quote=True)}'>"
            f"    <span class='node-host-icon'>🏷️</span>"
            f"    <code class='node-host-text'>{html.escape(node_host)}</code>"
            f"  </div>"
            f"  <div class='node-card-sparkline'>"
            f"    <svg viewBox='0 0 160 28' class='sparkline-svg' preserveAspectRatio='none'>"
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
            f"      <path class='sparkline-area' fill='url(#spark-fill-{node['id']})' d='M0 20 Q 25 8, 50 15 T 100 6 T 160 12 L 160 28 L 0 28 Z'></path>"
            f"      <path class='sparkline-line' stroke='url(#spark-grad-{node['id']})' fill='none' stroke-width='2' d='M0 20 Q 25 8, 50 15 T 100 6 T 160 12'></path>"
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
    my_routes_html = "".join(route_rows) or "<tr><td colspan='6' class='table-empty-box'><div class='empty-sparkle'>✦</div><p>暂无反代线路，在下方选择节点并输入源站即可快速生成专属线路。</p></td></tr>"
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
  --panel-bg: rgba(255, 255, 255, 0.92);
  --panel-solid: #ffffff;
  --card-bg: rgba(241, 245, 252, 0.88);
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

/* Top Hero: Left Continents 3D Globe + Right 2 Metric Cards */
.hero-dashboard {{
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 20px;
  margin-bottom: 22px;
}}

.globe-card-hero {{
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 260px;
  padding: 20px 24px;
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
  height: 200px;
  margin: 4px 0 0;
}}
#globe-canvas {{
  width: 260px;
  height: 260px;
  max-width: 100%;
  cursor: grab;
  touch-action: none;
  filter: drop-shadow(0 0 24px rgba(34, 211, 238, 0.18));
}}
#globe-canvas:active {{
  cursor: grabbing;
}}

.hero-metrics-stack {{
  display: flex;
  flex-direction: column;
  gap: 14px;
  justify-content: space-between;
}}

.metric-tile-hero {{
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--panel-bg);
  box-shadow: var(--shadow-magic);
  backdrop-filter: blur(20px);
  flex: 1;
  transition: all 0.18s ease;
}}
.metric-tile-hero:hover {{
  transform: translateY(-2px);
  border-color: var(--border-hover);
  background: var(--card-hover);
}}

.metric-hero-left {{
  display: flex;
  flex-direction: column;
}}
.metric-hero-title {{
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}
.metric-hero-val {{
  margin-top: 6px;
  font-size: 26px;
  font-weight: 850;
  letter-spacing: -0.02em;
  color: var(--ink);
  line-height: 1.2;
}}
.metric-hero-val span {{
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  margin-left: 4px;
}}
.metric-hero-sub {{
  margin-top: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--emerald);
  display: flex;
  align-items: center;
  gap: 4px;
}}

.metric-hero-icon-box {{
  width: 50px;
  height: 50px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid rgba(34, 211, 238, 0.22);
  color: var(--cyan);
  font-size: 22px;
}}
.metric-hero-icon-box.quota-box {{
  background: rgba(139, 92, 246, 0.08);
  border-color: rgba(139, 92, 246, 0.22);
  color: var(--violet);
}}

/* Main Workspace: 3/4 Left Bento Nodes + 1/4 Right Clean Form */
.magic-workspace {{
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(310px, 1fr);
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
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}}

.node-card {{
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 142px;
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

.node-host-bar {{
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 6px 0 2px;
  padding: 3px 7px;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid var(--border);
  overflow: hidden;
}}
.node-host-icon {{ font-size: 10px; flex: 0 0 auto; }}
.node-host-text {{
  font-family: ui-monospace, monospace;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--cyan);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}

.node-card-sparkline {{
  position: relative;
  z-index: 1;
  width: 100%;
  height: 22px;
  margin: 4px 0 2px;
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

/* Right 1/4 Clean Route Creation Card */
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

.form-header-clean {{
  margin-bottom: 12px;
}}
.form-header-clean h3 {{
  font-size: 16px;
  font-weight: 850;
  letter-spacing: -0.01em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 8px;
}}

.selected-node-detail-box {{
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--card-bg);
  border: 1px solid var(--border-hover);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
}}
.snd-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
}}
.snd-label {{
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  flex: 0 0 auto;
}}
.snd-value-strong {{
  color: var(--ink);
  font-weight: 750;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}
.snd-host-code {{
  font-family: ui-monospace, monospace;
  font-size: 11px;
  font-weight: 750;
  color: var(--cyan);
  background: rgba(34, 211, 238, 0.08);
  padding: 1px 6px;
  border-radius: 4px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}

.magic-form {{
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 12px;
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
  .globe-card-hero, .metric-tile-hero, .bento-nodes-box, .route-creation-card, .my-routes-box {{ padding: 16px 14px; }}
  .node-grid {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }}
  .node-card {{ min-height: 110px; padding: 10px; }}
  .nav-badge.status {{ display: none; }}
  .globe-stage-wrapper {{ height: 180px; }}
  #globe-canvas {{ width: 220px; height: 220px; }}
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

  <!-- Top Hero: Left Continents 3D Globe + Right 2 Clean Metric Cards Stack -->
  <section class="hero-dashboard">
    <div class="globe-card-hero">
      <div class="globe-header">
        <div class="globe-title-group">
          <h3>🌐 全球中继态势拓扑 <span class="globe-live-tag"><i class="radar-ping"></i>LIVE 实时连通</span></h3>
          <p>高精世界大陆地形与活跃节点拓扑，支持鼠标按住自由旋转探索</p>
        </div>
      </div>
      
      <div class="globe-stage-wrapper">
        <canvas id="globe-canvas" width="560" height="560"></canvas>
      </div>
    </div>

    <div class="hero-metrics-stack">
      <div class="metric-tile-hero">
        <div class="metric-hero-left">
          <span class="metric-hero-title">可用加速节点</span>
          <div class="metric-hero-val">{nodes_count} <span>Nodes</span></div>
          <div class="metric-hero-sub">● 全节点就绪</div>
        </div>
        <div class="metric-hero-icon-box">⚡</div>
      </div>

      <div class="metric-tile-hero">
        <div class="metric-hero-left">
          <span class="metric-hero-title">我的配额使用</span>
          <div class="metric-hero-val">{used_routes} <span>/ {route_quota}</span></div>
          <div class="metric-hero-sub">● 随时删除释放</div>
        </div>
        <div class="metric-hero-icon-box quota-box">🗂</div>
      </div>
    </div>
  </section>

  <!-- Main Workspace: 3/4 Left Bento Nodes + 1/4 Right Clean Form -->
  <section class="magic-workspace">
    <div class="bento-nodes-box">
      <div class="box-header">
        <div class="box-header-title">
          <h2>✦ 选择加速节点</h2>
          <p>点击卡片选择节点，右侧将联动更新分配的专属加速地址</p>
        </div>
        <button type="button" class="btn-probe-magic" id="test-nodes">⚡ 全节点测速</button>
      </div>

      <div class="node-grid" id="nodes">
        {node_cards}
      </div>
    </div>

    <div class="route-creation-card">
      <div>
        <div class="form-header-clean">
          <h3>🚀 创建专属线路</h3>
          
          <div class="selected-node-detail-box">
            <div class="snd-row">
              <span class="snd-label">分配节点：</span>
              <strong class="snd-value-strong" id="snd-name">{html.escape(selected_node_flag)} {html.escape(selected_node_name)} ({html.escape(selected_node_country)})</strong>
            </div>
            <div class="snd-row" style="margin-top:4px;">
              <span class="snd-label">加速地址：</span>
              <code class="snd-host-code" id="snd-host">{html.escape(selected_node_host)}</code>
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
{WORLD_LAND_POLYGONS_JS}

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
  'GB': {{ lat: 51.50, lng: -0.12, name: '英国', flag: '🇬🇧' }},
  'CN': {{ lat: 31.23, lng: 121.47, name: '中国', flag: '🇨🇳' }}
}};

function resolveNodeGeo(node) {{
  const code = (node.code || '').toUpperCase();
  const cName = node.country_name || '';
  const nName = node.name || '';
  for (const [k, v] of Object.entries(REGION_GEO)) {{
    if (code === k || cName.includes(v.name) || nName.includes(v.name)) {{
      return {{ ...v, id: node.id, nodeName: node.name, host: node.host || '' }};
    }}
  }}
  return {{ lat: 22.0 + (node.id * 5) % 25, lng: 110.0 + (node.id * 10) % 30, name: cName || node.name, flag: node.flag || '🌐', id: node.id, nodeName: node.name, host: node.host || '' }};
}}

const activeNodeGeos = nodes.map(resolveNodeGeo);

// 3D Solid Continents Terrain Globe
const canvas = document.getElementById('globe-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

// Initial rotation: Face directly towards East Asia (China/Hong Kong/Japan/Singapore)
let rotationY = -0.45;
let rotationX = 0.22;
let targetRotY = -0.45;
let targetRotX = 0.22;
let isDragging = false;
let startMouseX = 0;
let startMouseY = 0;
let lastRotY = 0;
let lastRotX = 0;

// Project 3D Spherical Point
function project(lon, lat, r, cosY, sinY, cosX, sinX) {{
  const radLat = (lat * Math.PI) / 180;
  const radLon = (lon * Math.PI) / 180;

  const nx = Math.cos(radLat) * Math.cos(radLon);
  const ny = Math.sin(radLat);
  const nz = Math.cos(radLat) * Math.sin(radLon);

  const x1 = nx * cosY + nz * sinY;
  const y1 = ny;
  const z1 = -nx * sinY + nz * cosY;

  const x2 = x1;
  const y2 = y1 * cosX - z1 * sinX;
  const z2 = y1 * sinX + z1 * cosX;

  return {{ x: x2 * r, y: -y2 * r, z: z2 }};
}}

function renderGlobe() {{
  if (!ctx || !canvas) return;
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const globeR = 195;

  ctx.clearRect(0, 0, w, h);

  const isLight = document.body.dataset.theme === 'light';

  // Smooth rotation
  if (!isDragging) {{
    rotationY += 0.0028;
    if (targetRotY !== null) {{
      const diffY = ((targetRotY - rotationY) % (Math.PI * 2) + Math.PI * 3) % (Math.PI * 2) - Math.PI;
      rotationY += diffY * 0.035;
    }}
  }}

  const cosY = Math.cos(rotationY);
  const sinY = Math.sin(rotationY);
  const cosX = Math.cos(rotationX);
  const sinX = Math.sin(rotationX);

  // 1. Outer Atmosphere Halo
  const atmoGrad = ctx.createRadialGradient(cx, cy, globeR * 0.82, cx, cy, globeR * 1.28);
  if (!isLight) {{
    atmoGrad.addColorStop(0, 'rgba(34, 211, 238, 0.22)');
    atmoGrad.addColorStop(0.5, 'rgba(139, 92, 246, 0.12)');
    atmoGrad.addColorStop(1, 'rgba(3, 7, 18, 0)');
  }} else {{
    atmoGrad.addColorStop(0, 'rgba(14, 165, 233, 0.28)');
    atmoGrad.addColorStop(0.6, 'rgba(99, 102, 241, 0.08)');
    atmoGrad.addColorStop(1, 'rgba(244, 246, 251, 0)');
  }}
  ctx.fillStyle = atmoGrad;
  ctx.beginPath();
  ctx.arc(cx, cy, globeR * 1.28, 0, Math.PI * 2);
  ctx.fill();

  // 2. Base Ocean Sphere
  const oceanGrad = ctx.createRadialGradient(cx - globeR * 0.35, cy - globeR * 0.35, globeR * 0.15, cx, cy, globeR);
  if (!isLight) {{
    oceanGrad.addColorStop(0, '#0c1a38');
    oceanGrad.addColorStop(0.6, '#060d1f');
    oceanGrad.addColorStop(1, '#02050c');
  }} else {{
    oceanGrad.addColorStop(0, '#ffffff');
    oceanGrad.addColorStop(0.6, '#e0edff');
    oceanGrad.addColorStop(1, '#bcd6fa');
  }}
  ctx.fillStyle = oceanGrad;
  ctx.beginPath();
  ctx.arc(cx, cy, globeR, 0, Math.PI * 2);
  ctx.fill();

  // 3. Graticule 3D Grid Lines
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, globeR, 0, Math.PI * 2);
  ctx.clip();

  ctx.lineWidth = 0.75;
  ctx.strokeStyle = !isLight ? 'rgba(148, 163, 184, 0.12)' : 'rgba(148, 163, 184, 0.22)';

  for (let lon = -180; lon < 180; lon += 30) {{
    ctx.beginPath();
    let started = false;
    for (let lat = -80; lat <= 80; lat += 5) {{
      const p = project(lon, lat, globeR, cosY, sinY, cosX, sinX);
      if (p.z > 0) {{
        if (!started) {{ ctx.moveTo(cx + p.x, cy + p.y); started = true; }}
        else {{ ctx.lineTo(cx + p.x, cy + p.y); }}
      }} else {{
        started = false;
      }}
    }}
    ctx.stroke();
  }}

  for (let lat = -60; lat <= 60; lat += 30) {{
    ctx.beginPath();
    let started = false;
    for (let lon = -180; lon <= 180; lon += 5) {{
      const p = project(lon, lat, globeR, cosY, sinY, cosX, sinX);
      if (p.z > 0) {{
        if (!started) {{ ctx.moveTo(cx + p.x, cy + p.y); started = true; }}
        else {{ ctx.lineTo(cx + p.x, cy + p.y); }}
      }} else {{
        started = false;
      }}
    }}
    ctx.stroke();
  }}

  // 4. Render Solid World Continents & Landforms
  if (typeof WORLD_LAND_POLYGONS !== 'undefined') {{
    WORLD_LAND_POLYGONS.forEach(poly => {{
      poly.forEach(ring => {{
        if (ring.length < 3) return;

        const projRing = [];
        let anyVisible = false;

        for (let i = 0; i < ring.length; i++) {{
          const pt = ring[i];
          const p = project(pt[0], pt[1], globeR, cosY, sinY, cosX, sinX);
          if (p.z > -0.05) anyVisible = true;
          projRing.push(p);
        }}

        if (!anyVisible) return;

        ctx.beginPath();
        let penDown = false;
        for (let i = 0; i < projRing.length; i++) {{
          const p = projRing[i];
          if (p.z > 0) {{
            if (!penDown) {{
              ctx.moveTo(cx + p.x, cy + p.y);
              penDown = true;
            }} else {{
              ctx.lineTo(cx + p.x, cy + p.y);
            }}
          }} else {{
            penDown = false;
          }}
        }}

        if (!isLight) {{
          ctx.fillStyle = 'rgba(20, 184, 166, 0.45)';
          ctx.strokeStyle = 'rgba(34, 211, 238, 0.85)';
        }} else {{
          ctx.fillStyle = 'rgba(14, 165, 233, 0.35)';
          ctx.strokeStyle = 'rgba(2, 132, 199, 0.85)';
        }}
        ctx.lineWidth = 1.2;
        ctx.fill();
        ctx.stroke();
      }});
    }});
  }}

  ctx.restore();

  // 5. Globe Outer Border Rim
  ctx.lineWidth = 2;
  ctx.strokeStyle = !isLight ? 'rgba(34, 211, 238, 0.5)' : 'rgba(14, 165, 233, 0.6)';
  ctx.beginPath();
  ctx.arc(cx, cy, globeR, 0, Math.PI * 2);
  ctx.stroke();

  // 6. Draw Active Connected Nodes 3D Light Beams & Tags
  const now = Date.now() * 0.003;
  activeNodeGeos.forEach(nodeGeo => {{
    const p = project(nodeGeo.lng, nodeGeo.lat, globeR, cosY, sinY, cosX, sinX);
    if (p.z <= -0.15) return;

    const bx = cx + p.x;
    const by = cy + p.y;
    const isChosen = nodeGeo.id === selected;

    const rippleScale = (now % 2) / 2;
    ctx.beginPath();
    ctx.arc(bx, by, 7 + rippleScale * 16, 0, Math.PI * 2);
    ctx.strokeStyle = isChosen ? `rgba(244, 63, 94, ${{(1 - rippleScale) * 0.85}})` : `rgba(34, 211, 238, ${{(1 - rippleScale) * 0.85}})`;
    ctx.lineWidth = 2;
    ctx.stroke();

    const pillarHeight = isChosen ? 42 : 28;
    const topP = project(nodeGeo.lng, nodeGeo.lat, globeR + pillarHeight, cosY, sinY, cosX, sinX);
    const tx = cx + topP.x;
    const ty = cy + topP.y;

    const beamGrad = ctx.createLinearGradient(bx, by, tx, ty);
    beamGrad.addColorStop(0, 'rgba(34, 211, 238, 0.95)');
    beamGrad.addColorStop(1, isChosen ? 'rgba(244, 63, 94, 1)' : 'rgba(139, 92, 246, 1)');
    ctx.beginPath();
    ctx.moveTo(bx, by);
    ctx.lineTo(tx, ty);
    ctx.strokeStyle = beamGrad;
    ctx.lineWidth = isChosen ? 4.5 : 3;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(tx, ty, isChosen ? 6.5 : 4.5, 0, Math.PI * 2);
    ctx.fillStyle = isChosen ? '#fb7185' : '#22d3ee';
    ctx.shadowColor = isChosen ? '#fb7185' : '#22d3ee';
    ctx.shadowBlur = 15;
    ctx.fill();
    ctx.shadowBlur = 0;

    if (p.z > 0.08) {{
      const tagText = `${{nodeGeo.flag}} ${{nodeGeo.name}}`;
      ctx.font = 'bold 11px system-ui, -apple-system, sans-serif';
      const textWidth = ctx.measureText(tagText).width;
      
      const tagX = tx + 8;
      const tagY = ty - 8;

      ctx.fillStyle = !isLight ? 'rgba(11, 17, 34, 0.92)' : 'rgba(255, 255, 255, 0.96)';
      ctx.strokeStyle = isChosen ? 'rgba(244, 63, 94, 0.85)' : (!isLight ? 'rgba(34, 211, 238, 0.5)' : 'rgba(14, 165, 233, 0.6)');
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(tagX - 4, tagY - 11, textWidth + 8, 17, 4) : ctx.rect(tagX - 4, tagY - 11, textWidth + 8, 17);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = !isLight ? '#f8fafc' : '#0f172a';
      ctx.fillText(tagText, tagX, tagY + 2);
    }}
  }});

  requestAnimationFrame(renderGlobe);
}}

renderGlobe();

// Mouse Drag Interactions
canvas?.addEventListener('pointerdown', (e) => {{
  isDragging = true;
  startMouseX = e.clientX;
  startMouseY = e.clientY;
  lastRotY = rotationY;
  lastRotX = rotationX;
  canvas.style.cursor = 'grabbing';
}});

window.addEventListener('pointerup', () => {{
  if (isDragging) {{
    isDragging = false;
    if (canvas) canvas.style.cursor = 'grab';
  }}
}});

window.addEventListener('pointermove', (e) => {{
  if (!isDragging) return;
  const dx = e.clientX - startMouseX;
  const dy = e.clientY - startMouseY;
  rotationY = lastRotY + dx * 0.007;
  rotationX = Math.max(-0.6, Math.min(0.6, lastRotX - dy * 0.007));
  targetRotY = null;
}});

function pick(id) {{
  selected = id;
  const nodeInput = document.getElementById('node-id');
  if (nodeInput) nodeInput.value = id;
  
  let chosenName = '未选择';
  let chosenCountry = '全球';
  let chosenFlag = '🌐';
  let chosenHost = '暂无地址';

  document.querySelectorAll('.node-card').forEach(card => {{
    const active = Number(card.dataset.nodeId) === id;
    card.classList.toggle('selected', active);
    card.setAttribute('aria-pressed', String(active));
    if (active) {{
      chosenName = card.dataset.nodeName || ('节点 #' + id);
      chosenCountry = card.dataset.country || '';
      chosenFlag = card.dataset.flag || '🌐';
      chosenHost = card.dataset.host || '已就绪';
    }}
  }});
  
  const sndName = document.getElementById('snd-name');
  if (sndName) {{
    sndName.textContent = `${{chosenFlag}} ${{chosenName}} (${{chosenCountry}})`;
  }}
  const sndHost = document.getElementById('snd-host');
  if (sndHost) {{
    sndHost.textContent = chosenHost;
  }}

  const targetGeo = activeNodeGeos.find(g => g.id === id);
  if (targetGeo) {{
    const targetLonRad = (targetGeo.lng * Math.PI) / 180;
    targetRotY = (Math.PI / 2) - targetLonRad;
    targetRotX = (targetGeo.lat * Math.PI) / 180 * 0.35;
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

function probeAll() {{
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

