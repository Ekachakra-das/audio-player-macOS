import os
import sys
import webview
import json
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
import socket
import urllib.parse

# Configuration
APP_NAME = "AudioPlayerHaribol"
# Path Resolution
# Script is at: AudioPlayer.app/Contents/Resources/app.py
SCRIPT_PATH = os.path.abspath(__file__)
RESOURCES_DIR = os.path.dirname(SCRIPT_PATH)
# Store settings inside the app bundle to make instances independent
SETTINGS_DIR = os.path.join(RESOURCES_DIR, "../Settings")
os.makedirs(SETTINGS_DIR, exist_ok=True)

def has_audio_files(directory):
    extensions = ('.mp3', '.m4a', '.wav', '.ogg', '.flac')
    try:
        for root, dirs, files in os.walk(directory):
            # Don't go into hidden folders
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.lower().endswith(extensions) and not file.startswith('.'):
                    return True
    except:
        pass
    return False

def choose_audio_folder(default_dir):
    import subprocess
    escaped = default_dir.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'set defaultFolder to POSIX file "{escaped}"\n'
        'set selectedFolder to choose folder with prompt "Select your Audiobooks folder" default location defaultFolder\n'
        "POSIX path of selectedFolder"
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()

def save_library_dir(directory):
    settings_file = os.path.join(SETTINGS_DIR, "settings.json")
    settings = {}
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
        except:
            pass
    settings["library_dir"] = directory
    try:
        with open(settings_file, "w") as f:
            json.dump(settings, f)
    except:
        pass

def resolve_base_dir():
    # 1. Default directory next to the .app bundle
    default_dir = os.path.abspath(os.path.join(RESOURCES_DIR, "../../.."))
    is_translocated = "AppTranslocation" in default_dir or "private/var/folders" in default_dir
    
    # 2. Load from settings.json
    settings_file = os.path.join(SETTINGS_DIR, "settings.json")
    saved_dir = None
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
                saved_dir = settings.get("library_dir")
        except:
            pass
            
    # If saved dir is valid and contains audio files, use it
    if saved_dir and os.path.exists(saved_dir) and not ("AppTranslocation" in saved_dir or "private/var/folders" in saved_dir) and has_audio_files(saved_dir):
        return saved_dir
        
    # If default directory is not translocated and contains audio files, use it
    if not is_translocated and os.path.exists(default_dir) and has_audio_files(default_dir):
        save_library_dir(default_dir)
        return default_dir
        
    # Otherwise, ask the user to select the folder
    selected_dir = choose_audio_folder(default_dir if os.path.exists(default_dir) else os.path.expanduser("~/Documents"))
    if selected_dir and os.path.exists(selected_dir):
        save_library_dir(selected_dir)
        return selected_dir
        
    return default_dir

BASE_DIR = resolve_base_dir()

class AudioServer(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Serve files from BASE_DIR
        parsed_path = urllib.parse.urlparse(path).path
        decoded_path = urllib.parse.unquote(parsed_path)
        # Ensure path is relative (strip leading slashes)
        rel_path = decoded_path.lstrip('/')
        # Join with BASE_DIR
        return os.path.join(BASE_DIR, rel_path)
    def log_message(self, format, *args):
        pass

def start_server():
    server = HTTPServer(('localhost', 0), AudioServer)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port

class API:
    def __init__(self, port):
        self.port = port
        self.settings_file = os.path.join(SETTINGS_DIR, "settings.json")
        self._settings_lock = threading.Lock()

    def _load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    return json.load(f)
            except: return {}
        return {}

    def _save_settings(self, settings):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
        except: pass

    def get_tracks(self):
        tracks = []
        extensions = ('.mp3', '.m4a', '.wav', '.ogg', '.flac')
        try:
            print(f"Scanning BASE_DIR: {BASE_DIR}")
            for root, dirs, files in os.walk(BASE_DIR):
                # Don't go into hidden folders
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                # But allow scanning alongside .app bundles
                
                for file in files:
                    if file.lower().endswith(extensions) and not file.startswith('.'):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, BASE_DIR)
                        tracks.append({
                            'name': os.path.splitext(file)[0],
                            'path': rel_path,
                            'folder': os.path.dirname(rel_path) or '',
                            'url': f'http://localhost:{self.port}/{urllib.parse.quote(rel_path)}'
                        })
        except Exception as e:
            print(f"Scan error: {e}")
        
        # Sort by folder and then by name
        tracks.sort(key=lambda x: (x['folder'].lower(), x['name'].lower()))
        return tracks

    def save_position(self, data):
        with self._settings_lock:
            settings = self._load_settings()
            settings[BASE_DIR] = data
            self._save_settings(settings)
        return True

    def load_position(self):
        with self._settings_lock:
            settings = self._load_settings()
            return settings.get(BASE_DIR, None)

    def save_collapsed_folders(self, folders):
        with self._settings_lock:
            settings = self._load_settings()
            settings[f"{BASE_DIR}__collapsed"] = folders
            self._save_settings(settings)
        return True

    def load_collapsed_folders(self):
        with self._settings_lock:
            settings = self._load_settings()
            return settings.get(f"{BASE_DIR}__collapsed", [])

    def show_in_finder(self, rel_path):
        full_path = os.path.join(BASE_DIR, rel_path)
        if os.path.exists(full_path):
            import subprocess
            subprocess.run(["open", "-R", full_path])
        return True

    def quit(self):
        sys.exit(0)

    def change_library_dir(self):
        global BASE_DIR
        default_dir = BASE_DIR
        selected_dir = choose_audio_folder(default_dir if os.path.exists(default_dir) else os.path.expanduser("~/Documents"))
        if selected_dir and os.path.exists(selected_dir):
            save_library_dir(selected_dir)
            BASE_DIR = selected_dir
            return True
        return False

def main():
    port = start_server()
    api = API(port)
    html_path = os.path.join(RESOURCES_DIR, "index.html")
    
    window = webview.create_window(
        f'Haribol Player [{BASE_DIR}]',
        url=f'file://{html_path}',
        js_api=api,
        width=1100,
        height=750,
        background_color='#f2f2f2'
    )
    
    webview.start(debug=False)

if __name__ == '__main__':
    main()
