"""
dashboard.py
Quant Bot v3.3 Cockpit — Minimalist GitHub/Terminal Dashboard
SIFIR animasyon, SIFIR gradient, SIFIR glassmorphism.
Tüm veriler dosya okumasıyla — E2-micro dostu.
"""
import os
import re
import sys
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import datetime
import time
import config
# Dosya yolları
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKER_FILE = os.path.join(BASE_DIR, "active_trades.json")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
ENV_FILE = os.path.join(BASE_DIR, ".env")

# .env'den şifre oku (varsayılan: admin)
DASHBOARD_PASSWORD = "admin"
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("DASHBOARD_PASSWORD="):
                DASHBOARD_PASSWORD = line.split("=")[1].strip().replace('"', '').replace("'", "")

# Uptime hesabı için başlangıç zamanı
START_TIME = time.time()

def get_uptime():
    diff = int(time.time() - START_TIME)
    days, remain = divmod(diff, 86400)
    hours, remain = divmod(remain, 3600)
    minutes, seconds = divmod(remain, 60)
    return f"{days}g {hours}s {minutes}d {seconds}sn"

def read_last_logs(num_lines=50):
    if not os.path.exists(LOG_FILE):
        return ["Log dosyası henüz oluşturulmadı. Bot başladığında loglar burada görünecektir."]
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-num_lines:]]
    except Exception as e:
        return [f"Log okuma hatası: {e}"]

def read_trades():
    if not os.path.exists(TRACKER_FILE):
        return []
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

# ════════════════════════════════════════
# Ek Veri Kaynakları — Sadece dosya okuma (CPU yok)
# ════════════════════════════════════════

def _read_ab_stats():
    """A/B test istatistiklerini ab_test_stats.json'dan oku."""
    path = os.path.join(BASE_DIR, 'ab_test_stats.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _read_circuit_breaker():
    """Circuit breaker durumunu oku."""
    path = os.path.join(BASE_DIR, 'circuit_breaker_state.json')
    if not os.path.exists(path):
        return {'strategies': {}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            state = json.load(f)
            return {'strategies': state.get('strategies', {})}
    except Exception:
        return {'strategies': {}}

def _read_penalty_box():
    """Penalty box durumunu oku."""
    path = os.path.join(BASE_DIR, 'penalty_box.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [{'ticker': k, 'sl_count': v.get('sl_count', 0),
                     'until': v.get('penalty_until', 'N/A')}
                    for k, v in data.items() if v.get('sl_count', 0) > 0][:10]
    except Exception:
        return []

def _read_scorecard():
    """Strateji scorecard'ını oku."""
    path = os.path.join(BASE_DIR, 'strategy_scorecard.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [{'strategy': k, 'tp': v.get('tp_count', 0),
                     'sl': v.get('sl_count', 0), 'active': v.get('active', True)}
                    for k, v in data.items()][:15]
    except Exception:
        return []

def _parse_scan_stats():
    """Bot.log'dan son tarama bilgilerini çıkar — E2 dostu: sadece son 100 satır."""
    if not os.path.exists(LOG_FILE):
        return {}
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-100:]
        total_signals = 0
        last_scan_duration = 'N/A'
        dg_rejects = 0
        conviction_scores = []
        for line in lines:
            if 'Toplam sinyal' in line or 'sinyal üretildi' in line:
                nums = re.findall(r'(\d+)\s*sinyal', line)
                if nums:
                    total_signals = int(nums[-1])
            if 'Tarama süresi' in line or 'sürdü' in line:
                dur = re.findall(r'([\d.]+)\s*(?:sn|saniye|dk|min)', line)
                if dur:
                    last_scan_duration = f'{dur[-1]}s'
            if '[DataGuard]' in line and ('reddetti' in line or 'reddedildi' in line):
                dg_rejects += 1
            if 'Score=' in line:
                sc = re.findall(r'Score=(\d+)', line)
                if sc:
                    conviction_scores.append(int(sc[0]))
        avg_score = round(sum(conviction_scores) / len(conviction_scores), 1) if conviction_scores else 0
        return {
            'total_signals': total_signals,
            'scan_duration': last_scan_duration,
            'dg_rejects': dg_rejects,
            'avg_conviction': avg_score,
            'conviction_distribution': {
                'strong': sum(1 for s in conviction_scores if s >= config.GLOBAL_STRONG_CONVICTION_SCORE),
                'medium': sum(1 for s in conviction_scores if config.GLOBAL_MEDIUM_CONVICTION_SCORE <= s < config.GLOBAL_STRONG_CONVICTION_SCORE),
                'watch': sum(1 for s in conviction_scores if config.GLOBAL_MIN_CONVICTION_SCORE <= s < config.GLOBAL_MEDIUM_CONVICTION_SCORE),
                'reject': sum(1 for s in conviction_scores if s < config.GLOBAL_MIN_CONVICTION_SCORE),
            } if conviction_scores else {}
        }
    except Exception:
        return {}

