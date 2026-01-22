import os
import sys
import json
import uuid
import subprocess
import threading
import re
from datetime import date, datetime

# =========================================================================
# 1. SETUP & DATA PATHS
# =========================================================================

APP_NAME_DIR = "DailyVideoEnforcer"
local_app_data = os.getenv('LOCALAPPDATA')
if not local_app_data:
    local_app_data = os.path.expanduser("~")

APP_DIR = os.path.join(local_app_data, APP_NAME_DIR)
if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)

DATA_FILE = os.path.join(APP_DIR, "courses.json")

if not getattr(sys, 'frozen', False):
    def install_package(package):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except:
            pass
    try:
        import webview
    except ImportError:
        install_package("pywebview")
        import webview
else:
    import webview

# =========================================================================
# 2. BACKEND LOGIC (Course Manager)
# =========================================================================

class CourseManager:
    def __init__(self):
        self.courses = self.load_data()

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    today_str = str(date.today())
                    for c in data:
                        if 'status' not in c: c['status'] = 'active'
                        if 'last_update_date' not in c: c['last_update_date'] = today_str
                        if 'watched_today_count' not in c: c['watched_today_count'] = 0
                        if 'strikes_data' not in c: c['strikes_data'] = []
                        # Legacy cleanup
                        if 'strikes' in c and isinstance(c['strikes'], int) and c['strikes'] > 0 and not c['strikes_data']:
                            for _ in range(c['strikes']): c['strikes_data'].append({'date': 'Legacy', 'videos': []})
                    return data
            except:
                pass
        return []

    def save_data(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.courses, f, indent=4)

    def get_video_files(self, folder):
        """
        Recursively finds all video files in folder and subfolders.
        Returns a list of RELATIVE paths (e.g. "Subfolder\video.mp4")
        sorted naturally.
        """
        if not folder or not os.path.exists(folder):
            return []
        
        valid_exts = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm')
        files = []

        # Walk through all directories
        for root, dirs, filenames in os.walk(folder):
            for filename in filenames:
                if filename.lower().endswith(valid_exts):
                    # Get full path
                    full_path = os.path.join(root, filename)
                    # Convert to relative path (so we store "Module 1\Video.mp4")
                    rel_path = os.path.relpath(full_path, folder)
                    files.append(rel_path)
        
        # Natural Sort (handles numbers correctly: 2.mp4 comes before 10.mp4)
        def natural_keys(text): 
            return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]
        
        files.sort(key=natural_keys)
        return files

    def process_daily_schedule(self):
        today = date.today()
        today_str = str(today)
        changed = False
        active_courses = []

        for c in self.courses:
            if 'status' not in c: c['status'] = 'active'
            if 'last_update_date' not in c: c['last_update_date'] = today_str
            if 'watched_today_count' not in c: c['watched_today_count'] = 0
            if 'strikes_data' not in c: c['strikes_data'] = []
            
            try: last_date = datetime.strptime(c['last_update_date'], "%Y-%m-%d").date()
            except: last_date = today

            if today > last_date:
                days_passed = (today - last_date).days
                if c['status'] == 'active':
                    files = self.get_video_files(c['folder'])
                    total = len(files)
                    curr = c['last_index']
                    quota = c['daily_quota']

                    # 1. Strike for yesterday incomplete
                    if c['watched_today_count'] < quota:
                        missed = quota - c['watched_today_count']
                        start_m = curr + c['watched_today_count']
                        end_m = min(start_m + missed, total)
                        missed_files = files[start_m:end_m]
                        if missed_files:
                            c['strikes_data'].append({'id':str(uuid.uuid4()), 'date':str(last_date), 'videos':missed_files})
                            c['last_index'] += missed

                    # 2. Strike for skipped days
                    if days_passed > 1:
                        skipped = days_passed - 1
                        for _ in range(skipped):
                            start_s = c['last_index']
                            end_s = min(start_s + quota, total)
                            s_files = files[start_s:end_s]
                            if s_files:
                                c['strikes_data'].append({'id':str(uuid.uuid4()), 'date':"Skipped Day", 'videos':s_files})
                                c['last_index'] += len(s_files)

                    if len(c['strikes_data']) >= 5:
                        changed = True; continue

                c['watched_today_count'] = 0
                c['last_update_date'] = today_str
                changed = True
            
            active_courses.append(c)
        
        if changed:
            self.courses = active_courses
            self.save_data()

    def get_all_courses_with_stats(self):
        self.process_daily_schedule()
        enhanced = []
        for c in self.courses:
            folder = c.get('folder', '')
            idx = c.get('last_index', 0)
            quota = c.get('daily_quota', 3)
            watched = c.get('watched_today_count', 0)
            
            # This now gets recursive files
            files = self.get_video_files(folder)
            total = len(files)
            
            p = 0
            if total > 0: p = int((min(idx, total)/total)*100)
            dp = int((watched/quota)*100)
            if dp>100: dp=100

            cc = c.copy()
            cc['progress'] = p
            cc['total_videos'] = total
            cc['daily_percent'] = dp
            cc['quota_display'] = f"{watched} / {quota}"
            cc['is_quota_met'] = watched >= quota
            cc['strikes_count'] = len(c.get('strikes_data', []))
            if 'logo' not in cc: cc['logo'] = ""
            enhanced.append(cc)
        return enhanced

    def play_file_by_name(self, course_id, filename):
        for c in self.courses:
            if c['id'] == course_id:
                # Use join to handle subfolders correctly
                path = os.path.join(c['folder'], filename)
                if os.path.exists(path):
                    os.startfile(path)
                    return True
        return False

    def remove_strike_entry(self, course_id, strike_id, filename):
        for c in self.courses:
            if c['id'] == course_id:
                for s in c['strikes_data']:
                    if s['id'] == strike_id:
                        if filename in s['videos']:
                            s['videos'].remove(filename)
                            if not s['videos']: c['strikes_data'].remove(s)
                            self.save_data()
                            return self.get_all_courses_with_stats()
        return self.get_all_courses_with_stats()

    def add_course(self, name, platform, folder, quota, logo):
        self.courses.append({
            "id": str(uuid.uuid4()), "name": name, "platform": platform, "folder": folder,
            "daily_quota": int(quota), "logo": logo, "last_index": 0, "status": "active",
            "last_update_date": str(date.today()), "watched_today_count": 0, "strikes_data": []
        })
        self.save_data()
        return self.get_all_courses_with_stats()

    def update_course(self, cid, name, folder, quota, logo):
        for c in self.courses:
            if c['id']==cid:
                c['name']=name; c['folder']=folder; c['daily_quota']=int(quota); c['logo']=logo
                break
        self.save_data()
        return self.get_all_courses_with_stats()

    def toggle_status(self, cid):
        for c in self.courses:
            if c['id']==cid:
                c['status'] = 'paused' if c['status']=='active' else 'active'
                if c['status']=='active': c['last_update_date'] = str(date.today())
                break
        self.save_data()
        return self.get_all_courses_with_stats()

    def delete_course(self, cid):
        self.courses = [c for c in self.courses if c['id']!=cid]
        self.save_data()
        return self.get_all_courses_with_stats()

    def play_next(self, cid):
        for c in self.courses:
            if c['id']==cid:
                if c['watched_today_count'] >= c['daily_quota']: return "quota_reached"
                files = self.get_video_files(c['folder'])
                idx = c['last_index']
                if idx < len(files):
                    # Join handles subfolders
                    os.startfile(os.path.join(c['folder'], files[idx]))
                    return "success"
                return "finished"
        return "error"

    def mark_progress(self, cid):
        for c in self.courses:
            if c['id']==cid:
                if c['watched_today_count'] >= c['daily_quota']: return self.get_all_courses_with_stats()
                c['last_index']+=1; c['watched_today_count']+=1
                self.save_data()
                return self.get_all_courses_with_stats()
        return []

