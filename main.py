import os
import sys
import json
import uuid
import subprocess
import webbrowser
import base64
import mimetypes
import threading
from datetime import date, datetime, timedelta

# =========================================================================
# 1. SYSTEM SETUP & PATH HANDLING
# =========================================================================
APP_NAME = "DailyVideoEnforcer"
app_data = os.getenv('LOCALAPPDATA') or os.path.expanduser("~")
DB_DIR = os.path.join(app_data, APP_NAME)
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)

DATA_PATH = os.path.join(DB_DIR, "courses.json")
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

try:
    import yt_dlp
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    import yt_dlp

# =========================================================================
# 2. ROBUST BACKEND ENGINE
# =========================================================================
class CourseManager:
    def __init__(self):
        self.session_cache = {} 
        self.courses = self.load()

    def load(self):
        if os.path.exists(DATA_PATH):
            try:
                with open(DATA_PATH, 'r') as f:
                    data = json.load(f)
                    today = str(date.today())
                    for c in data:
                        if 'strikes_data' not in c: c['strikes_data'] =[]
                        if 'status' not in c: c['status'] = 'active'
                        if 'last_update_date' not in c: c['last_update_date'] = today
                        if 'watched_today_count' not in c: c['watched_today_count'] = 0
                        if 'last_index' not in c: c['last_index'] = 0
                        if 'type' not in c: c['type'] = 'offline'
                        if 'urls' not in c: c['urls'] =[]
                        c.pop('fetched_videos', None) 
                    return data
            except: pass
        return[]

    def save(self):
        with open(DATA_PATH, 'w') as f: json.dump(self.courses, f, indent=4)

    def fetch_online_videos(self, url):
        try:
            ydl_opts = {
                'extract_flat': 'in_playlist',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info: return[url]
                
                if 'entries' in info and info['entries']:
                    return[e['url'] for e in info['entries'] if e.get('url')]
                else:
                    return[info.get('webpage_url', url)]
        except Exception:
            return [url]

    def get_files(self, c, force_refresh=False):
        if c.get('type') == 'online':
            cid = c['id']
            if force_refresh or cid not in self.session_cache:
                vids =[]
                for u in c.get('urls',[]):
                    vids.extend(self.fetch_online_videos(u))
                self.session_cache[cid] = vids
            return self.session_cache[cid]
        else:
            import re
            folder = c.get('folder')
            if not folder or not os.path.exists(folder): return[]
            exts = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm')
            found =[]
            for r, _, fnames in os.walk(folder):
                for fn in fnames:
                    if fn.lower().endswith(exts):
                        found.append(os.path.relpath(os.path.join(r, fn), folder))
            found.sort(key=lambda text:[int(x) if x.isdigit() else x for x in re.split(r'(\d+)', text)])
            return found

    def refresh_logic(self, mode):
        today = date.today()
        today_str = str(today)
        for c in self.courses:
            if c.get('type', 'offline') != mode: continue

            try: last_d = datetime.strptime(c['last_update_date'], "%Y-%m-%d").date()
            except: last_d = today
            
            if today > last_d:
                if c['status'] == 'active':
                    files = self.get_files(c, force_refresh=True)
                    total_files = len(files)
                    
                    curr_d = last_d
                    while curr_d < today:
                        watched = c.get('watched_today_count', 0) if curr_d == last_d else 0
                        needed = c.get('daily_quota', 3) - watched
                        
                        if needed > 0 and c.get('last_index', 0) < total_files:
                            start = c['last_index']
                            missed = files[start:start+needed]
                            if missed:
                                c['strikes_data'].append({
                                    'id': str(uuid.uuid4()), 
                                    'date': str(curr_d), 
                                    'videos': missed
                                })
                                c['last_index'] += len(missed)
                        curr_d += timedelta(days=1)
                        
                c['watched_today_count'] = 0
                c['last_update_date'] = today_str
        
        self.courses =[c for c in self.courses if len(c.get('strikes_data', [])) < 5]
        self.save()

    def get_data(self, mode="offline", clear_cache=False):
        if clear_cache and mode == "online":
            self.session_cache.clear()

        self.refresh_logic(mode)
        
        result =[]
        for c in self.courses:
            if c.get('type', 'offline') != mode: continue

            files = self.get_files(c)
            total = len(files)
            if c['last_index'] > total: c['last_index'] = total
            c['progress'] = int((min(c['last_index'], total)/total)*100) if total > 0 else 0
            c['total_videos'] = total
            c['is_quota_met'] = c['watched_today_count'] >= c['daily_quota']
            c['strikes_count'] = len(c.get('strikes_data',[]))
            
            c['logo_b64'] = ""
            if c.get('logo'):
                if c['logo'].startswith('http'):
                    c['logo_b64'] = c['logo']
                elif os.path.exists(c['logo']):
                    try:
                        with open(c['logo'], "rb") as f:
                            mime, _ = mimetypes.guess_type(c['logo'])
                            if not mime: mime = "image/png"
                            c['logo_b64'] = f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"
                    except: pass
            
            result.append(c)
        return result

class Api:
    def __init__(self): 
        self.cm = CourseManager()
        self._window = None 

    def open_link(self, url): webbrowser.open(url)
    
    def get_courses_async(self, mode="offline", clear_cache=False): 
        def worker():
            data = self.cm.get_data(mode, clear_cache)
            self._window.evaluate_js(f"finishNetworkMode('{mode}', {json.dumps(data)})")
        threading.Thread(target=worker, daemon=True).start()

    def get_courses_sync(self, mode="offline"):
        return self.cm.get_data(mode, False)
        
    def set_theme(self, t): s = get_settings(); s['theme'] = t; save_settings(s); return True
    def browse_f(self):
        import tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw()
        p=filedialog.askdirectory(); r.destroy(); return p
    def browse_l(self):
        import tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw()
        p=filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        r.destroy(); return p

    def fetch_meta(self, url):
        try:
            ydl_opts = {'extract_flat': 'in_playlist', 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Online Course')
                image = ""
                if info.get('thumbnails'): image = info['thumbnails'][-1].get('url', '')
                elif info.get('entries'):
                    entries = list(info['entries'])
                    if entries and entries[0].get('thumbnails'):
                        image = entries[0]['thumbnails'][-1].get('url', '')
                return {"title": title, "image": image}
        except Exception:
            return {"title": "", "image": ""}

    def add_c(self, n, p, f, q, l, c_type, urls, mode):
        if c_type == 'online' and urls and not n:
            meta = self.fetch_meta(urls[0])
            n = meta['title'] or "Online Course"
            if not l and meta['image']: l = meta['image']
        if not p: p = "Online" if c_type == 'online' else "Local"
            
        c_id = str(uuid.uuid4())
        self.cm.courses.append({
            "id":c_id, "name":n, "platform":p, "folder":f, 
            "type":c_type, "urls":urls, "daily_quota":int(q), 
            "logo":l, "last_index":0, "status":"active", "last_update_date":str(date.today()), 
            "watched_today_count":0, "strikes_data":[]
        })
        self.cm.save(); return self.cm.get_data(mode)

    def update_c(self, i, n, p, f, q, l, c_type, urls, mode):
        for c in self.cm.courses:
            if c['id']==i: 
                c['name']=n; c['platform']=p; c['folder']=f; c['daily_quota']=int(q); c['logo']=l
                c['type']=c_type; c['urls']=urls
                self.cm.session_cache.pop(i, None)
                break
        self.cm.save(); return self.cm.get_data(mode)

    def delete_c(self, i, mode):
        self.cm.courses =[c for c in self.cm.courses if c['id']!=i]
        self.cm.save(); return self.cm.get_data(mode)

    def toggle_c(self, i, mode):
        for c in self.cm.courses:
            if c['id']==i: c['status'] = 'paused' if c['status']=='active' else 'active'
        self.cm.save(); return self.cm.get_data(mode)

    def open_target(self, folder, target):
        if target.startswith('http://') or target.startswith('https://'):
            webbrowser.open(target)
            return True
        else:
            path = os.path.join(folder, target) if folder else target
            if os.path.exists(path):
                os.startfile(path)
                return True
            return False

    def play(self, i):
        for c in self.cm.courses:
            if c['id']==i:
                fs = self.cm.get_files(c)
                if c['last_index'] < len(fs):
                    return self.open_target(c.get('folder', ''), fs[c['last_index']])
        return False
        
    def play_specific(self, i, index):
        for c in self.cm.courses:
            if c['id'] == i:
                fs = self.cm.get_files(c)
                if index < len(fs):
                    return self.open_target(c.get('folder', ''), fs[index])
        return False

    def reset_progress(self, i, mode):
        for c in self.cm.courses:
            if c['id'] == i:
                c['last_index'] = 0
                c['watched_today_count'] = 0
                c['strikes_data'] =[]
                break
        self.cm.save()
        return self.cm.get_data(mode)

    def mark(self, i, mode):
        for c in self.cm.courses:
            if c['id']==i: c['last_index']+=1; c['watched_today_count']+=1; break
        self.cm.save(); return self.cm.get_data(mode)

    def play_strike(self, i, fn):
        for c in self.cm.courses:
            if c['id']==i: return self.open_target(c.get('folder', ''), fn)
        return False

    def resolve(self, i, si, fn, mode):
        for c in self.cm.courses:
            if c['id']==i:
                for s in c['strikes_data']:
                    if s['id']==si:
                        if fn in s['videos']: s['videos'].remove(fn)
                        if not s['videos']: c['strikes_data'].remove(s)
                        break
        self.cm.save(); return self.cm.get_data(mode)


# =========================================================================
# 3. HIGH-CONTRAST GLOSSY FRONTEND 
# =========================================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en" class="__THEME__">
<head>
    <meta charset="utf-8"/><meta content="width=device-width, initial-scale=1.0" name="viewport"/>
    <style>
        :root {
            /* Light theme vars */
            --bg: #f8fafc;
            --glass: rgba(255, 255, 255, 0.85);
            --text-main: #1e293b;
            --text-muted: #64748b;
            --primary: #8b5cf6;
            --primary-hover: #7c3aed;
            --secondary: #3b82f6;
            --card-bg: rgba(255, 255, 255, 0.6);
            --border: rgba(0,0,0,0.08);
            --danger: #ef4444;
            --danger-bg: #fef2f2;
            --success: #22c55e;
            --input-bg: #f1f5f9;
        }
        .dark {
            /* Dark theme vars */
            --bg: #08080a;
            --glass: rgba(18, 18, 24, 0.8);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --card-bg: rgba(255, 255, 255, 0.03);
            --border: rgba(255,255,255,0.08);
            --danger-bg: rgba(239, 68, 68, 0.1);
            --input-bg: rgba(0,0,0,0.4);
        }
        
        body {
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0; padding: 0; min-height: 100vh;
            transition: background-color 0.3s, color 0.3s;
        }
        * { box-sizing: border-box; }
        .hidden { display: none !important; }
        
        .flex { display: flex; }
        .flex-row { display: flex; gap: 0.75rem; }
        .flex-1 { flex: 1; }
        .items-center { align-items: center; }
        .justify-between { justify-content: space-between; }
        .justify-center { justify-content: center; }
        .text-center { text-align: center; }
        .w-full { width: 100%; }
        .mb-2 { margin-bottom: 0.5rem; }
        .mb-4 { margin-bottom: 1rem; }
        .mt-4 { margin-top: 1rem; }
        
        h1, h2, h3, h4, p { margin: 0; }
        .text-xl { font-size: 1.25rem; font-weight: 900; }
        .text-danger { color: var(--danger); }
        .text-muted { color: var(--text-muted); }
        
        svg { width: 20px; height: 20px; flex-shrink: 0; }

        .navbar {
            display: flex; justify-content: space-between; align-items: center;
            height: 64px; padding: 0 2.5rem;
            background: var(--glass); backdrop-filter: blur(25px);
            border-bottom: 1px solid var(--border);
            position: sticky; top: 0; z-index: 50;
        }
        .nav-left, .nav-right { display: flex; align-items: center; gap: 1.5rem; }
        
        .btn-icon {
            width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
            background: transparent; border: 1px solid var(--border); color: var(--text-main);
            cursor: pointer; transition: 0.2s;
        }
        .btn-icon:hover { background: var(--border); transform: scale(1.1); }
        
        .btn-mode {
            display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 1.25rem; border-radius: 2rem;
            border: 1px solid var(--border); background: var(--glass); cursor: pointer; color: var(--text-muted); font-weight: bold; transition: 0.2s; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        .btn-mode:hover { color: var(--primary); transform: scale(1.05); }
        .btn-mode.online { color: var(--success); border-color: rgba(34, 197, 94, 0.3); }
        .btn-mode.disabled { pointer-events: none; opacity: 0.8; }

        .btn { padding: 1.25rem 2rem; border-radius: 1.5rem; border: none; font-weight: 800; cursor: pointer; transition: 0.3s; text-align: center; font-size: 0.9rem; position: relative; overflow: hidden; }
        .btn:disabled { opacity: 0.6; pointer-events: none; }
        .btn::after { content: ""; position: absolute; top: -50%; left: -150%; width: 200%; height: 200%; background: linear-gradient(45deg, transparent, rgba(255,255,255,0.3), transparent); transform: rotate(45deg); transition: 0.8s; }
        .btn:hover::after { left: 150%; }
        
        .btn-primary { background: var(--primary); color: white; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3); }
        .btn-primary:hover { background: var(--primary-hover); transform: translateY(-2px); }
        .btn-danger { background: var(--danger); color: white; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.3); }
        .btn-outline { background: transparent; color: var(--text-muted); }
        .btn-outline:hover { color: var(--text-main); }
        .btn-small { padding: 0.5rem 1rem; border-radius: 0.75rem; font-size: 0.75rem; }

        .container { max-width: 1440px; margin: 0 auto; padding: 2.5rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 2rem; }
        
        .card {
            background: var(--card-bg); border: 1px solid var(--border); border-radius: 2.5rem; padding: 1.5rem;
            display: flex; flex-direction: column; position: relative; transition: 0.3s;
            box-shadow: 0 4px 20px rgba(0,0,0,0.04); min-height: 340px;
        }
        .dark .card { box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .card:hover { border-color: var(--primary); transform: translateY(-5px); }
        
        .card-add { align-items: center; justify-content: center; border: 2px dashed var(--border); cursor: pointer; text-align: center; }
        .card-add:hover { border-color: var(--primary); }
        .card-add-icon { width: 64px; height: 64px; border-radius: 1.5rem; background: rgba(139, 92, 246, 0.1); display: flex; align-items: center; justify-content: center; color: var(--primary); margin-bottom: 1rem; transition: 0.3s; }
        .card-add-icon svg { width: 36px; height: 36px; }
        .card-add:hover .card-add-icon { transform: scale(1.1); }
        
        .card-actions { position: absolute; top: 1.25rem; right: 1.25rem; display: flex; gap: 0.5rem; z-index: 10; }
        .card-action-btn { width: 36px; height: 36px; border-radius: 1rem; background: var(--glass); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; color: var(--text-muted); transition: 0.2s; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        .card-action-btn:hover { color: var(--primary); transform: scale(1.1); border-color: var(--primary); }
        .card-action-btn.delete:hover { color: white; background: var(--danger); border-color: var(--danger); }
        
        .card-img-wrapper { height: 144px; border-radius: 2rem; overflow: hidden; position: relative; background: var(--input-bg); margin-bottom: 1.25rem; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; }
        .card-img-wrapper img { width: 100%; height: 100%; object-fit: cover; }
        .card-platform { position: absolute; bottom: 1rem; left: 1rem; background: rgba(0,0,0,0.6); backdrop-filter: blur(5px); color: white; font-size: 0.65rem; font-weight: 900; padding: 0.3rem 0.75rem; border-radius: 0.75rem; text-transform: uppercase; letter-spacing: 1px; }
        
        .card-title { font-size: 1.25rem; font-weight: 900; margin: 0 0 0.5rem 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
        .status-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; cursor: pointer; margin-top: 4px; border: none; }
        .status-active { background: var(--success); box-shadow: 0 0 12px var(--success); }
        .status-paused { background: var(--danger); }
        
        .progress-info { display: flex; justify-content: space-between; font-size: 0.7rem; font-weight: 900; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.5rem; letter-spacing: -0.5px; }
        .progress-bar-bg { width: 100%; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; margin-bottom: 1.5rem; }
        .progress-bar-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--secondary)); transition: width 0.3s; }
        
        .quota-box { background: var(--glass); padding: 1.25rem; border-radius: 2rem; border: 1px solid var(--border); margin-top: auto; box-shadow: 0 2px 5px rgba(0,0,0,0.02); }
        .quota-info { display: flex; justify-content: space-between; font-size: 0.7rem; font-weight: 900; margin-bottom: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }
        .quota-met .btn-primary { background: rgba(34, 197, 94, 0.1); color: var(--success); box-shadow: none; border: none; }
        
        .strike-badge { position: absolute; top: -12px; right: -12px; background: var(--danger); color: white; padding: 0.5rem 1rem; border-radius: 2rem; font-size: 0.7rem; font-weight: 900; z-index: 20; display: flex; align-items: center; gap: 0.5rem; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.4); cursor: pointer; animation: shake 0.4s infinite; border: none; outline: none; }
        
        /* ==========================================================
           REWRITTEN MODAL SYSTEM (Div overlays instead of Dialogs)
           ========================================================== */
        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
            display: flex; align-items: center; justify-content: center;
            z-index: 1000;
            opacity: 0; pointer-events: none; transition: 0.2s ease-in-out;
            padding: 2rem;
        }
        .modal-overlay.active {
            opacity: 1; pointer-events: auto;
        }
        
        /* Force Confirm Modal above everything else */
        #modal-confirm { z-index: 2000; }
        
        .modal-content {
            background: var(--glass); border: 1px solid var(--border); border-radius: 3rem;
            padding: 2.5rem; width: 100%; max-height: 90vh; overflow-y: auto;
            box-shadow: 0 25px 50px rgba(0,0,0,0.25);
            transform: scale(0.95) translateY(10px); transition: 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
            color: var(--text-main);
        }
        .modal-overlay.active .modal-content {
            transform: scale(1) translateY(0);
        }

        .modal-sm { max-width: 400px; }
        .modal-md { max-width: 450px; }
        .modal-lg { max-width: 768px; }
        
        .modal-title { font-size: 1.8rem; font-weight: 900; margin-bottom: 2rem; display: flex; align-items: center; gap: 0.75rem; }
        
        .form-group { margin-bottom: 1.25rem; }
        .form-label { display: flex; justify-content: space-between; font-size: 0.7rem; font-weight: 900; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem; margin-left: 1rem; }
        .form-input { width: 100%; padding: 1.25rem; border-radius: 1.5rem; border: 1px solid var(--border); background: var(--input-bg); color: var(--text-main); font-size: 0.85rem; outline: none; transition: 0.2s; }
        .form-input:focus { border-color: var(--primary); box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2); }
        .url-wrapper { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
        
        .progress-grid-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(32px, 1fr)); gap: 6px; max-height: 40vh; overflow-y: auto; padding-right: 0.5rem; margin-bottom: 1rem; }
        .progress-box { width: 32px; height: 32px; border-radius: 0.5rem; border: 2px solid var(--border); background: var(--input-bg); display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.2s; color: transparent; }
        .progress-box:hover { border-color: var(--primary); transform: scale(1.1); }
        .progress-box.watched { background: var(--primary); border-color: var(--primary); color: white; }
        .progress-box svg { width: 18px; height: 18px; }

        .strike-item { background: var(--danger-bg); border: 1px solid rgba(239, 68, 68, 0.1); padding: 1.25rem; border-radius: 2rem; margin-bottom: 1rem; }
        .strike-date { font-size: 0.65rem; color: var(--danger); font-weight: 900; text-transform: uppercase; margin-bottom: 0.75rem; letter-spacing: 1px; }
        .strike-video { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05); }
        .dark .strike-video { border-bottom-color: rgba(255, 255, 255, 0.05); }
        .strike-video:last-child { border-bottom: none; }
        .strike-video span { font-size: 0.75rem; font-weight: 800; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; flex: 1; margin-right: 1rem; }
        
        .animate-spin { animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        @keyframes shake { 0%, 100% { transform: rotate(0deg); } 25% { transform: rotate(-6deg); } 75% { transform: rotate(6deg); } }
        
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(139, 92, 246, 0.3); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(139, 92, 246, 0.6); }
    </style>