def _parse_dataguard_stats():
    """Bot.log'dan DataGuard istatistiklerini çıkar."""
    if not os.path.exists(LOG_FILE):
        return {}
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-200:]
        dg_counts = {'DG-01': 0, 'DG-02': 0, 'DG-04': 0, 'DG-06': 0}
        for line in lines:
            for dg in dg_counts:
                if dg in line:
                    dg_counts[dg] += 1
        return dg_counts
    except Exception:
        return {}


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Konsol log kalabalığını önlemek için HTTP loglarını sessize alıyoruz
        return

    def check_auth(self):
        # Cookies'ten token kontrolü yap
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = urllib.parse.parse_qs(cookie_header.replace('; ', '&'))
            if 'token' in cookies and cookies['token'][0] == DASHBOARD_PASSWORD:
                return True
        return False

    def do_GET(self):
        # 1. API: Login kontrolü
        if self.path == "/api/login-check":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"authenticated": self.check_auth()}).encode('utf-8'))
            return

        # 2. Sayfa: Login HTML
        if not self.check_auth():
            if self.path.startswith("/api/"):
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_login_html().encode('utf-8'))
            return

        # 3. Birleşik API: Tüm veriler tek istekte
        if self.path == "/api/all":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Sunucu RAM bilgisi
            ram_info = "N/A"
            try:
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                    total = int(lines[0].split()[1]) // 1024
                    free = int(lines[1].split()[1]) // 1024
                    used = total - free
                    ram_info = f"{used}/{total}MB"
            except Exception:
                pass

            response_data = {
                "status": {
                    "uptime": get_uptime(),
                    "ram": ram_info,
                    "last_scan": datetime.datetime.now().strftime("%H:%M:%S"),
                    "status": "AKTIF"
                },
                "trades": read_trades(),
                "logs": read_last_logs(40),
                "scan_stats": _parse_scan_stats(),
                "ab_test": _read_ab_stats(),
                "circuit_breaker": _read_circuit_breaker(),
                "dataguard": _parse_dataguard_stats(),
                "penalty_box": _read_penalty_box(),
                "scorecard": _read_scorecard(),
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            return

        # 4. Sayfa: Ana Dashboard
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_dashboard_html().encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/login":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                password = data.get("password")
                if password == DASHBOARD_PASSWORD:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Set-Cookie", f"token={DASHBOARD_PASSWORD}; Path=/; Max-Age=2592000; HttpOnly")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "message": "Hatalı şifre!"}).encode('utf-8'))
            except Exception:
                self.send_response(500)
                self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def get_login_html(self):
        return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Bot v3.3 — Login</title>
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0d1117;color:#c9d1d9;font-family:'JetBrains Mono','Fira Code','Cascadia Code','Consolas',monospace;height:100vh;display:flex;align-items:center;justify-content:center}
        .login{border:1px solid #30363d;padding:32px;width:360px;border-radius:4px;background:#161b22}
        h2{color:#58a6ff;font-size:16px;margin-bottom:4px;border-left:3px solid #58a6ff;padding-left:8px}
        .sub{color:#8b949e;font-size:11px;margin-bottom:20px;padding-left:11px}
        input{width:100%;padding:8px 10px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;font-family:inherit;font-size:13px;border-radius:2px;margin-bottom:12px}
        input:focus{outline:none;border-color:#58a6ff}
        button{width:100%;padding:8px;background:#238636;border:none;color:#fff;font-family:inherit;font-size:13px;cursor:pointer;border-radius:2px}
        button:hover{background:#2ea043}
        .err{color:#f85149;font-size:11px;margin-top:8px;display:none}
    </style>
</head>
<body>
    <div class="login">
        <h2>QUANT BOT v3.3</h2>
        <div class="sub">kimlik doğrulama gerekli</div>
        <input type="password" id="pw" placeholder="şifre" autofocus>
        <button onclick="doLogin()">GİRİŞ</button>
        <div class="err" id="err">hatalı şifre</div>
    </div>
    <script>
        document.getElementById('pw').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
        function doLogin(){
            const pw=document.getElementById('pw').value;
            fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})})
            .then(r=>{if(r.ok){location.reload()}else{document.getElementById('err').style.display='block'}})
            .catch(()=>{document.getElementById('err').style.display='block'});
        }
    </script>
</body>
</html>"""

    def get_dashboard_html(self):
        return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Bot v3.3 Cockpit</title>
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0d1117;color:#c9d1d9;font-family:'JetBrains Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:12px;padding:16px}
        .hdr{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #30363d;padding-bottom:10px;margin-bottom:12px}
        .hdr h1{font-size:14px;color:#58a6ff;font-weight:600}
        .hdr .st{font-size:11px;color:#3fb950}
        .hdr .st.off{color:#f85149}
        .hdr a{color:#8b949e;font-size:11px;text-decoration:none}
        .hdr a:hover{color:#f85149}
        .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
        .panel{border:1px solid #30363d;border-radius:4px;padding:10px;background:#161b22}
        .panel h3{font-size:11px;color:#58a6ff;border-left:3px solid #58a6ff;padding-left:8px;margin-bottom:8px;font-weight:600;text-transform:uppercase}
        .kv{display:flex;flex-wrap:wrap;gap:12px}
        .kv .k{color:#8b949e;font-size:10px}
        .kv .v{color:#c9d1d9;font-size:14px;font-weight:600}
        .kv .item{display:flex;flex-direction:column;gap:2px}
        .full{grid-column:1/-1}
        table{width:100%;border-collapse:collapse;font-size:11px}
        th{text-align:left;color:#8b949e;font-weight:400;padding:4px 6px;border-bottom:1px solid #30363d}
        td{padding:4px 6px;border-bottom:1px solid #21262d}
        .al{color:#3fb950}
        .sat{color:#f85149}
        .badge{display:inline-block;padding:1px 6px;border-radius:2px;font-size:10px;font-weight:600}
        .b-strong{background:#238636;color:#fff}
        .b-medium{background:#9e6a03;color:#fff}
        .b-watch{background:#bd561d;color:#fff}
        .b-reject{background:#da3633;color:#fff}
        .bar{display:inline-block;height:10px;border-radius:1px}
        .log-box{background:#010409;border:1px solid #30363d;border-radius:4px;padding:8px;max-height:260px;overflow-y:auto;font-size:10px;line-height:1.6}
        .log-box .info{color:#8b949e}
        .log-box .warn{color:#d29922}
        .log-box .error{color:#f85149}
        .log-box .conviction{color:#58a6ff}
        .dg-row{display:flex;gap:16px;flex-wrap:wrap}
        .dg-item{display:flex;flex-direction:column;align-items:center;gap:2px}
        .dg-item .code{color:#8b949e;font-size:10px}
        .dg-item .cnt{font-size:16px;font-weight:700}
        .ab-row{display:flex;gap:20px}
        .ab-group{flex:1}
        .ab-group .lbl{color:#8b949e;font-size:10px;margin-bottom:4px}
        .active-badge{color:#3fb950}
        .disabled-badge{color:#f85149}
        .empty{color:#8b949e;font-style:italic;padding:8px}
    </style>
</head>
<body>
    <div class="hdr">
        <h1>QUANT BOT v3.3 COCKPIT</h1>
        <div>
            <span class="st" id="bot-status">AKTIF</span>
            &nbsp;&nbsp;
            <a href="#" onclick="document.cookie='token=;Max-Age=0;Path=/';location.reload()">ÇIKIŞ</a>
        </div>
    </div>

    <div class="grid">
        <!-- SYSTEM -->
        <div class="panel">
            <h3>SYSTEM</h3>
            <div class="kv">
                <div class="item"><span class="k">uptime</span><span class="v" id="s-uptime">—</span></div>
                <div class="item"><span class="k">ram</span><span class="v" id="s-ram">—</span></div>
                <div class="item"><span class="k">son güncelleme</span><span class="v" id="s-scan">—</span></div>
                <div class="item"><span class="k">circuit breaker</span><span class="v" id="s-cb">—</span></div>
                <div class="item"><span class="k">penalty box</span><span class="v" id="s-pb">—</span></div>
            </div>
        </div>

        <!-- TARAMA -->
        <div class="panel">
            <h3>TARAMA (Son Döngü)</h3>
            <div class="kv" style="margin-bottom:8px">
                <div class="item"><span class="k">süre</span><span class="v" id="sc-dur">—</span></div>
                <div class="item"><span class="k">sinyal</span><span class="v" id="sc-sig">—</span></div>
                <div class="item"><span class="k">DG red</span><span class="v" id="sc-dg">—</span></div>
                <div class="item"><span class="k">ort.score</span><span class="v" id="sc-avg">—</span></div>
            </div>
            <div id="conv-dist" style="font-size:11px;line-height:1.8"></div>
        </div>

        <!-- A/B TEST -->
        <div class="panel">
            <h3>A/B TEST</h3>
            <div id="ab-panel"><span class="empty">veri bekleniyor...</span></div>
        </div>

        <!-- DATAGUARD -->
        <div class="panel">
            <h3>DATAGUARD</h3>
            <div class="dg-row" id="dg-panel">
                <span class="empty">veri bekleniyor...</span>
            </div>
        </div>

        <!-- SCORECARD -->
        <div class="panel full">
            <h3>SCORECARD</h3>
            <table id="sc-table">
                <thead><tr><th>strateji</th><th>TP</th><th>SL</th><th>durum</th></tr></thead>
                <tbody id="sc-body"><tr><td colspan="4" class="empty">veri bekleniyor...</td></tr></tbody>
            </table>
        </div>

        <!-- AKTİF İŞLEMLER -->
        <div class="panel full">
            <h3>AKTİF İŞLEMLER (<span id="trade-count">0</span>)</h3>
            <table id="trade-table">
                <thead><tr><th>varlık</th><th>yön</th><th>strateji</th><th>giriş</th><th>SL</th><th>TP</th><th>conviction</th><th>durum</th></tr></thead>
                <tbody id="trade-body"><tr><td colspan="8" class="empty">aktif işlem yok</td></tr></tbody>
            </table>
        </div>

        <!-- PENALTY BOX -->
        <div class="panel full" id="pb-panel" style="display:none">
            <h3>PENALTY BOX</h3>
            <table>
                <thead><tr><th>varlık</th><th>SL sayısı</th><th>bitiş</th></tr></thead>
                <tbody id="pb-body"></tbody>
            </table>
        </div>

        <!-- CANLI LOG -->
        <div class="panel full">
            <h3>CANLI LOG</h3>
            <div class="log-box" id="log-box"></div>
        </div>
    </div>

    <script>
        function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

        function makeBar(count, max, color){
            if(!max||!count) return '';
            const w = Math.min(Math.round((count/max)*120), 120);
            return `<span class="bar" style="width:${w}px;background:${color}"></span>`;
        }

        function updateAllData(){
            fetch('/api/all')
            .then(r=>{if(!r.ok)throw new Error(r.status);return r.json()})
            .then(d=>{
                // SYSTEM
                const s=d.status||{};
                document.getElementById('s-uptime').textContent=s.uptime||'—';
                document.getElementById('s-ram').textContent=s.ram||'N/A';
                document.getElementById('s-scan').textContent=s.last_scan||'—';
                const cb=d.circuit_breaker||{};
                const strats=cb.strategies||{};
                const keys=Object.keys(strats);
                let cbHtml='';
                if(keys.length===0){
                    cbHtml='<span style="color:#3fb950">KAPALI (Veri Yok)</span>';
                }else{
                    cbHtml=keys.map(k=>{
                        const st=strats[k];
                        const isOpen=st.silent_mode;
                        const status=isOpen?'AÇIK':'KAPALI';
                        const color=isOpen?'#f85149':'#3fb950';
                        return `<span style="color:${color}">${k}: ${status}</span>`;
                    }).join(' | ');
                }
                const cbEl=document.getElementById('s-cb');
                cbEl.innerHTML=cbHtml;
                const pb=d.penalty_box||[];
                document.getElementById('s-pb').textContent=pb.length>0?pb.length+' varlık':'temiz';

                // TARAMA
                const sc=d.scan_stats||{};
                document.getElementById('sc-dur').textContent=sc.scan_duration||'N/A';
                document.getElementById('sc-sig').textContent=sc.total_signals||0;
                document.getElementById('sc-dg').textContent=sc.dg_rejects||0;
                document.getElementById('sc-avg').textContent=sc.avg_conviction||0;
                const cd=sc.conviction_distribution||{};
                const maxC=Math.max(cd.strong||0,cd.medium||0,cd.watch||0,cd.reject||0,1);
                let distHtml='';
                if(cd.strong!==undefined){
                    distHtml+=`${makeBar(cd.strong,maxC,'#3fb950')} <span style="color:#3fb950">STRONG:${cd.strong}</span> `;
                    distHtml+=`${makeBar(cd.medium,maxC,'#d29922')} <span style="color:#d29922">MEDIUM:${cd.medium}</span> `;
                    distHtml+=`${makeBar(cd.watch,maxC,'#f0883e')} <span style="color:#f0883e">WATCH:${cd.watch}</span> `;
                    distHtml+=`${makeBar(cd.reject,maxC,'#f85149')} <span style="color:#f85149">REJECT:${cd.reject}</span>`;
                }
                document.getElementById('conv-dist').innerHTML=distHtml;

                // A/B TEST
                const ab=d.ab_test;
                const abEl=document.getElementById('ab-panel');
                if(ab&&ab.total_evaluations){
                    const divPct=ab.divergence_count?((ab.divergence_count/ab.total_evaluations)*100).toFixed(1):'0';
                    const cg=ab.control_grades||{};
                    const eg=ab.experiment_grades||{};
                    abEl.innerHTML=`
                        <div class="kv" style="margin-bottom:6px">
                            <div class="item"><span class="k">toplam</span><span class="v">${ab.total_evaluations}</span></div>
                            <div class="item"><span class="k">fark</span><span class="v">${ab.divergence_count||0} (%${divPct})</span></div>
                        </div>
                        <div class="ab-row">
                            <div class="ab-group"><div class="lbl">control</div>S:${cg.STRONG||0} M:${cg.MEDIUM||0} W:${cg.WATCH||0} R:${cg.REJECT||0}</div>
                            <div class="ab-group"><div class="lbl">experiment</div>S:${eg.STRONG||0} M:${eg.MEDIUM||0} W:${eg.WATCH||0} R:${eg.REJECT||0}</div>
                        </div>`;
                }else{
                    abEl.innerHTML='<span class="empty">henüz A/B test verisi yok</span>';
                }

                // DATAGUARD
                const dg=d.dataguard||{};
                const dgEl=document.getElementById('dg-panel');
                const dgKeys=['DG-01','DG-02','DG-04','DG-06'];
                let dgHtml='';
                dgKeys.forEach(k=>{
                    const c=dg[k]||0;
                    const color=c>5?'#f85149':c>0?'#d29922':'#3fb950';
                    dgHtml+=`<div class="dg-item"><span class="code">${k}</span><span class="cnt" style="color:${color}">${c}</span></div>`;
                });
                dgEl.innerHTML=dgHtml;

                // SCORECARD
                const scard=d.scorecard||[];
                const scBody=document.getElementById('sc-body');
                if(scard.length){
                    scBody.innerHTML=scard.map(s=>{
                        const status=s.active?'<span class="active-badge">aktif</span>':'<span class="disabled-badge">devre dışı</span>';
                        return `<tr><td>${esc(s.strategy)}</td><td style="color:#3fb950">${s.tp}</td><td style="color:#f85149">${s.sl}</td><td>${status}</td></tr>`;
                    }).join('');
                }else{
                    scBody.innerHTML='<tr><td colspan="4" class="empty">scorecard verisi yok</td></tr>';
                }

                // AKTİF İŞLEMLER
                const trades=d.trades||[];
                document.getElementById('trade-count').textContent=trades.length;
                const tBody=document.getElementById('trade-body');
                if(trades.length){
                    tBody.innerHTML=trades.map(t=>{
                        const dir=t.signal||'AL';
                        const dirClass=dir==='AL'?'al':'sat';
                        const cs=t.conviction_score;
                        const cg=t.conviction_grade||'';
                        let convHtml='—';
                        if(cs!==undefined&&cs!==null){
                            const bc=cg==='STRONG'?'b-strong':cg==='MEDIUM'?'b-medium':cg==='WATCH'?'b-watch':'b-reject';
                            convHtml=`${Math.round(cs)} <span class="badge ${bc}">${cg}</span>`;
                        }
                        const status=t.status||'ACTIVE';
                        const stColor=status==='ACTIVE'?'#3fb950':'#8b949e';
                        return `<tr>
                            <td>${esc(t.ticker)}</td>
                            <td class="${dirClass}">${dir}</td>
                            <td>${esc(t.strategy)}</td>
                            <td>${t.entry_price}</td>
                            <td style="color:#f85149">${t.sl}</td>
                            <td style="color:#3fb950">${t.tp}</td>
                            <td>${convHtml}</td>
                            <td style="color:${stColor}">${status}</td>
                        </tr>`;
                    }).join('');
                }else{
                    tBody.innerHTML='<tr><td colspan="8" class="empty">aktif işlem yok</td></tr>';
                }

                // PENALTY BOX
                const pbPanel=document.getElementById('pb-panel');
                const pbBody=document.getElementById('pb-body');
                if(pb.length){
                    pbPanel.style.display='block';
                    pbBody.innerHTML=pb.map(p=>`<tr><td>${esc(p.ticker)}</td><td style="color:#f85149">${p.sl_count}</td><td>${esc(p.until)}</td></tr>`).join('');
                }else{
                    pbPanel.style.display='none';
                }

                // CANLI LOG
                const logs=d.logs||[];
                const logBox=document.getElementById('log-box');
                logBox.innerHTML=logs.map(l=>{
                    let cls='info';
                    if(l.includes('[WARN]')||l.includes('[WARNING]'))cls='warn';
                    else if(l.includes('[ERROR]'))cls='error';
                    else if(l.includes('Score=')||l.includes('Conviction'))cls='conviction';
                    return `<div class="${cls}">&gt; ${esc(l)}</div>`;
                }).join('');
                logBox.scrollTop=logBox.scrollHeight;
            })
            .catch(err=>console.error('Güncelleme hatası:',err));
        }

        updateAllData();
        setInterval(updateAllData, 15000);
    </script>
</body>
</html>"""

def run_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"\n==================================================")
    print(f"  Quant Bot Dashboard: http://localhost:{port}")
    print(f"  Erişim Şifresi: {DASHBOARD_PASSWORD}")
    print(f"==================================================\n")
    httpd.serve_forever()

if __name__ == "__main__":
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port)