# =========================================================================
# 3. API BRIDGE
# =========================================================================
class Api:
    def __init__(self): self.cm = CourseManager()
    def get_courses(self): return self.cm.get_all_courses_with_stats()
    def add_new_course(self, n, p, f, q, l): return self.cm.add_course(n, p, f, q, l)
    def save_course_settings(self, i, n, f, q, l): return self.cm.update_course(i, n, f, q, l)
    def toggle_course_status(self, i): return self.cm.toggle_status(i)
    def delete_course(self, i): return self.cm.delete_course(i)
    def play_course_next(self, i): return self.cm.play_next(i)
    def mark_course_progress(self, i): return self.cm.mark_progress(i)
    def play_missed_video(self, cid, fname): return self.cm.play_file_by_name(cid, fname)
    def confirm_strike_watched(self, cid, sid, fname): return self.cm.remove_strike_entry(cid, sid, fname)

    def browse_folder(self):
        import tkinter as tk; from tkinter import filedialog; root=tk.Tk(); root.withdraw()
        p=filedialog.askdirectory(); root.destroy(); return p
    def browse_file(self):
        import tkinter as tk; from tkinter import filedialog; root=tk.Tk(); root.withdraw()
        p=filedialog.askopenfilename(filetypes=(("Img", "*.png;*.jpg;*.jpeg"),("All","*.*"))); root.destroy(); return p