</head>
<body>

<nav class="navbar">
    <div class="nav-left">
        <button id="mode-btn" onclick="toggleNetworkMode()" class="btn-mode">
            <span id="mode-icon"></span>
            <span id="mode-text">Offline</span>
        </button>
        <div onclick="pywebview.api.open_link('https://github.com/Glax3210')" style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;font-weight:900;font-size:1.25rem;letter-spacing:-0.5px;">
            <div style="width:36px;height:36px;background:var(--primary);border-radius:0.75rem;display:flex;align-items:center;justify-content:center;color:white;box-shadow:0 4px 10px rgba(139, 92, 246, 0.4);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:20px;height:20px;"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2l.5-.5m5.5-8.5l-2 2m-2-2l-2 2M21.5 2.5a15.92 15.92 0 00-6.5 2c-3.1 1.7-6.23 4.88-8 8-.5.83-.88 1.74-1 2.5l5.5 5.5c.76-.12 1.67-.5 2.5-1 3.12-1.77 6.3-4.9 8-8a15.92 15.92 0 002-6.5zM12 12a2 2 0 100-4 2 2 0 000 4z"/></svg>
            </div>
            <span class="hidden" style="display:block;">CourseTracker <span style="color:var(--primary)">Pro</span></span>
        </div>
    </div>
    <div class="nav-right">
        <button onclick="toggleTheme()" class="btn-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        </button>
    </div>
