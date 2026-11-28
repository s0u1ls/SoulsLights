import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

def _read_app_version() -> str:
    ver_p = os.path.join(BASE_DIR, "core", "version.py")
    if os.path.exists(ver_p):
        with open(ver_p, "r", encoding="utf-8") as f:
            m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', f.read())
            if m:
                return m.group(1).strip()
    return "2.3.0"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1048576)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _write_win_version_file(ver_str: str, out_path: str):
    nums = [int(x) for x in re.findall(r"\d+", ver_str)[:4]]
    while len(nums) < 4:
        nums.append(0)
    fvers = ", ".join(str(n) for n in nums)
    dot_ver = ".".join(str(n) for n in nums)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({fvers}),
    prodvers=({fvers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'SoulsLights'),
            StringStruct('FileDescription', 'SoulsLights - Spatial Edge Light & Synced Lyrics Studio'),
            StringStruct('FileVersion', '{dot_ver}'),
            StringStruct('InternalName', 'SoulsLights'),
            StringStruct('LegalCopyright', 'Copyright (c) 2026 SoulsLights (MIT License)'),
            StringStruct('OriginalFilename', 'SoulsLights.exe'),
            StringStruct('ProductName', 'SoulsLights'),
            StringStruct('ProductVersion', '{dot_ver}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


def _find_iscc() -> str:
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found and os.path.exists(found):
        return found
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def _write_inno_iss(ver_str: str, iss_path: str):
    icon_p = os.path.join(BASE_DIR, "app_icon.ico")
    src_glob = os.path.join(BASE_DIR, "dist", "SoulsLights", "*")
    out_dir = os.path.join(BASE_DIR, "dist")
    nums = [int(x) for x in re.findall(r"\d+", ver_str)[:4]]
    while len(nums) < 4:
        nums.append(0)
    dot4 = ".".join(str(n) for n in nums)
    iss = f"""; SoulsLights Windows Installer (Inno Setup 6)
[Setup]
AppId={{{{D9C2E3F4-7B8A-4E1C-9D2B-4A6F1C8E0922}}}}
AppName=SoulsLights
AppVersion={ver_str}
AppVerName=SoulsLights {ver_str}
AppPublisher=SoulsLights
AppPublisherURL=https://github.com/s0u1ls/SoulsLights
DefaultDirName={{localappdata}}\\Programs\\SoulsLights
DefaultGroupName=SoulsLights
PrivilegesRequired=lowest
AllowNoIcons=yes
OutputDir={out_dir}
OutputBaseFilename=SoulsLights-Setup
SetupIconFile={icon_p}
UninstallDisplayIcon={{app}}\\SoulsLights.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={dot4}
VersionInfoCompany=SoulsLights
VersionInfoDescription=SoulsLights Windows Installer
VersionInfoProductName=SoulsLights
VersionInfoProductVersion={dot4}
VersionInfoCopyright=Copyright (c) 2026 SoulsLights

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"

[Files]
Source: "{src_glob}"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\SoulsLights"; Filename: "{{app}}\\SoulsLights.exe"
Name: "{{group}}\\Uninstall SoulsLights"; Filename: "{{uninstallexe}}"
Name: "{{userdesktop}}\\SoulsLights"; Filename: "{{app}}\\SoulsLights.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\SoulsLights.exe"; Description: "{{cm:LaunchProgram,SoulsLights}}"; Flags: nowait postinstall skipifsilent
"""
    os.makedirs(os.path.dirname(iss_path), exist_ok=True)
    with open(iss_path, "w", encoding="utf-8") as f:
        f.write(iss)


def main():
    app_ver = _read_app_version()
    print("Terminating any running SoulsLights / legacy instances before build...")
    for proc in ("SoulsLights.exe", "SoulsLights-Setup.exe", "LumnVerciHub.exe"):
        subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)
    time.sleep(0.5)

    dist_dir = os.path.join(BASE_DIR, "dist")
    build_dir = os.path.join(BASE_DIR, "build")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir, ignore_errors=True)
    os.makedirs(build_dir, exist_ok=True)

    ver_file = os.path.join(build_dir, "version_info.txt")
    _write_win_version_file(app_ver, ver_file)

    print(f"Building SoulsLights v{app_ver} (--onedir + PE Version Metadata, avoiding %TEMP% unpacking)...")
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconsole",
        "--onedir",
        "--name=SoulsLights",
        "--icon=app_icon.ico",
        f"--version-file={ver_file}",
        "--add-data=app_icon.ico;.",
        "--add-data=assets/app_icon.png;assets",
        "--add-data=mobile;mobile",
        "--add-data=core/_token_hashes.json;core",
        "--collect-all=customtkinter",
        "--collect-all=pystray",
        "--collect-all=winrt",
        "--collect-all=certifi",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=tkinter.simpledialog",
        "--noconfirm",
        "--clean",
        "main.py",
    ]

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"\nBuild failed with code {res.returncode}")
        sys.exit(res.returncode)

    onedir_out = os.path.join(dist_dir, "SoulsLights")
    dist_exe = os.path.join(onedir_out, "SoulsLights.exe")
    if not os.path.exists(dist_exe):
        print("Error: dist/SoulsLights/SoulsLights.exe was not created.")
        sys.exit(1)

    portable_zip = shutil.make_archive(
        os.path.join(dist_dir, "SoulsLights-Windows-Portable"),
        "zip",
        dist_dir,
        "SoulsLights",
    )
    print(f"Portable ZIP: {portable_zip}")

    setup_exe = ""
    iscc = _find_iscc()
    if iscc:
        iss_path = os.path.join(build_dir, "SoulsLights.iss")
        _write_inno_iss(app_ver, iss_path)
        print(f"Compiling Inno Setup installer with: {iscc}")
        ir = subprocess.run([iscc, iss_path])
        if ir.returncode != 0:
            print(f"Inno Setup compilation failed with code {ir.returncode}")
            sys.exit(ir.returncode)
        cand_setup = os.path.join(dist_dir, "SoulsLights-Setup.exe")
        if os.path.exists(cand_setup):
            setup_exe = cand_setup
    else:
        print("WARNING: Inno Setup (ISCC.exe) not found; built --onedir + portable ZIP only.")

    print("\nBUILD SUCCESSFUL!")
    print(f"  App EXE   : {dist_exe} (SHA-256: {_sha256_file(dist_exe)})")
    print(f"  Portable  : {portable_zip} (SHA-256: {_sha256_file(portable_zip)})")
    if setup_exe:
        print(f"  Setup EXE : {setup_exe} (SHA-256: {_sha256_file(setup_exe)})")
    print("\nDefender False-Positive Whitelist Submission (if flagged):")
    print("  https://www.microsoft.com/en-us/wdsi/filesubmission")

    # Deploy locally: install clean --onedir build to %LOCALAPPDATA%\Programs\SoulsLights & put Setup in Downloads
    local_app_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "SoulsLights")
    if os.environ.get("LOCALAPPDATA"):
        try:
            if os.path.exists(local_app_dir):
                shutil.rmtree(local_app_dir, ignore_errors=True)
            shutil.copytree(onedir_out, local_app_dir)
            print(f"Local install updated: {local_app_dir}")
        except Exception as e:
            print(f"Local install note: {e}")

    downloads_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
    if os.path.exists(downloads_dir):
        if setup_exe:
            target_setup = os.path.join(downloads_dir, "SoulsLights-Setup.exe")
            shutil.copy2(setup_exe, target_setup)
            print(f"Setup deployed to: {target_setup}")

        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop")
        if not os.path.exists(desktop):
            desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        lnk_target = os.path.join(local_app_dir, "SoulsLights.exe") if os.path.exists(os.path.join(local_app_dir, "SoulsLights.exe")) else dist_exe
        if os.path.exists(desktop):
            lnk_path = os.path.join(desktop, "SoulsLights.lnk")
            ps_script = (
                "$WshShell = New-Object -comObject WScript.Shell; "
                f"$Shortcut = $WshShell.CreateShortcut('{lnk_path}'); "
                f"$Shortcut.TargetPath = '{lnk_target}'; "
                f"$Shortcut.WorkingDirectory = '{os.path.dirname(lnk_target)}'; "
                "$Shortcut.Description = 'SoulsLights — Spatial Light & Lyrics Studio'; "
                "$Shortcut.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
            print(f"Desktop shortcut updated: {lnk_path}")


if __name__ == "__main__":
    main()
