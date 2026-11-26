<div align="center">

# ✨ SoulsLights

### Ultra-Smooth Synced Desktop Lyrics & Ambient Screen Lighting

[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com)
[![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon%20%7C%20Intel-000000?style=for-the-badge&logo=apple&logoColor=white)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.badge?style=for-the-badge)](LICENSE)
[![Release](https://img.shields.io/badge/Download-Latest%20Releases-blueviolet?style=for-the-badge&logo=github&logoColor=white)](https://github.com/YOUR_USERNAME/SoulsLights/releases/latest)

<br/>

**SoulsLights** turns your desktop into an immersive audiovisual stage. Featuring **liquid-glass studio controls**, **real-time system media synchronization**, and **10 kinetic lyric motion styles** with seamless audio-reactive ambient lighting.

<br/>

[⬇️ Download for Windows (.exe)](https://github.com/YOUR_USERNAME/SoulsLights/releases/latest) • [🍎 Download for macOS (.dmg / .app)](#-macos-installation) • [✨ Features](#-features) • [🎨 Lyrics Styles](#-lyrics-styles) • [🛠️ Build from Source](#️-build-from-source)

</div>

---

## 🌟 Highlights

- **🪟 Liquid Glass Studio UI:** Modern dark frosted acrylic styling with live kinetic card hover previews, responsive drawer controls, and quick navigation pills.
- **🎵 Zero-Setup Universal Media Sync:** Instantly syncs with Spotify, Apple Music, YouTube Music, Chrome, Edge, Safari, and native system media listeners.
- **💫 10 Dynamic Lyrics Motion Styles:** From kinetic typography walls to glowing starfield constellations and live-typing terminals.
- **🌈 Dual-Blob Ambient Lighting:** Cinematic, audio-reactive soft ambient backdrop synced in real-time to your current album cover palette.
- **🖱️ Transparent Click-Through Overlays:** Non-intrusive floating desktop lyrics you can lock, unlock, click through, or pin on top while gaming, working, or browsing.
- **⚡ Standalone Portability:** Ready-to-use standalone builds for both **Windows** and **macOS**.

---

## 🎨 Lyrics Styles

SoulsLights includes 10 motion themes:

| Style | Category | Description |
| :--- | :--- | :--- |
| **Ship** | Kinetic type | Words land one by one on a wall that drifts in 3D with dynamic highlight blocks. |
| **Fisheye** | Kinetic type | Spherical barrel-warped typography with smooth beat-bouncing kinetic scale. |
| **Visual** | Kinetic type | Centered wave typography paired with contextual expressive icons. |
| **Fisheye Visual**| Kinetic type | Chromatic fisheye dome paired with animated floating icon accents. |
| **Codestyle** | Motion scenes | Clean monospace live-typing syntax with a blinking terminal cursor. |
| **Codestyle Visual**| Motion scenes| Terminal-inspired syntax accompanied by inline glyph and emoji animations. |
| **Branches** | Motion scenes | Organic harmonic wave nodes that bloom and branch in musical sequence. |
| **Web** | Motion scenes | Words suspended like dew across a kinetic spinning spiderweb. |
| **Constellation**| Motion scenes | Non-overlapping starfield lyrics linked by glowing shooting-star trails. |
| **Native Design**| Phone screens | Live animated iOS / iMessage-style chat bubbles with spring physics. |

---

## 🚀 Getting Started

### 🪟 Windows Installation
1. Download **`SoulsLights.exe`** from the [Releases](https://github.com/YOUR_USERNAME/SoulsLights/releases/latest) page.
2. Double-click to launch (no installation or Python required).
3. Play music on Spotify, Apple Music, YouTube Music, or any supported player.

### 🍎 macOS Installation
1. Download **`SoulsLights-macOS.dmg`** (or `SoulsLights.app.zip`) from [Releases](https://github.com/YOUR_USERNAME/SoulsLights/releases/latest).
2. Drag **SoulsLights** into your **Applications** folder.
3. Open `SoulsLights` from Applications or Spotlight.

> [!NOTE]
> **macOS Permissions:**
> - When first running on macOS, allow **Accessibility** permissions under *System Settings → Privacy & Security → Accessibility* if prompted, enabling click-through window detection.
> - For Apple Music / Spotify track sync on macOS, grant **Automation** permission when requested.
> - If you see an *"unidentified developer"* prompt on first launch, right-click `SoulsLights.app` and choose **Open**.

---

## 🛠️ Build from Source

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/SoulsLights.git
cd SoulsLights
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run in development mode
```bash
python main.py
```

### 4. Build standalone binaries

#### On Windows:
```bash
python build_exe.py
```
*(Outputs `dist/SoulsLights.exe`)*

#### On macOS:
```bash
pyinstaller --name "SoulsLights" --windowed --icon "app_icon.icns" main.py
```
*(Outputs `dist/SoulsLights.app`)*

---

## ⌨️ Controls & Customization

Inside the SoulsLights Studio UI:
- **`Size`:** Adjust lyrics font size, overlay scale, and margin spacing.
- **`Font`:** Choose system typography (Segoe UI, Georgia, San Francisco, Consolas, etc.).
- **`Screen`:** Select target monitor for multi-display setups.
- **`Aesthetics`:** Tweak blur radius, ambient glow intensity, and background opacity.
- **`↻ Force Refresh`:** Instantly re-fetch and re-align lyrics timestamps.
- **`🔒 Unlock / Lock`:** Toggle click-through mode to pass mouse events directly to windows underneath.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

<div align="center">
<sub>Crafted with precision for audio and desktop enthusiasts.</sub>
</div>