</nav>

<main class="container">
    <div id="course-grid" class="grid"></div>
</main>

<!-- ALL MODALS NOW USE DIV OVERLAYS -->
<div id="modal-confirm" class="modal-overlay">
    <div class="modal-content modal-sm text-center">
        <div id="confirm-bg" style="width:80px;height:80px;border-radius:2rem;margin:0 auto 1.5rem;display:flex;align-items:center;justify-content:center;color:white;box-shadow:0 10px 20px rgba(0,0,0,0.1);">
            <span id="confirm-icon" style="display:flex;"></span>
        </div>
        <h3 id="confirm-title" class="modal-title justify-center" style="margin-bottom:0.5rem;">Confirm Action</h3>
        <p id="confirm-msg" class="text-muted" style="margin-bottom:2.5rem;line-height:1.6;font-size:0.9rem;"></p>
        <div class="flex-row">
            <button onclick="closeConfirm(false)" class="btn btn-outline flex-1">Cancel</button>
            <button id="confirm-btn" onclick="closeConfirm(true)" class="btn flex-1">Yes, Proceed</button>
        </div>
    </div>
</div>

<div id="modal-course" class="modal-overlay">
    <div class="modal-content modal-md">
        <h3 id="modal-title" class="modal-title">Course Details</h3>
        <input type="hidden" id="c-id">
        
        <div class="form-group">
            <label class="form-label">Name & Platform</label>
            <input id="c-name" type="text" placeholder="Course Name" class="form-input mb-2">
            <input id="c-plat" type="text" placeholder="Platform (e.g. Udemy/YouTube)" class="form-input">
        </div>
        
        <div id="offline-fields" class="form-group">
            <label class="form-label">Source Folder</label>
            <div class="flex-row">
                <input id="c-folder" readonly placeholder="Pick folder..." class="form-input flex-1" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                <button onclick="browseF()" class="btn btn-primary btn-small" style="padding:0 1.5rem;">Browse</button>
            </div>
        </div>

        <div id="online-fields" class="form-group hidden">
            <label class="form-label">
                <span>Playlist / Video URLs</span>
                <span onclick="addUrlInput('')" style="color:var(--primary);cursor:pointer;display:flex;align-items:center;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;"><path d="M12 5v14m-7-7h14"/></svg>
                </span>
            </label>
            <div id="url-container" style="max-height:160px;overflow-y:auto;padding-right:0.5rem;"></div>
        </div>

        <div class="form-group">
            <label class="form-label">Custom Logo (Optional)</label>
            <div class="flex-row">
                <input id="c-logo" readonly placeholder="Pick image..." class="form-input flex-1" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                <button onclick="browseL()" class="btn btn-outline btn-small" style="padding:0 1.5rem;border:1px solid var(--border);">Image</button>
            </div>
        </div>
        
        <div class="form-group">
            <label class="form-label">Daily Video Quota</label>
            <input id="c-quota" type="number" value="3" class="form-input">
        </div>
        
        <div class="flex-row mt-4" style="padding-top:1rem;">
            <button onclick="closeModal('modal-course')" class="btn btn-outline flex-1">Cancel</button>
            <button id="btn-save-course" onclick="saveC()" class="btn btn-primary flex-1" style="flex:2;">Save Track</button>
        </div>
    </div>
