import os
import sys
import json
import uuid
import subprocess
import webbrowser
import re
import base64
from datetime import date, datetime

# =========================================================================
# 1. SYSTEM SETUP & PATH HANDLING
# =========================================================================
APP_NAME = "FocusFlow_Final"
app_data = os.getenv('LOCALAPPDATA') or os.path.expanduser("~")
DB_DIR = os.path.join(app_data, APP_NAME)
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)

DATA_PATH = os.path.join(DB_DIR, "courses_v3.json")
SETTINGS_PATH = os.path.join(DB_DIR, "settings.json")

def get_settings():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, 'r') as f: return json.load(f)
        except: pass
    return {"theme": "dark"}

def save_settings(s):
    with open(SETTINGS_PATH, 'w') as f: json.dump(s, f)

try:
    import webview
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
    import webview

# =========================================================================
# 2. ROBUST BACKEND ENGINE
# =========================================================================
class CourseManager:
    def __init__(self):
        self.courses = self.load()

    def load(self):
        if os.path.exists(DATA_PATH):
            try:
                with open(DATA_PATH, 'r') as f:
                    data = json.load(f)
                    today = str(date.today())
                    for c in data:
                        if 'strikes_data' not in c: c['strikes_data'] = []
                        if 'status' not in c: c['status'] = 'active'
                        if 'last_update_date' not in c: c['last_update_date'] = today
                    return data
            except: pass
        return []

    def save(self):
        with open(DATA_PATH, 'w') as f: json.dump(self.courses, f, indent=4)

    def get_files(self, folder):
        if not folder or not os.path.exists(folder): return []
        exts = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm')
        found = []
        for r, _, fnames in os.walk(folder):
            for fn in fnames:
                if fn.lower().endswith(exts):
                    found.append(os.path.relpath(os.path.join(r, fn), folder))
        found.sort(key=lambda text: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)])
        return found

    def refresh_logic(self):
        today = date.today()
        today_str = str(today)
        for c in self.courses:
            try: last_d = datetime.strptime(c['last_update_date'], "%Y-%m-%d").date()
            except: last_d = today
            
            if today > last_d:
                if c['status'] == 'active':
                    files = self.get_files(c['folder'])
                    needed = c['daily_quota'] - c['watched_today_count']
                    if needed > 0:
                        start = c['last_index'] + c['watched_today_count']
                        missed = files[start:start+needed]
                        if missed:
                            c['strikes_data'].append({'id':str(uuid.uuid4()), 'date':str(last_d), 'videos':missed})
                            c['last_index'] += len(missed)
                c['watched_today_count'] = 0
                c['last_update_date'] = today_str
        
        self.courses = [c for c in self.courses if len(c.get('strikes_data', [])) < 5]
        self.save()

    def get_data(self):
        self.refresh_logic()
        for c in self.courses:
            files = self.get_files(c['folder'])
            total = len(files)
            if c['last_index'] > total: c['last_index'] = total
            c['progress'] = int((min(c['last_index'], total)/total)*100) if total > 0 else 0
            c['total_videos'] = total
            c['is_quota_met'] = c['watched_today_count'] >= c['daily_quota']
            c['logo_b64'] = ""
            if c['logo'] and os.path.exists(c['logo']):
                try:
                    with open(c['logo'], "rb") as f:
                        c['logo_b64'] = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
                except: pass
        return self.courses

