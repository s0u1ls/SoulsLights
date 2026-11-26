"""Builds SoulsLights.app and SoulsLights-macOS.dmg cleanly on macOS."""
import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)


def main():
    if sys.platform != "darwin":
        print("Error: SoulsLights.app must be built on macOS (darwin).")
        print("Tip: Copy this folder to a Mac and run: bash macos/build_mac.sh")
        print("Or push to GitHub to run .github/workflows/build-mac.yml automatically.")
        sys.exit(1)

    # Ensure assets/SoulsLights.icns exists
    icns_path = os.path.join(BASE_DIR, "assets", "SoulsLights.icns")
    if not os.path.exists(icns_path):
        subprocess.run([sys.executable, os.path.join("macos", "make_icons.py")], check=True)

    dist_dir = os.path.join(BASE_DIR, "dist")
    build_dir = os.path.join(BASE_DIR, "build")
    shutil.rmtree(dist_dir, ignore_errors=True)
    shutil.rmtree(build_dir, ignore_errors=True)

    print("Building SoulsLights.app with PyInstaller...")
    res = subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "SoulsLights_mac.spec",
    ])
    if res.returncode != 0:
        sys.exit(res.returncode)

    app_path = os.path.join(dist_dir, "SoulsLights.app")
    if not os.path.exists(app_path):
        print("Error: dist/SoulsLights.app was not created.")
        sys.exit(1)

    # Ad-hoc codesign so macOS Gatekeeper / local launch runs smoothly
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app_path], check=False)

    dmg_staging = os.path.join(dist_dir, "_dmg_stage")
    os.makedirs(dmg_staging, exist_ok=True)
    staged_app = os.path.join(dmg_staging, "SoulsLights.app")
    subprocess.run(["ditto", app_path, staged_app], check=True)
    apps_link = os.path.join(dmg_staging, "Applications")
    if not os.path.exists(apps_link):
        os.symlink("/Applications", apps_link)

    dmg_out = os.path.join(dist_dir, "SoulsLights-macOS.dmg")
    if os.path.exists(dmg_out):
        os.remove(dmg_out)
    subprocess.run([
        "hdiutil", "create",
        "-volname", "SoulsLights",
        "-srcfolder", dmg_staging,
        "-ov", "-format", "UDZO",
        dmg_out,
    ], check=True)
    shutil.rmtree(dmg_staging, ignore_errors=True)

    print("\nMAC BUILD SUCCESSFUL!")
    print(f"App Bundle: {app_path}")
    print(f"Installer DMG: {dmg_out}")


if __name__ == "__main__":
    main()
