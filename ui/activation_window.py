import os
import customtkinter as ctk

from core.platform_utils import IS_WIN, get_resource_path


class ActivationWindow(ctk.CTk):
    """Sleek dark Liquid-Glass token activation prompt shown before launching SoulsLights."""

    def __init__(self, license_mgr):
        super().__init__()
        self.license_mgr = license_mgr
        self.activated = False

        ctk.set_appearance_mode("dark")
        self.title("SoulsLights — Activation")
        self.geometry("460x320")
        self.resizable(False, False)
        self.configure(fg_color="#0D0B16")

        if IS_WIN:
            ico = get_resource_path("app_icon.ico")
            if os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except Exception:
                    pass

        # Center on primary screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"460x320+{(sw - 460) // 2}+{(sh - 320) // 2}")

        card = ctk.CTkFrame(self, fg_color="#161326", corner_radius=20, border_width=1, border_color="#3B2D5C")
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card, text="Activate SoulsLights",
            font=("Segoe UI", 22, "bold"), text_color="#F8FAFC"
        ).pack(pady=(26, 6))

        ctk.CTkLabel(
            card, text="Enter your 10-character license token to unlock SoulsLights.",
            font=("Segoe UI", 12), text_color="#94A3B8"
        ).pack(pady=(0, 18))

        self.entry = ctk.CTkEntry(
            card, width=320, height=42, corner_radius=12,
            placeholder_text="Enter activation token...",
            font=("Consolas", 15, "bold"),
            fg_color="#0C0A15", border_color="#6D28D9", text_color="#F8FAFC",
            justify="center",
        )
        self.entry.pack(pady=(0, 10))
        self.entry.bind("<Return>", lambda _e: self._on_activate())
        self.after(120, self.entry.focus_set)

        self.status_lbl = ctk.CTkLabel(
            card, text="", font=("Segoe UI", 12), text_color="#F87171"
        )
        self.status_lbl.pack(pady=(0, 12))

        self.btn = ctk.CTkButton(
            card, text="Verify & Activate", width=220, height=40, corner_radius=20,
            fg_color="#7C3AED", hover_color="#9333EA",
            font=("Segoe UI", 13, "bold"), command=self._on_activate
        )
        self.btn.pack()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_activate(self):
        tok = self.entry.get().strip()
        self.btn.configure(state="disabled", text="Verifying...")
        self.update_idletasks()
        ok, msg = self.license_mgr.verify_and_activate(tok)
        if ok:
            self.activated = True
            self.status_lbl.configure(text=msg, text_color="#34D399")
            self.after(350, self.destroy)
        else:
            self.btn.configure(state="normal", text="Verify & Activate")
            self.status_lbl.configure(text=msg, text_color="#F87171")

    def _on_close(self):
        self.activated = False
        self.destroy()