class Api:
    def __init__(self): self.cm = CourseManager()
    def open_link(self, url): webbrowser.open(url)
    def get_courses(self): return self.cm.get_data()
    def set_theme(self, t): s = get_settings(); s['theme'] = t; save_settings(s); return True
    def browse_f(self):
        import tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw()
        p=filedialog.askdirectory(); r.destroy(); return p
    def browse_l(self):
        # FIX: Added specific image filters for the file dialog
        import tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw()
        p=filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        r.destroy(); return p
    def add_c(self, n, p, f, q, l):
        self.cm.courses.append({"id":str(uuid.uuid4()), "name":n, "platform":p, "folder":f, "daily_quota":int(q), "logo":l, "last_index":0, "status":"active", "last_update_date":str(date.today()), "watched_today_count":0, "strikes_data":[]})
        self.cm.save(); return self.cm.get_data()
    def update_c(self, i, n, p, f, q, l):
        for c in self.cm.courses:
            if c['id']==i: c['name']=n; c['platform']=p; c['folder']=f; c['daily_quota']=int(q); c['logo']=l; break
        self.cm.save(); return self.cm.get_data()
    def delete_c(self, i):
        self.cm.courses = [c for c in self.cm.courses if c['id']!=i]
        self.cm.save(); return self.cm.get_data()
    def toggle_c(self, i):
        for c in self.cm.courses:
            if c['id']==i: c['status'] = 'paused' if c['status']=='active' else 'active'
        self.cm.save(); return self.cm.get_data()
    def play(self, i):
        for c in self.cm.courses:
            if c['id']==i:
                fs = self.cm.get_files(c['folder'])
                if c['last_index'] < len(fs):
                    os.startfile(os.path.join(c['folder'], fs[c['last_index']]))
                    return True
        return False
    def mark(self, i):
        for c in self.cm.courses:
            if c['id']==i: c['last_index']+=1; c['watched_today_count']+=1; break
        self.cm.save(); return self.cm.get_data()
    def play_strike(self, i, fn):
        for c in self.cm.courses:
            if c['id']==i: os.startfile(os.path.join(c['folder'], fn)); return True
        return False
    def resolve(self, i, si, fn):
        for c in self.cm.courses:
            if c['id']==i:
                for s in c['strikes_data']:
                    if s['id']==si:
                        if fn in s['videos']: s['videos'].remove(fn)
                        if not s['videos']: c['strikes_data'].remove(s)
                        break
        self.cm.save(); return self.cm.get_data()

