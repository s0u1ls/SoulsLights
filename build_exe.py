import os
import subprocess
import sys
import shutil
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

print("Terminating any running SoulsLights / legacy instances before build...")
for proc in ("SoulsLights.exe", "LumnVerciHub.exe"):
    subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)
time.sleep(0.5)

dist_dir = os.path.join(BASE_DIR, "dist")
if os.path.exists(dist_dir):
    shutil.rmtree(dist_dir, ignore_errors=True)

print("Building SoulsLights Standalone Single-File Executable with PyInstaller...")

cmd = [
    sys.executable,
    "-m", "PyInstaller",
    "--noconsole",
    "--onefile",
    "--name=SoulsLights",
    "--icon=app_icon.ico",
    "--add-data=app_icon.ico;.",
    "--collect-all=customtkinter",
    "--collect-all=pystray",
    "--collect-all=winrt",
    "--collect-all=certifi",
    "--hidden-import=PIL._tkinter_finder",
    "--noconfirm",
    "--clean",
    "main.py",
]

res = subprocess.run(cmd)
if res.returncode != 0:
    print(f"\nBuild failed with code {res.returncode}")
    sys.exit(res.returncode)

print("\nBUILD SUCCESSFUL!")
dist_exe = os.path.join(BASE_DIR, "dist", "SoulsLights.exe")
print(f"Standalone executable: {dist_exe}")

downloads_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
if os.path.exists(downloads_dir):
    for stale in ("LumnVerciHub.exe", "LumnVerciHub"):
        p_stale = os.path.join(downloads_dir, stale)
        if os.path.isdir(p_stale):
            shutil.rmtree(p_stale, ignore_errors=True)
        elif os.path.isfile(p_stale):
            os.remove(p_stale)

    target_exe = os.path.join(downloads_dir, "SoulsLights.exe")
    shutil.copy2(dist_exe, target_exe)
    print(f"Deployed to: {target_exe}")

    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop")
    if not os.path.exists(desktop):
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if os.path.exists(desktop):
        old_lnk = os.path.join(desktop, "Lumn & Verci Hub.lnk")
        if os.path.exists(old_lnk):
            os.remove(old_lnk)
        lnk_path = os.path.join(desktop, "SoulsLights.lnk")
        ps_script = (
            "$WshShell = New-Object -comObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{lnk_path}'); "
            f"$Shortcut.TargetPath = '{target_exe}'; "
            f"$Shortcut.WorkingDirectory = '{downloads_dir}'; "
            "$Shortcut.Description = 'SoulsLights — Spatial Light & Lyrics Studio'; "
            "$Shortcut.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
        print(f"Desktop shortcut updated: {lnk_path}")
