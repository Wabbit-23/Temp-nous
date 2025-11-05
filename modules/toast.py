"""Lightweight toast notifications for Tkinter."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List


class ToastManager:
    def __init__(self, root: tk.Tk, theme_getter: Callable[[], dict]) -> None:
        self.root = root
        self.theme_getter = theme_getter
        self._toasts: List[tk.Toplevel] = []

    def show(self, message: str, duration: int = 3000) -> None:
        theme = self.theme_getter()
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=theme["card_bg"])

        frame = ttk.Frame(toast, style="Card.TFrame", padding=(16, 10))
        frame.pack(fill="both", expand=True)
        label = ttk.Label(frame, text=message, style="Muted.TLabel", anchor="center", justify="center")
        label.pack()

        toast.update_idletasks()

        width = toast.winfo_width()
        height = toast.winfo_height()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()

        x = root_x + root_w - width - 32
        y = root_y + root_h - height - 32

        toast.geometry(f"+{x}+{y}")
        toast.attributes("-alpha", 0.95)

        self._toasts.append(toast)
        self.root.after(duration, lambda: self._fade_out(toast))

    def _fade_out(self, toast: tk.Toplevel, step: float = 0.08) -> None:
        if not toast.winfo_exists():
            return
        alpha = toast.attributes("-alpha")
        alpha -= step
        if alpha <= 0:
            toast.destroy()
            if toast in self._toasts:
                self._toasts.remove(toast)
        else:
            toast.attributes("-alpha", alpha)
            self.root.after(50, lambda: self._fade_out(toast, step))