# =========================================================================
# 3. HIGH-CONTRAST GLOSSY FRONTEND
# =========================================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en" class="__THEME__">
<head>
    <meta charset="utf-8"/><meta content="width=device-width, initial-scale=1.0" name="viewport"/>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet"/>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = { darkMode: "class", theme: { extend: { colors: { primary: "#8b5cf6", secondary: "#3b82f6" } } } };
    </script>
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
        .glass { background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(25px); border: 1px solid rgba(255, 255, 255, 0.5); }
        .dark .glass { background: rgba(18, 18, 24, 0.8); backdrop-filter: blur(25px); border: 1px solid rgba(255, 255, 255, 0.1); }
        
        .card-frost { background: rgba(255, 255, 255, 0.6); border: 1px solid rgba(0,0,0,0.08); box-shadow: 0 4px 20px rgba(0,0,0,0.04); }
        .dark .card-frost { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        
        .light-text { color: #1e293b; }
        .dark .light-text { color: #f8fafc; }
        
        .sub-text { color: #64748b; }
        .dark .sub-text { color: #94a3b8; }

        @keyframes shake { 0%, 100% { transform: rotate(0deg); } 25% { transform: rotate(-6deg); } 75% { transform: rotate(6deg); } }
        .strike-shake { animation: shake 0.4s infinite; }
        
        dialog::backdrop { background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(12px); }
        dialog { background: transparent; outline: none; border: none; }
        .modal-pop { animation: pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
        @keyframes pop { from { opacity: 0; transform: scale(0.9) translateY(20px); } to { opacity: 1; transform: scale(1) translateY(0); } }
        
        .btn-shine { position: relative; overflow: hidden; }
        .btn-shine::after { content: ""; position: absolute; top: -50%; left: -150%; width: 200%; height: 200%; background: linear-gradient(45deg, transparent, rgba(255,255,255,0.3), transparent); transform: rotate(45deg); transition: 0.8s; }
        .btn-shine:hover::after { left: 150%; }
    </style>
</head>
<body class="bg-slate-50 dark:bg-[#08080a] light-text min-h-screen">

<nav class="sticky top-0 z-50 glass h-16 flex items-center justify-between px-10 border-b dark:border-white/5">
   <div onclick="pywebview.api.open_link('https://github.com/Glax3210')" class="flex items-center gap-3 cursor-pointer hover:opacity-80 transition-all">
        <div class="w-9 h-9 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/30"><span class="material-symbols-rounded text-white text-xl">rocket_launch</span></div>
        <h1 class="text-xl font-black tracking-tighter">FocusFlow <span class="text-primary">Pro</span></h1>
    </div>
    <button onclick="toggleTheme()" class="w-10 h-10 rounded-full glass flex items-center justify-center hover:scale-110 transition-all border dark:border-white/10">
        <span class="material-symbols-rounded text-sm">wb_sunny</span>
    </button>
</nav>

<main class="max-w-[1440px] mx-auto px-10 py-10">
    <div id="course-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
        <div onclick="openAdd()" class="card-frost rounded-[2.5rem] p-8 flex flex-col items-center justify-center border-2 border-dashed border-slate-300 dark:border-slate-800 cursor-pointer hover:border-primary transition-all group min-h-[340px]">
            <div class="w-16 h-16 rounded-3xl bg-primary/10 flex items-center justify-center group-hover:scale-110 transition-all"><span class="material-symbols-rounded text-primary text-4xl">add_circle</span></div>
            <p class="mt-4 font-bold sub-text">New Learning Track</p>
        </div>
    </div>
</main>

<dialog id="modal-confirm" class="w-full max-w-sm">
    <div class="glass rounded-[3rem] p-10 text-center modal-pop border-2 dark:border-white/10 shadow-2xl">
        <div id="confirm-bg" class="w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-6 text-white shadow-xl">
            <span id="confirm-icon" class="material-symbols-rounded text-4xl">help</span>
        </div>
        <h3 id="confirm-title" class="text-2xl font-black mb-2 light-text">Confirm Action</h3>
        <p id="confirm-msg" class="sub-text text-sm mb-10 leading-relaxed"></p>
        <div class="flex gap-4">
            <button onclick="closeConfirm(false)" class="flex-1 py-4 font-bold sub-text hover:light-text transition-all">Cancel</button>
            <button id="confirm-btn" onclick="closeConfirm(true)" class="flex-1 py-4 font-bold text-white rounded-[1.5rem] btn-shine shadow-lg">Yes, Proceed</button>
        </div>
    </div>
</dialog>

<dialog id="modal-course" class="w-full max-w-md">
    <div class="glass rounded-[3rem] p-10 modal-pop border-2 dark:border-white/10 shadow-2xl">
        <h3 id="modal-title" class="text-3xl font-black mb-8 light-text">Course Details</h3>
        <input type="hidden" id="c-id">
        <div class="space-y-5">
            <div>
                <label class="text-[11px] font-black sub-text uppercase tracking-widest ml-4 mb-2 block">Name & Platform</label>
                <input id="c-name" type="text" placeholder="Course Name" class="w-full bg-slate-100 dark:bg-black/40 p-5 rounded-[1.5rem] outline-none focus:ring-2 focus:ring-primary light-text border dark:border-white/5 mb-3">
                <input id="c-plat" type="text" placeholder="Platform (e.g. Udemy)" class="w-full bg-slate-100 dark:bg-black/40 p-5 rounded-[1.5rem] outline-none focus:ring-2 focus:ring-primary light-text border dark:border-white/5">
            </div>
            <div>
                <label class="text-[11px] font-black sub-text uppercase tracking-widest ml-4 mb-2 block">Source Folder</label>
                <div class="flex gap-3">
                    <input id="c-folder" readonly placeholder="Pick folder..." class="flex-1 bg-slate-100 dark:bg-black/40 p-5 rounded-[1.5rem] text-xs outline-none truncate border dark:border-white/5 light-text">
                    <button onclick="browseF()" class="px-6 bg-primary text-white rounded-[1.5rem] font-bold text-xs btn-shine">Browse</button>
                </div>
            </div>
            <div>
                <label class="text-[11px] font-black sub-text uppercase tracking-widest ml-4 mb-2 block">Custom Logo (Optional)</label>
                <div class="flex gap-3">
                    <input id="c-logo" readonly placeholder="Pick image..." class="flex-1 bg-slate-100 dark:bg-black/40 p-5 rounded-[1.5rem] text-xs outline-none truncate border dark:border-white/5 light-text">
                    <button onclick="browseL()" class="px-6 bg-slate-400 dark:bg-white/10 text-white rounded-[1.5rem] font-bold text-xs">Image</button>
                </div>
            </div>
            <div>
                <label class="text-[11px] font-black sub-text uppercase tracking-widest ml-4 mb-2 block">Daily Video Quota</label>
                <input id="c-quota" type="number" value="3" class="w-full bg-slate-100 dark:bg-black/40 p-5 rounded-[1.5rem] outline-none focus:ring-2 focus:ring-primary light-text border dark:border-white/5">
            </div>
            <div class="pt-4 flex gap-3">
                <button onclick="document.getElementById('modal-course').close()" class="flex-1 py-5 font-bold sub-text">Cancel</button>
                <button onclick="saveC()" class="flex-2 px-10 py-5 bg-primary text-white font-black rounded-[1.5rem] shadow-xl shadow-primary/20 btn-shine">Save Track</button>
            </div>
        </div>
    </div>
</dialog>

<dialog id="modal-strikes" class="w-full max-w-md">
    <div class="glass rounded-[3rem] p-10 modal-pop max-h-[85vh] flex flex-col border-2 dark:border-white/10 shadow-2xl">
        <h3 class="text-3xl font-black text-red-500 mb-8 flex items-center gap-3">
            <span class="material-symbols-rounded strike-shake text-4xl">warning</span> Pending Strikes
        </h3>
        <div id="strikes-list" class="flex-1 overflow-y-auto space-y-4 pr-2"></div>
        <button onclick="document.getElementById('modal-strikes').close()" class="mt-8 w-full py-5 bg-slate-100 dark:bg-white/5 rounded-[1.5rem] font-black light-text">Got it</button>
    </div>
</dialog>

<script>
    let courses = [];
    let confirmCb = null;

    function openConfirm(title, msg, type, cb) {
        document.getElementById('confirm-title').innerText = title;
        document.getElementById('confirm-msg').innerText = msg;
        const bg = document.getElementById('confirm-bg');
        const btn = document.getElementById('confirm-btn');
        const icon = document.getElementById('confirm-icon');
        
        if(type === 'danger') {
            bg.className = "w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-6 bg-red-500 shadow-xl shadow-red-500/40 text-white";
            btn.className = "flex-1 py-4 font-bold text-white rounded-[1.5rem] bg-red-500 btn-shine shadow-lg";
            icon.innerText = "delete_forever";
        } else {
            bg.className = "w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-6 bg-primary shadow-xl shadow-primary/40 text-white";
            btn.className = "flex-1 py-4 font-bold text-white rounded-[1.5rem] bg-primary btn-shine shadow-lg";
            icon.innerText = "verified";
        }
        confirmCb = cb;
        document.getElementById('modal-confirm').showModal();
    }

    function closeConfirm(res) {
        document.getElementById('modal-confirm').close();
        if(res && confirmCb) confirmCb();
    }

    function toggleTheme() {
        const h = document.documentElement;
        const t = h.classList.contains('dark') ? 'light' : 'dark';
        h.className = t;
        pywebview.api.set_theme(t);
    }

    function render(data) {
        courses = data;
        const grid = document.getElementById('course-grid');
        const addBtn = grid.firstElementChild;
        grid.innerHTML = ''; grid.appendChild(addBtn);
        
        data.forEach(c => {
            const card = document.createElement('div');
            card.className = "card-frost rounded-[2.5rem] p-6 flex flex-col relative group transition-all duration-300";
            
            const strikeUI = c.strikes_count > 0 ? `
                <button onclick="showStrikes('${c.id}')" class="absolute -top-3 -right-3 z-20 bg-red-600 text-white px-4 py-2 rounded-full text-[11px] font-black flex items-center gap-2 shadow-xl shadow-red-600/40 strike-shake">
                    <span class="material-symbols-rounded text-sm">warning</span> ${c.strikes_count}/5
                </button>` : '';

            card.innerHTML = `
                ${strikeUI}
                <div class="absolute top-5 right-5 z-10 flex gap-2">
                    <button onclick="openEdit('${c.id}')" class="w-9 h-9 rounded-2xl bg-white dark:bg-white/10 shadow-lg flex items-center justify-center border dark:border-white/10 hover:scale-110 transition-all">
                        <span class="material-symbols-rounded text-sm light-text">edit</span>
                    </button>
                    <button onclick="delC('${c.id}')" class="w-9 h-9 rounded-2xl bg-red-500/10 shadow-lg flex items-center justify-center border border-red-500/20 hover:bg-red-500 hover:text-white transition-all hover:scale-110">
                        <span class="material-symbols-rounded text-sm">delete</span>
                    </button>
                </div>
                
                <div class="h-36 rounded-[2rem] overflow-hidden bg-slate-200 dark:bg-black/40 mb-5 relative border dark:border-white/5">
                    ${c.logo_b64 ? `<img src="${c.logo_b64}" class="w-full h-full object-cover">` : `<div class="w-full h-full flex items-center justify-center sub-text opacity-20"><span class="material-symbols-rounded text-6xl">school</span></div>`}
                    <div class="absolute bottom-4 left-4 bg-black/60 backdrop-blur-md text-white text-[10px] px-3 py-1 rounded-xl font-black uppercase tracking-widest">${c.platform}</div>
                </div>

                <div class="flex-1">
                    <div class="flex justify-between items-start mb-2 gap-3">
                        <h3 class="font-black text-xl light-text leading-tight truncate">${c.name}</h3>
                        <button onclick="toggleS('${c.id}')" class="w-3 h-3 rounded-full mt-2 shrink-0 ${c.status==='active'?'bg-green-500 shadow-[0_0_12px_#22c55e]':'bg-red-500'}"></button>
                    </div>
                    
                    <div class="flex justify-between text-[11px] font-black sub-text mb-2 uppercase tracking-tighter">
                        <span>Total Progress</span>
                        <span>${c.progress}%</span>
                    </div>
                    <div class="h-2 w-full bg-slate-200 dark:bg-white/5 rounded-full overflow-hidden mb-6">
                        <div class="h-full bg-gradient-to-r from-primary to-secondary" style="width:${c.progress}%"></div>
                    </div>
                </div>

                <div class="bg-white/80 dark:bg-black/30 p-5 rounded-[2rem] border dark:border-white/10 shadow-sm">
                    <div class="flex justify-between text-[11px] font-black mb-3">
                        <span class="uppercase tracking-widest sub-text">Daily Quota</span>
                        <span class="${c.is_quota_met?'text-green-500':'light-text'}">${c.watched_today_count} / ${c.daily_quota}</span>
                    </div>
                    <button onclick="playNext('${c.id}')" class="w-full py-4 rounded-2xl text-[12px] font-black transition-all btn-shine ${c.is_quota_met ? 'bg-green-500/10 text-green-600' : 'bg-primary text-white shadow-xl shadow-primary/30'}">
                        ${c.is_quota_met ? 'DAILY GOAL MET' : 'PLAY NEXT LESSON'}
                    </button>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function openAdd() {
        document.getElementById('modal-title').innerText = "Create Track";
        document.getElementById('c-id').value = "";
        document.getElementById('c-name').value = "";
        document.getElementById('c-plat').value = "";
        document.getElementById('c-folder').value = "";
        document.getElementById('c-logo').value = "";
        document.getElementById('c-quota').value = 3;
        document.getElementById('modal-course').showModal();
    }

    function openEdit(id) {
        const c = courses.find(x => x.id === id);
        document.getElementById('modal-title').innerText = "Edit Track";
        document.getElementById('c-id').value = c.id;
        document.getElementById('c-name').value = c.name;
        document.getElementById('c-plat').value = c.platform;
        document.getElementById('c-folder').value = c.folder;
        document.getElementById('c-logo').value = c.logo;
        document.getElementById('c-quota').value = c.daily_quota;
        document.getElementById('modal-course').showModal();
    }

    function saveC() {
        const i = document.getElementById('c-id').value;
        const n = document.getElementById('c-name').value;
        const p = document.getElementById('c-plat').value;
        const f = document.getElementById('c-folder').value;
        const q = document.getElementById('c-quota').value;
        const l = document.getElementById('c-logo').value;
        if(!n || !f) return;
        if(i) pywebview.api.update_c(i,n,p,f,q,l).then(render);
        else pywebview.api.add_c(n,p,f,q,l).then(render);
        document.getElementById('modal-course').close();
    }

    function playNext(id) {
        const c = courses.find(x => x.id === id);
        if(c.is_quota_met) return;
        pywebview.api.play(id).then(ok => {
            if(ok) {
                openConfirm("Lesson Launched", "Did you complete the full lesson? This updates your daily count.", "success", () => {
                    pywebview.api.mark(id).then(render);
                });
            }
        });
    }

    function showStrikes(id) {
        const c = courses.find(x => x.id === id);
        const list = document.getElementById('strikes-list');
        list.innerHTML = "";
        c.strikes_data.forEach(s => {
            const wrap = document.createElement('div');
            wrap.className = "bg-slate-100 dark:bg-white/5 p-5 rounded-[2rem] border border-red-500/10";
            let vids = "";
            s.videos.forEach(v => {
                const name = v.split(/[\\/]/).pop();
                vids += `<div class="flex justify-between items-center py-3 border-b border-black/5 dark:border-white/5 last:border-0">
                    <span class="text-[12px] font-bold light-text truncate flex-1 mr-4">${name}</span>
                    <button onclick="playS('${id}', '${s.id}', '${v.replace(/\\/g,'\\\\')}')" class="px-4 py-2 bg-red-500 text-white text-[11px] font-black rounded-xl">RESOLVE</button>
                </div>`;
            });
            wrap.innerHTML = `<div class="text-[10px] font-black text-red-500 uppercase tracking-widest mb-3">Missed Day: ${s.date}</div>${vids}`;
            list.appendChild(wrap);
        });
        document.getElementById('modal-strikes').showModal();
    }

    function playS(i, si, fn) {
        pywebview.api.play_strike(i, fn).then(() => {
            openConfirm("Resolution", "Lesson finished? This clears the strike.", "success", () => {
                pywebview.api.resolve(i, si, fn).then(data => {
                    render(data);
                    const updated = data.find(x => x.id === i);
                    if(!updated || updated.strikes_count === 0) document.getElementById('modal-strikes').close();
                    else showStrikes(i);
                });
            });
        });
    }

    function delC(id) { openConfirm("Delete Track?", "This permanently deletes this course and history.", "danger", () => pywebview.api.delete_c(id).then(render)); }
    function toggleS(id) { pywebview.api.toggle_c(id).then(render); }
    function browseF() { pywebview.api.browse_f().then(p => { if(p) document.getElementById('c-folder').value = p; }); }
    function browseL() { pywebview.api.browse_l().then(p => { if(p) document.getElementById('c-logo').value = p; }); }

    window.addEventListener('pywebviewready', () => pywebview.api.get_courses().then(render));
</script>
</body>
</html>
"""

if __name__ == '__main__':
    api = Api()
    cfg = get_settings()
    html = HTML_TEMPLATE.replace('__THEME__', cfg.get('theme', 'dark'))
    window = webview.create_window('FocusFlow Pro', html=html, js_api=api, width=1300, height=850)
    webview.start()
