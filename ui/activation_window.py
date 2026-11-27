import os
import customtkinter as ctk

from core.platform_utils import IS_WIN, get_resource_path


class ActivationWindow(ctk.CTk):
    """Sleek dark Liquid-Glass token activation prompt shown before launching SoulsLights."""

    def __init__(self, license_mgr):
        super().__init__()
        self.license_mgr = license_mgr
        self.activated = False
        self._verified_token = None

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

        self.title_lbl = ctk.CTkLabel(
            card, text="Activate SoulsLights",
            font=("Segoe UI", 22, "bold"), text_color="#F8FAFC"
        )
        self.title_lbl.pack(pady=(26, 6))

        self.sub_lbl = ctk.CTkLabel(
            card, text="Enter your 10-character license token to unlock SoulsLights.",
            font=("Segoe UI", 12), text_color="#94A3B8"
        )
        self.sub_lbl.pack(pady=(0, 18))

        self.entry = ctk.CTkEntry(
            card, width=320, height=42, corner_radius=12,
            placeholder_text="Enter activation token...",
            font=("Consolas", 15, "bold"),
            fg_color="#0C0A15", border_color="#6D28D9", text_color="#F8FAFC",
            justify="center",
        )
        self.entry.pack(pady=(0, 10))
        self.entry.bind("<Return>", lambda _e: self._on_submit())
        self.after(120, self.entry.focus_set)

        self.status_lbl = ctk.CTkLabel(
            card, text="", font=("Segoe UI", 12), text_color="#F87171"
        )
        self.status_lbl.pack(pady=(0, 12))

        self.btn = ctk.CTkButton(
            card, text="Verify Token", width=220, height=40, corner_radius=20,
            fg_color="#7C3AED", hover_color="#9333EA",
            font=("Segoe UI", 13, "bold"), command=self._on_submit
        )
        self.btn.pack()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_submit(self):
        if self._verified_token is None:
            tok = self.entry.get().strip()
            self.btn.configure(state="disabled", text="Verifying...")
            self.update_idletasks()
            ok, msg = self.license_mgr.check_token(tok)
            if ok:
                self._verified_token = tok
                self.title_lbl.configure(text="What's Your Name?")
                self.sub_lbl.configure(text="Enter your name to complete activation.")
                self.entry.delete(0, "end")
                self.entry.configure(placeholder_text="Enter your name...", font=("Segoe UI", 15, "bold"))
                self.status_lbl.configure(text="Token verified!", text_color="#34D399")
                self.btn.configure(state="normal", text="Finish & Launch")
                self.entry.focus_set()
            else:
                self.btn.configure(state="normal", text="Verify Token")
                self.status_lbl.configure(text=msg, text_color="#F87171")
            return

        name = self.entry.get().strip()
        if len(name) < 2:
            self.status_lbl.configure(text="Please enter your name (at least 2 characters).", text_color="#F87171")
            return
        self.btn.configure(state="disabled", text="Activating...")
        self.update_idletasks()
        ok, msg = self.license_mgr.verify_and_activate(self._verified_token, user_name=name)
        if ok:
            self.activated = True
            self.status_lbl.configure(text=msg, text_color="#34D399")
            self.after(350, self.destroy)
        else:
            self._verified_token = None
            self.title_lbl.configure(text="Activate SoulsLights")
            self.sub_lbl.configure(text="Enter your 10-character license token to unlock SoulsLights.")
            self.entry.delete(0, "end")
            self.entry.configure(placeholder_text="Enter activation token...", font=("Consolas", 15, "bold"))
            self.btn.configure(state="normal", text="Verify Token")
            self.status_lbl.configure(text=msg, text_color="#F87171")

    def _on_close(self):
        self.activated = False
        self.destroy()