# =========================================================================
# 4. FRONTEND
# =========================================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html class="light" lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Course Tracker Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
<script>
    tailwind.config = {
        darkMode: "class",
        theme: {
          extend: {
            colors: {
              primary: "#6366f1",
              "background-light": "#f8fafc",
              "background-dark": "#0f172a",
            },
            fontFamily: { display: ["Plus Jakarta Sans", "sans-serif"] },
            borderRadius: { DEFAULT: "1rem" },
          },
        },
    };
</script>
<style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; user-select: none; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
    .dropdown-menu { transform-origin: top right; transition: all 0.1s ease-out; transform: scale(0.95); opacity: 0; pointer-events: none; }
    .dropdown-menu.open { transform: scale(1); opacity: 1; pointer-events: auto; }
    dialog { border: none; border-radius: 1rem; padding: 0; background: transparent; }
    dialog::backdrop { background: rgba(0,0,0,0.5); backdrop-filter: blur(4px); }
    .logo-img { width: 100%; height: 100%; object-fit: contain; }
    @keyframes pulse-green { 0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); } 70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); } }
    .status-active { animation: pulse-green 2s infinite; background-color: #22c55e; }
    .status-paused { background-color: #ef4444; }
    @keyframes shake { 0% { transform: translate(1px, 1px) rotate(0deg); } 50% { transform: translate(-1px, 2px) rotate(-1deg); } 100% { transform: translate(1px, -2px) rotate(-1deg); } }
    .has-strikes { color: #ef4444; animation: shake 2s infinite; }
</style>
</head>
<body class="bg-background-light dark:bg-background-dark text-slate-900 dark:text-slate-100 min-h-screen transition-colors duration-300">
<nav class="sticky top-0 z-50 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800">
    <div class="max-w-[1440px] mx-auto px-6 h-16 flex items-center justify-between">
        <div class="flex items-center gap-2">
            <div class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center"><span class="material-symbols-rounded text-white text-xl">school</span></div>
            <span class="text-xl font-bold tracking-tight">CourseTrack</span>
        </div>
        <button class="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800" onclick="document.documentElement.classList.toggle('dark')"><span class="material-symbols-rounded">contrast</span></button>
    </div>
</nav>

<main class="max-w-[1440px] mx-auto px-6 py-8">
    <header class="mb-8"><h1 class="text-3xl font-bold">My Courses</h1><p class="text-slate-500 mt-1">Goal: Complete daily quota. 5 Strikes = Deleted. Click ⚡ to redeem strikes.</p></header>
    <div id="course-grid" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
        <button onclick="openAddModal()" class="group relative aspect-[4/5] flex flex-col items-center justify-center border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-primary bg-white/50 dark:bg-slate-800/50 rounded-2xl transition-all hover:bg-white dark:hover:bg-slate-800">
            <div class="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-700 group-hover:bg-primary/10 flex items-center justify-center transition-colors mb-4"><span class="material-symbols-rounded text-4xl text-slate-400 group-hover:text-primary">add</span></div>
            <span class="font-semibold text-slate-500 group-hover:text-primary">Add New Course</span>
        </button>
    </div>
</main>

<dialog id="modal-add" class="w-full max-w-lg">
    <div class="bg-white dark:bg-slate-900 w-full rounded-2xl shadow-2xl p-8 space-y-4 border border-slate-200 dark:border-slate-800">
        <h3 class="text-xl font-bold">Add Course</h3>
        <input id="add-name" type="text" placeholder="Name" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <input id="add-platform" type="text" placeholder="Platform" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <div class="flex gap-2"><input id="add-folder" type="text" placeholder="Folder" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700" readonly><button onclick="browseFolder('add-folder')" class="px-3 bg-slate-200 dark:bg-slate-700 rounded-lg">Browse</button></div>
        <div class="flex gap-2"><input id="add-logo" type="text" placeholder="Logo (Optional)" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700" readonly><button onclick="browseFile('add-logo')" class="px-3 bg-slate-200 dark:bg-slate-700 rounded-lg">Img</button></div>
        <input id="add-quota" type="number" value="3" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <div class="flex justify-end gap-2"><button onclick="document.getElementById('modal-add').close()" class="px-4 py-2">Cancel</button><button onclick="submitAddCourse()" class="px-4 py-2 bg-primary text-white rounded-lg">Save</button></div>
    </div>
</dialog>

<dialog id="modal-strikes" class="w-full max-w-lg">
    <div class="bg-white dark:bg-slate-900 w-full rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div class="px-8 py-6 border-b border-slate-100 dark:border-slate-800 flex justify-between">
            <h3 class="text-xl font-bold text-red-500">Missed Videos</h3>
            <button onclick="document.getElementById('modal-strikes').close()" class="text-slate-400"><span class="material-symbols-rounded">close</span></button>
        </div>
        <div id="strikes-content" class="p-6 max-h-[60vh] overflow-y-auto space-y-4"></div>
        <div class="px-8 py-4 bg-slate-50 dark:bg-slate-800/50 text-xs text-center text-slate-500">Watch videos completely to remove strikes.</div>
    </div>
</dialog>

<dialog id="modal-edit" class="w-full max-w-lg"><div class="bg-white dark:bg-slate-900 w-full rounded-2xl shadow-2xl p-8 space-y-4 border border-slate-200 dark:border-slate-800"><h3 class="text-xl font-bold">Edit</h3><input type="hidden" id="edit-id"><input id="edit-name" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700"><div class="flex gap-2"><input id="edit-folder" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700" readonly><button onclick="browseFolder('edit-folder')" class="px-3 bg-slate-200 rounded-lg">Browse</button></div><div class="flex gap-2"><input id="edit-logo" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700" readonly><button onclick="browseFile('edit-logo')" class="px-3 bg-slate-200 rounded-lg">Img</button></div><input id="edit-quota" type="number" class="w-full rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700"><div class="flex justify-end gap-2"><button onclick="document.getElementById('modal-edit').close()" class="px-4 py-2">Cancel</button><button onclick="submitEditCourse()" class="px-4 py-2 bg-primary text-white rounded-lg">Update</button></div></div></dialog>

<script>
    let activeDropdown = null;
    let allCourses = [];
    window.addEventListener('pywebviewready', function() { refreshCourses(); document.addEventListener('click', (e) => { if (!e.target.closest('.dropdown-trigger') && activeDropdown) { activeDropdown.classList.remove('open'); activeDropdown = null; } }); });
    function refreshCourses() { pywebview.api.get_courses().then(c => { allCourses=c; renderCourses(c); }); }

    function renderCourses(courses) {
        const grid = document.getElementById('course-grid');
        while (grid.children.length > 1) { grid.removeChild(grid.lastChild); }
        courses.forEach(c => {
            const card = document.createElement('div');
            card.className = "group bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-200 dark:border-slate-700 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all relative";
            let logoHtml = c.logo ? `<img src="${c.logo}" class="logo-img" onerror="this.style.display='none'">` : `<div class="absolute inset-0 bg-indigo-100 dark:bg-slate-700 flex items-center justify-center"><span class="material-symbols-rounded text-6xl text-slate-400">school</span></div>`;
            
            let strikeHtml = '';
            if (c.strikes_count > 0) {
                strikeHtml = `
                    <button onclick="openStrikeModal('${c.id}')" class="absolute top-4 left-14 z-20 flex items-center gap-1 bg-red-50 dark:bg-red-900/30 px-2 py-0.5 rounded-full border border-red-100 dark:border-red-900 cursor-pointer hover:bg-red-100 transition-colors">
                        <span class="material-symbols-rounded text-sm text-red-500 has-strikes">bolt</span>
                        <span class="text-xs font-bold text-red-600 dark:text-red-400">${c.strikes_count}/5</span>
                    </button>`;
            }

            let btnClass = c.is_quota_met ? "bg-green-100 text-green-700 cursor-not-allowed" : "bg-primary/10 text-primary hover:bg-primary hover:text-white";
            let btnText = c.is_quota_met ? "Done" : "Play Next";
            let btnAction = c.is_quota_met ? "" : `playNext('${c.id}')`;

            card.innerHTML = `
                <div class="aspect-square rounded-xl mb-4 relative overflow-hidden bg-slate-100 dark:bg-slate-700">
                    ${logoHtml}
                    <div class="absolute top-2 right-2 px-2 py-1 bg-white/80 dark:bg-slate-800/80 backdrop-blur rounded-md text-[10px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400 z-10">${c.platform}</div>
                </div>
                <div class="flex items-start justify-between">
                    <h3 class="font-bold text-slate-800 dark:text-slate-200 line-clamp-1 mb-1" title="${c.name}">${c.name}</h3>
                    <button onclick="toggleStatus(event, '${c.id}')" class="w-3 h-3 rounded-full ${c.status === 'active' ? 'status-active' : 'status-paused'} mt-1"></button>
                </div>
                <div class="space-y-2 mt-3">
                    <div class="flex justify-between text-xs text-slate-500"><span>Progress</span><span>${c.progress}%</span></div>
                    <div class="w-full bg-slate-100 dark:bg-slate-700 h-1.5 rounded-full overflow-hidden"><div class="bg-primary h-full rounded-full" style="width: ${c.progress}%"></div></div>
                    <div class="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700">
                         <div class="flex justify-between text-xs text-slate-500 mb-1"><span>Daily Goal</span><span>${c.quota_display}</span></div>
                        <div class="w-full bg-slate-100 dark:bg-slate-700 h-1.5 rounded-full overflow-hidden"><div class="bg-green-500 h-full rounded-full" style="width: ${c.daily_percent}%"></div></div>
                    </div>
                    <div class="flex justify-between items-center mt-3">
                        <span class="text-xs text-slate-400">${c.last_index} / ${c.total_videos}</span>
                        <button onclick="${btnAction}" class="text-xs px-3 py-1.5 rounded-lg transition-colors ${btnClass}">${btnText}</button>
                    </div>
                </div>
                ${strikeHtml}
                <div class="absolute top-4 left-4 z-20">
                    <button class="dropdown-trigger p-1 bg-white/50 hover:bg-white rounded-full" onclick="toggleDropdown(event, '${c.id}')"><span class="material-symbols-rounded text-slate-500">more_vert</span></button>
                    <div id="dd-${c.id}" class="dropdown-menu absolute top-full left-0 mt-2 w-32 bg-white dark:bg-slate-900 rounded-lg shadow-xl border border-slate-100 dark:border-slate-700 z-10 flex flex-col p-1">
                        <button onclick="openEditModal('${c.id}', '${c.name.replace(/'/g, "\\'")}', '${c.folder.replace(/\\/g, '\\\\')}', ${c.daily_quota}, '${c.logo.replace(/\\/g, '\\\\')}')" class="text-left px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md">Edit</button>
                        <button onclick="deleteCourse('${c.id}')" class="text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50 rounded-md">Delete</button>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function openStrikeModal(id) {
        const course = allCourses.find(c => c.id === id);
        const container = document.getElementById('strikes-content');
        container.innerHTML = "";
        if(!course || !course.strikes_data || course.strikes_data.length === 0) { container.innerHTML = "<p>No missed videos!</p>"; return; }
        course.strikes_data.forEach(strike => {
            let videosHtml = "";
            strike.videos.forEach(vid => {
                // Shorten file name slightly for display
                let dispName = vid.split('\\').pop(); 
                videosHtml += `
                    <div class="flex items-center justify-between py-2 border-b border-red-100/50 last:border-0">
                        <span class="text-sm font-medium text-slate-700 dark:text-slate-300 truncate w-2/3" title="${vid}">${dispName}</span>
                        <button onclick="playStrikeVideo('${id}', '${strike.id}', '${vid.replace(/'/g, "\\'")}')" class="text-xs bg-red-100 text-red-600 px-3 py-1 rounded hover:bg-red-200">Play</button>
                    </div>`;
            });
            const div = document.createElement('div');
            div.className = "border border-red-100 dark:border-red-900 bg-red-50 dark:bg-red-900/10 rounded-xl p-4";
            div.innerHTML = `<div class="flex items-center gap-2 mb-2 text-red-600 font-bold"><span class="material-symbols-rounded">calendar_month</span>${strike.date}</div><div class="bg-white dark:bg-slate-900 rounded-lg px-3">${videosHtml}</div>`;
            container.appendChild(div);
        });
        document.getElementById('modal-strikes').showModal();
    }

    function playStrikeVideo(courseId, strikeId, filename) {
        pywebview.api.play_missed_video(courseId, filename).then(success => {
            if(success) {
                if(confirm("Video launched. Did you finish watching " + filename + "?\n\nClick OK to remove the strike.")) {
                    pywebview.api.confirm_strike_watched(courseId, strikeId, filename).then(c => {
                        allCourses = c; renderCourses(c);
                        const updated = c.find(x => x.id === courseId);
                        if(updated.strikes_count === 0) document.getElementById('modal-strikes').close();
                        else openStrikeModal(courseId);
                    });
                }
            } else alert("File not found!");
        });
    }

    function toggleStatus(e, id) { e.stopPropagation(); pywebview.api.toggle_course_status(id).then(c => {allCourses=c; renderCourses(c)}); }
    function playNext(id) { pywebview.api.play_course_next(id).then(r => { if(r==="quota_reached") alert("Quota reached!"); else if(r==="success") { if(confirm("Mark as watched?")) pywebview.api.mark_course_progress(id).then(c=>{allCourses=c;renderCourses(c)}); } }); }
    function deleteCourse(id) { if(confirm("Delete?")) pywebview.api.delete_course(id).then(c=>{allCourses=c;renderCourses(c)}); }
    function toggleDropdown(e, id) { e.stopPropagation(); const dd=document.getElementById('dd-'+id); if(activeDropdown && activeDropdown!==dd) activeDropdown.classList.remove('open'); dd.classList.toggle('open'); activeDropdown=dd.classList.contains('open')?dd:null; }
    function browseFolder(id) { pywebview.api.browse_folder().then(p => {if(p) document.getElementById(id).value=p}); }
    function browseFile(id) { pywebview.api.browse_file().then(p => {if(p) document.getElementById(id).value=p}); }
    function openAddModal() { document.getElementById('modal-add').showModal(); }
    function submitAddCourse() { pywebview.api.add_new_course(document.getElementById('add-name').value, document.getElementById('add-platform').value, document.getElementById('add-folder').value, document.getElementById('add-quota').value, document.getElementById('add-logo').value).then(c=>{allCourses=c;renderCourses(c);document.getElementById('modal-add').close();}); }
    function openEditModal(id,name,folder,quota,logo) { document.getElementById('edit-id').value=id;document.getElementById('edit-name').value=name;document.getElementById('edit-folder').value=folder;document.getElementById('edit-quota').value=quota;document.getElementById('edit-logo').value=logo;document.getElementById('modal-edit').showModal(); if(activeDropdown) activeDropdown.classList.remove('open'); }
    function submitEditCourse() { pywebview.api.save_course_settings(document.getElementById('edit-id').value,document.getElementById('edit-name').value,document.getElementById('edit-folder').value,document.getElementById('edit-quota').value,document.getElementById('edit-logo').value).then(c=>{allCourses=c;renderCourses(c);document.getElementById('modal-edit').close();}); }
</script>
</body>
</html>
"""

if __name__ == '__main__':
    api = Api()
    window = webview.create_window('CourseTrack', html=HTML_TEMPLATE, js_api=api, width=1200, height=800, resizable=True)
    webview.start(debug=False)