</div>

<div id="modal-strikes" class="modal-overlay">
    <div class="modal-content modal-md" style="display:flex;flex-direction:column;">
        <h3 class="modal-title" style="color:var(--danger);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:32px;height:32px;animation:shake 0.4s infinite;"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4m0 4h.01"/></svg>
            Pending Strikes
        </h3>
        <div id="strikes-list" style="flex:1;overflow-y:auto;padding-right:0.5rem;max-height: 40vh;"></div>
        <button onclick="closeModal('modal-strikes')" class="btn btn-outline w-full mt-4" style="background:var(--input-bg);">Got it</button>
    </div>
</div>

<div id="modal-progress" class="modal-overlay">
    <div class="modal-content modal-lg" style="display:flex;flex-direction:column;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2rem;">
            <h3 class="modal-title" style="margin:0;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--primary);width:32px;height:32px;"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg>
                Video Progress
            </h3>
            <button id="btn-reset-progress" class="btn btn-danger btn-small" style="display:flex;align-items:center;gap:0.5rem;background:transparent;color:var(--danger);border:1px solid var(--danger);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;"><path d="M3 12a9 9 0 109-9 9.75 9.75 0 00-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                Reset Progress
            </button>
        </div>
        <div id="progress-grid-container" class="progress-grid-container"></div>
        <button onclick="closeModal('modal-progress')" class="btn btn-outline w-full mt-4" style="background:var(--input-bg);">Close Grid</button>
    </div>
