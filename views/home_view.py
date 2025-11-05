import tkinter as tk
from tkinter import ttk
from theme.themes import THEMES

class HomeView(ttk.Frame):
    def __init__(self, parent, app_core=None):
        super().__init__(parent)
        self.app_core = app_core

        # Just the chatbot view
        from views.chat_view import ChatView
        selected = getattr(self.app_core, "selected_model", "mistral")
        models = getattr(self.app_core, "available_models", [])
        self.chat_view = ChatView(
            self,
            model=selected,
            app_core=self.app_core,
            title="General Assistant",
            models=models,
            on_model_change=self.app_core.switch_model,
            show_model_selector=True,
        )
        self.chat_view.pack(fill=tk.BOTH, expand=True)

    def apply_theme(self, theme_key):
        theme = THEMES[theme_key]
        self.configure(style='TFrame')
        # If you have self.chat_view or any AI panel, propagate:
        if hasattr(self, "chat_view") and hasattr(self.chat_view, "apply_theme"):
            self.chat_view.apply_theme(theme_key)


    def focus_entry(self):
        if hasattr(self.chat_view, "focus_entry"):
            self.chat_view.focus_entry()