</div>

<script>
    const ICONS = {
        wifiOff: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 1l22 22M16.72 11.06A10.94 10.94 0 0119 12.55M5 12.55a10.94 10.94 0 015.17-2.39M10.71 5.05A16 16 0 0122.58 9M1.42 9a15.91 15.91 0 014.7-2.88M8.53 16.11a6 6 0 016.95 0M12 20h.01"/></svg>`,
        wifiOn: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0114.08 0M1.42 9a16 16 0 0121.16 0M8.53 16.11a6 6 0 016.95 0M12 20h.01"/></svg>`,
        sync: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="animate-spin"><path d="M21 2v6h-6M3 12a9 9 0 0115-6.7L21 8M3 22v-6h6M21 12a9 9 0 01-15 6.7L3 16"/></svg>`,
        add: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14m-7-7h14"/></svg>`,
        grid: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg>`,
        edit: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`,
        delete: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>`,
        warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:36px;height:36px;"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4m0 4h.01"/></svg>`,
        check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="width:40px;height:40px;"><path d="M20 6L9 17l-5-5"/></svg>`,
        checkSmall: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>`,
        close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
        school: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:64px;height:64px;"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>`
    };

    let courses =[];
    let confirmCb = null;
    let appMode = 'offline';

    document.getElementById('mode-icon').innerHTML = ICONS.wifiOff;

    // ==========================================
    // BULLETPROOF DIV-BASED MODAL SYSTEM
    // ==========================================
    function openModal(id) {
        // Only one primary modal can exist at once
        if (id !== 'modal-confirm') {
            document.querySelectorAll('.modal-overlay').forEach(m => {
                if (m.id !== 'modal-confirm') m.classList.remove('active');
            });
        }
        document.getElementById(id).classList.add('active');
    }

    function closeModal(id) {
        document.getElementById(id).classList.remove('active');
    }

    // Close on background click (ignores confirm modal intentionally)
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll('.modal-overlay').forEach(m => {
            m.addEventListener('click', (e) => {
                if (e.target === m && m.id !== 'modal-confirm') {
                    closeModal(m.id);
                }
            });
        });
    });

    function finishNetworkMode(mode, data) {
        appMode = mode;
        const btn = document.getElementById('mode-btn');
        const icon = document.getElementById('mode-icon');
        const text = document.getElementById('mode-text');

        btn.classList.remove('disabled');
        
        if (appMode === 'online') {
            icon.innerHTML = ICONS.wifiOn;
            text.innerText = 'Online';
            btn.className = 'btn-mode online';
        } else {
            icon.innerHTML = ICONS.wifiOff;
            text.innerText = 'Offline';
            btn.className = 'btn-mode';
        }
        
        render(data);
    }

    function toggleNetworkMode() {
        const targetMode = appMode === 'offline' ? 'online' : 'offline';
        const btn = document.getElementById('mode-btn');
        const icon = document.getElementById('mode-icon');
        const text = document.getElementById('mode-text');
        
        if (btn.classList.contains('disabled')) return;
        btn.classList.add('disabled');

        icon.innerHTML = ICONS.sync;
        text.innerText = 'Loading...';

        pywebview.api.get_courses_async(targetMode, targetMode === 'online').catch(e => console.error(e));
    }

    function openConfirm(title, msg, type, cb) {
        // Automatically close itself before opening to prevent weird states
        closeModal('modal-confirm'); 
        
        document.getElementById('confirm-title').innerText = title;
        document.getElementById('confirm-msg').innerText = msg;
        
        const bg = document.getElementById('confirm-bg');
        const btn = document.getElementById('confirm-btn');
        const icon = document.getElementById('confirm-icon');
        
        if(type === 'danger') {
            bg.style.background = 'var(--danger)';
            bg.style.boxShadow = '0 10px 20px rgba(239, 68, 68, 0.3)';
            btn.className = 'btn btn-danger flex-1';
            icon.innerHTML = ICONS.warning;
        } else {
            bg.style.background = 'var(--primary)';
            bg.style.boxShadow = '0 10px 20px rgba(139, 92, 246, 0.3)';
            btn.className = 'btn btn-primary flex-1';
            icon.innerHTML = ICONS.check;
        }
        confirmCb = cb;
        openModal('modal-confirm');
    }

    function closeConfirm(res) {
        closeModal('modal-confirm');
        const cb = confirmCb;
        confirmCb = null; 
        if(res && cb) cb();
    }

    function toggleTheme() {
        const h = document.documentElement;
        const t = h.classList.contains('dark') ? 'light' : 'dark';
        h.className = t;
        pywebview.api.set_theme(t).catch(e => console.error(e));
    }

    function render(data) {
        if(data) courses = data;
        renderGrid();
    }

    function renderGrid() {
        const grid = document.getElementById('course-grid');
        grid.innerHTML = `
            <div onclick="openAdd()" class="card card-add">
                <div class="card-add-icon">${ICONS.add}</div>
                <p style="font-weight:900;color:var(--text-muted);">${appMode === 'online' ? 'New Online Track' : 'New Offline Track'}</p>
            </div>
        `;
        
        courses.forEach(c => {
            const card = document.createElement('div');
            card.className = "card";
            
            const strikeUI = c.strikes_count > 0 ? `
                <button onclick="showStrikes('${c.id}')" class="strike-badge">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4m0 4h.01"/></svg>
                    ${c.strikes_count}/5
                </button>` : '';

            card.innerHTML = `
                ${strikeUI}
                <div class="card-actions">
                    <button onclick="openProgressGrid('${c.id}')" title="Grid" class="card-action-btn">${ICONS.grid}</button>
                    <button onclick="openEdit('${c.id}')" title="Edit" class="card-action-btn">${ICONS.edit}</button>
                    <button onclick="delC('${c.id}')" title="Delete" class="card-action-btn delete">${ICONS.delete}</button>
                </div>
                
                <div class="card-img-wrapper">
                    ${c.logo_b64 ? `<img src="${c.logo_b64}">` : `<div style="color:var(--text-muted);opacity:0.2;">${ICONS.school}</div>`}
                    <div class="card-platform">${c.platform}</div>
                </div>

                <div style="flex:1; display:flex; flex-direction:column;">
                    <h3 class="card-title">
                        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;">${c.name}</span>
                        <button onclick="toggleS('${c.id}')" class="status-dot ${c.status==='active'?'status-active':'status-paused'}" title="Toggle Pause"></button>
                    </h3>
                    
                    <div class="progress-info">
                        <span>Total Progress</span>
                        <span>${c.progress}%</span>
                    </div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width:${c.progress}%"></div>
                    </div>
                </div>

                <div class="quota-box ${c.is_quota_met?'quota-met':''}">
                    <div class="quota-info">
                        <span>Daily Quota</span>
                        <span style="color:${c.is_quota_met?'var(--success)':'var(--text-main)'}">${c.watched_today_count} / ${c.daily_quota}</span>
                    </div>
                    <button onclick="playNext('${c.id}', this)" class="btn btn-primary w-full" style="padding:1rem;">
                        ${c.is_quota_met ? 'DAILY GOAL MET' : 'PLAY NEXT LESSON'}
                    </button>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function setupModeFields(type) {
        if(type === 'online') {
            document.getElementById('offline-fields').classList.add('hidden');
            document.getElementById('online-fields').classList.remove('hidden');
            document.getElementById('c-name').placeholder = "Course Name (Leave blank to auto-fetch)";
        } else {
            document.getElementById('offline-fields').classList.remove('hidden');
            document.getElementById('online-fields').classList.add('hidden');
            document.getElementById('c-name').placeholder = "Course Name";
        }
    }

    function removeUrlInput(btn) { btn.parentElement.remove(); }
    
    function addUrlInput(val = '') {
        const div = document.createElement('div');
        div.className = "url-wrapper";
        div.innerHTML = `
            <input type="text" value="${val}" placeholder="https://..." class="form-input flex-1 url-input" style="padding:1rem;">
            <button onclick="removeUrlInput(this)" class="btn-icon" style="color:var(--danger);border-color:var(--danger);border-radius:1rem;">${ICONS.close}</button>
        `;
        document.getElementById('url-container').appendChild(div);
    }

    function openAdd() {
        document.getElementById('modal-title').innerHTML = appMode === 'online' ? `${ICONS.add} Create Online Track` : `${ICONS.add} Create Track`;
        document.getElementById('c-id').value = "";
        document.getElementById('c-name').value = "";
        document.getElementById('c-plat').value = "";
        document.getElementById('c-folder').value = "";
        document.getElementById('c-logo').value = "";
        document.getElementById('c-quota').value = 3;
        
        setupModeFields(appMode);
        document.getElementById('url-container').innerHTML = '';
        if(appMode === 'online') addUrlInput('');
        
        openModal('modal-course');
    }

    function openEdit(id) {
        const c = courses.find(x => x.id === id);
        const type = c.type || 'offline';
        document.getElementById('modal-title').innerHTML = `${ICONS.edit} Edit Track`;
        document.getElementById('c-id').value = c.id;
        document.getElementById('c-name').value = c.name;
        document.getElementById('c-plat').value = c.platform;
        document.getElementById('c-folder').value = c.folder || "";
        document.getElementById('c-logo').value = c.logo || "";
        document.getElementById('c-quota').value = c.daily_quota;
        
        setupModeFields(type);
        document.getElementById('url-container').innerHTML = '';
        if(type === 'online') {
            if(c.urls && c.urls.length) c.urls.forEach(u => addUrlInput(u));
            else addUrlInput('');
        }
        openModal('modal-course');
    }

    function openProgressGrid(id) {
        const c = courses.find(x => x.id === id);
        const container = document.getElementById('progress-grid-container');
        container.innerHTML = '';
        
        const btnReset = document.getElementById('btn-reset-progress');
        btnReset.onclick = () => resetCourseProgress(id);
        
        for (let i = 0; i < c.total_videos; i++) {
            const box = document.createElement('div');
            const isChecked = i < c.last_index;
            
            box.className = "progress-box" + (isChecked ? " watched" : "");
            box.title = `Play Video ${i + 1}`;
            box.onclick = () => pywebview.api.play_specific(id, i).catch(e => console.error(e));
            
            if (isChecked) box.innerHTML = ICONS.checkSmall;
            container.appendChild(box);
        }
        
        if(c.total_videos === 0) {
            container.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--text-muted);font-weight:bold;padding:2rem 0;">No videos tracked for this course.</p>`;
        }
        openModal('modal-progress');
    }
    
    function resetCourseProgress(id) {
        openConfirm("Reset Progress?", "This will wipe all watched history, clear strikes, and start this track from 0%. Are you sure?", "danger", () => {
            pywebview.api.reset_progress(id, appMode).then(data => {
                render(data);
                openProgressGrid(id); 
            }).catch(e => console.error(e));
        });
    }

    function saveC() {
        const btn = document.getElementById('btn-save-course');
        
        // Prevent multiple clicks
        if (btn.disabled) return;
        btn.disabled = true;
        btn.innerHTML = `<span style="display:flex;align-items:center;justify-content:center;gap:0.5rem;">${ICONS.sync} Saving...</span>`;

        const i = document.getElementById('c-id').value;
        const n = document.getElementById('c-name').value;
        const p = document.getElementById('c-plat').value;
        const f = document.getElementById('c-folder').value;
        const q = document.getElementById('c-quota').value;
        const l = document.getElementById('c-logo').value;
        
        const isOnline = !document.getElementById('online-fields').classList.contains('hidden');
        let urls =[];
        if(isOnline) {
            urls = Array.from(document.querySelectorAll('.url-input')).map(el => el.value).filter(v => v.trim() !== '');
            if(urls.length === 0) {
                btn.innerHTML = `Save Track`;
                btn.disabled = false;
                return;
            }
        } else {
            if(!n || !f) {
                btn.innerHTML = `Save Track`;
                btn.disabled = false;
                return;
            }
        }

        const type = isOnline ? 'online' : 'offline';

        const req = i ? pywebview.api.update_c(i,n,p,f,q,l,type,urls, appMode) : pywebview.api.add_c(n,p,f,q,l,type,urls, appMode);
        req.then(data => {
            render(data);
            btn.innerHTML = `Save Track`;
            btn.disabled = false;
            closeModal('modal-course');
        }).catch(e => {
            console.error(e);
            btn.innerHTML = `Save Track`;
            btn.disabled = false;
        });
    }

    function playNext(id, btnElement) {
        const c = courses.find(x => x.id === id);
        if(c.is_quota_met) return;
        
        if (btnElement.disabled) return;
        btnElement.disabled = true;
        
        const originalHTML = btnElement.innerHTML;
        btnElement.innerHTML = `LAUNCHING...`;

        pywebview.api.play(id).then(ok => {
            btnElement.innerHTML = originalHTML;
            btnElement.disabled = false;
            if(ok) {
                openConfirm("Lesson Launched", "Did you complete the full lesson? This updates your daily count.", "success", () => {
                    pywebview.api.mark(id, appMode).then(render).catch(e => console.error(e));
                });
            }
        }).catch(e => {
            console.error(e);
            btnElement.innerHTML = originalHTML;
            btnElement.disabled = false;
        });
    }

    function showStrikes(id) {
        const c = courses.find(x => x.id === id);
        const list = document.getElementById('strikes-list');
        list.innerHTML = "";
        c.strikes_data.forEach(s => {
            const wrap = document.createElement('div');
            wrap.className = "strike-item";
            let vids = "";
            s.videos.forEach(v => {
                const name = v.startsWith('http') ? (v.split('v=')[1] || "Online Video") : v.split(/[\\/]/).pop();
                vids += `<div class="strike-video">
                    <span title="${name}">${name}</span>
                    <button onclick="playS('${id}', '${s.id}', '${v.replace(/\\/g,'\\\\')}', this)" class="btn btn-danger btn-small" style="font-weight:900;">RESOLVE</button>
                </div>`;
            });
            wrap.innerHTML = `<div class="strike-date">Missed Day: ${s.date}</div>${vids}`;
            list.appendChild(wrap);
        });
        openModal('modal-strikes');
    }

    function playS(i, si, fn, btnElement) {
        if (btnElement.disabled) return;
        btnElement.disabled = true;
        const originalHTML = btnElement.innerHTML;
        btnElement.innerHTML = `...`;

        pywebview.api.play_strike(i, fn).then((ok) => {
            btnElement.innerHTML = originalHTML;
            btnElement.disabled = false;
            
            if (ok) {
                openConfirm("Resolution", "Lesson finished? This clears the strike.", "success", () => {
                    pywebview.api.resolve(i, si, fn, appMode).then(data => {
                        render(data);
                        const updated = data.find(x => x.id === i);
                        if(!updated || updated.strikes_count === 0) closeModal('modal-strikes');
                        else showStrikes(i);
                    }).catch(e => console.error(e));
                });
            }
        }).catch(e => {
            console.error(e);
            btnElement.innerHTML = originalHTML;
            btnElement.disabled = false;
        });
    }

    function delC(id) { openConfirm("Delete Track?", "This permanently deletes this course and history.", "danger", () => pywebview.api.delete_c(id, appMode).then(render).catch(e => console.error(e))); }
    function toggleS(id) { pywebview.api.toggle_c(id, appMode).then(render).catch(e => console.error(e)); }
    function browseF() { pywebview.api.browse_f().then(p => { if(p) document.getElementById('c-folder').value = p; }).catch(e => console.error(e)); }
    function browseL() { pywebview.api.browse_l().then(p => { if(p) document.getElementById('c-logo').value = p; }).catch(e => console.error(e)); }

    window.addEventListener('pywebviewready', () => {
        pywebview.api.get_courses_sync('offline').then(render).catch(e => console.error(e));
    });
</script>
</body>
</html>
"""

if __name__ == '__main__':
    api = Api()
    cfg = get_settings()
    html = HTML_TEMPLATE.replace('__THEME__', cfg.get('theme', 'dark'))
    window = webview.create_window('CourseTracker Pro', html=html, js_api=api, width=1300, height=850)
    api._window = window 
    webview.start()
