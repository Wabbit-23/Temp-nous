import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from theme.themes import THEMES


class SettingsView(ttk.Frame):
    """Settings screen providing theme info and knowledge index controls."""

    def __init__(self, parent, app_core=None):
        super().__init__(parent, style="TFrame")
        self.app_core = app_core
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.theme = THEMES[app_core.current_theme_name]

        self.memory_enabled_var = tk.BooleanVar(value=self.app_core.is_memory_enabled())
        self.memory_search_var = tk.StringVar()
        self.memory_results_var = tk.StringVar(value="Search results will appear here.")
        self.memory_count_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=self.app_core.get_mode())

        self.base_path_var = tk.StringVar(value=str(app_core.data_indexer.get_base_path()))
        self.index_status_var = tk.StringVar(value="Knowledge index ready.")
        self.progress_label_var = tk.StringVar(value="Waiting to start")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.documents_var = tk.StringVar(value="0 documents")
        self.last_index_var = tk.StringVar(value="Last indexed: Never")
        self.test_query_var = tk.StringVar()
        self.test_result_var = tk.StringVar()
        self.max_file_size_var = tk.DoubleVar(value=self.app_core.max_index_file_size_mb)
        self.skipped_var = tk.StringVar(value="0 skipped")
        self.errors_var = tk.StringVar(value="0 errors")
        self._allowed_items = []
        self._excluded_items = []

        wrapper = ttk.Frame(self, padding=32, style="TFrame")
        wrapper.grid(row=0, column=0, sticky="nsew")
        wrapper.columnconfigure(0, weight=1)

        self._build_appearance_card(wrapper)
        self._build_memory_card(wrapper)
        self._build_knowledge_card(wrapper)
        self._build_gpu_card(wrapper)
        self.refresh_memory(self.app_core.memory_stats())
        self.refresh_stats(self.app_core.data_indexer.stats())

    # ------------------------------------------------------------------
    def _build_appearance_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Appearance", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text="Nous AI uses the Nocturne theme for a cohesive dark experience.",
            style="Card.TLabel",
            wraplength=520
        ).grid(row=1, column=0, sticky="w", pady=(12, 0))

    def _build_memory_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=1, column=0, sticky="ew", pady=(24, 0))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Assistant Memory", style="Section.TLabel").grid(row=0, column=0, sticky="w")

        toggle = ttk.Checkbutton(
            card,
            text="Enable memory during conversations",
            variable=self.memory_enabled_var,
            command=self._on_toggle_memory,
        )
        toggle.grid(row=1, column=0, sticky="w", pady=(12, 8))

        ttk.Label(card, textvariable=self.memory_count_var, style="Muted.TLabel").grid(row=2, column=0, sticky="w")

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Button(actions, text="Clear Memory", command=self._on_clear_memory).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Export Memory", command=self._on_export_memory).grid(row=0, column=1)

        search_row = ttk.Frame(card, style="Card.TFrame")
        search_row.grid(row=4, column=0, sticky="ew", pady=(16, 4))
        search_row.columnconfigure(0, weight=1)

        ttk.Label(search_row, text="Search memory", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(search_row, textvariable=self.memory_search_var)
        entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        entry.bind("<Return>", lambda _e: self._on_memory_search())
        ttk.Button(search_row, text="Preview", command=self._on_memory_search).grid(row=1, column=1, padx=(8, 0))

        ttk.Label(card, textvariable=self.memory_results_var, style="Muted.TLabel", wraplength=520, justify="left").grid(row=5, column=0, sticky="w", pady=(8, 0))

    def _build_knowledge_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=2, column=0, sticky="ew", pady=(24, 0))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Knowledge Index", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, textvariable=self.index_status_var, style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))

        mode_row = ttk.Frame(card, style="Card.TFrame")
        mode_row.grid(row=2, column=0, sticky="w", pady=(0, 12))
        ttk.Label(mode_row, text="Mode", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        secure_btn = ttk.Radiobutton(mode_row, text="Secure", variable=self.mode_var, value="secure", command=self._on_mode_change)
        secure_btn.grid(row=0, column=1, padx=(12, 6))
        advanced_btn = ttk.Radiobutton(mode_row, text="Advanced Access", variable=self.mode_var, value="advanced", command=self._on_mode_change)
        advanced_btn.grid(row=0, column=2, padx=(6, 0))
        self.mode_buttons = [secure_btn, advanced_btn]

        path_row = ttk.Frame(card, style="Card.TFrame")
        path_row.grid(row=3, column=0, sticky="ew")
        path_row.columnconfigure(0, weight=1)
        path_row.columnconfigure(1, weight=0)

        ttk.Label(path_row, text="Indexed folder", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(path_row, textvariable=self.base_path_var, state="readonly")
        entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        path_controls = ttk.Frame(path_row, style="Card.TFrame")
        path_controls.grid(row=1, column=1, sticky="e", padx=(12, 0))
        self.change_folder_btn = ttk.Button(path_controls, text="Change", command=self._on_choose_folder)
        self.change_folder_btn.pack(side="left")
        self.view_folder_btn = ttk.Button(path_controls, text="Open", command=self._on_open_folder)
        self.view_folder_btn.pack(side="left", padx=(8, 0))

        policy_frame = ttk.Frame(card, style="Card.TFrame")
        policy_frame.grid(row=4, column=0, sticky="ew", pady=(16, 12))
        policy_frame.columnconfigure((0, 1), weight=1)

        allowed_col = ttk.Frame(policy_frame, style="Card.TFrame")
        allowed_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        allowed_col.columnconfigure(0, weight=1)
        ttk.Label(allowed_col, text="Allowed roots", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        list_style = {
            "height": 5,
            "exportselection": False,
            "activestyle": "none",
            "bg": self.theme["card_bg"],
            "fg": self.theme["text"],
            "highlightthickness": 1,
            "highlightcolor": self.theme["accent"],
            "selectbackground": self.theme["accent"],
            "selectforeground": "#FFFFFF",
            "relief": "flat",
        }
        self.allowed_listbox = tk.Listbox(allowed_col, **list_style)
        self.allowed_listbox.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        allowed_actions = ttk.Frame(allowed_col, style="Card.TFrame")
        allowed_actions.grid(row=2, column=0, sticky="e", pady=(6, 0))
        self.add_allowed_btn = ttk.Button(allowed_actions, text="Add", command=self._on_add_allowed_root)
        self.add_allowed_btn.pack(side="left")
        self.remove_allowed_btn = ttk.Button(allowed_actions, text="Remove", command=self._on_remove_allowed_root)
        self.remove_allowed_btn.pack(side="left", padx=(8, 0))

        excluded_col = ttk.Frame(policy_frame, style="Card.TFrame")
        excluded_col.grid(row=0, column=1, sticky="nsew")
        excluded_col.columnconfigure(0, weight=1)
        ttk.Label(excluded_col, text="Excluded paths", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.excluded_listbox = tk.Listbox(excluded_col, **list_style)
        self.excluded_listbox.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        ttk.Label(excluded_col, text="System entries are locked.", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        excluded_actions = ttk.Frame(excluded_col, style="Card.TFrame")
        excluded_actions.grid(row=3, column=0, sticky="e", pady=(6, 0))
        self.add_excluded_btn = ttk.Button(excluded_actions, text="Add", command=self._on_add_excluded_path)
        self.add_excluded_btn.pack(side="left")
        self.remove_excluded_btn = ttk.Button(excluded_actions, text="Remove", command=self._on_remove_excluded_path)
        self.remove_excluded_btn.pack(side="left", padx=(8, 0))

        config_row = ttk.Frame(card, style="Card.TFrame")
        config_row.grid(row=5, column=0, sticky="ew")
        config_row.columnconfigure(1, weight=1)
        ttk.Label(config_row, text="Max file size (MB)", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.max_size_spin = ttk.Spinbox(
            config_row,
            from_=1.0,
            to=2048.0,
            increment=1.0,
            textvariable=self.max_file_size_var,
            width=8
        )
        self.max_size_spin.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.apply_max_size_btn = ttk.Button(config_row, text="Apply", command=self._on_apply_max_file_size)
        self.apply_max_size_btn.grid(row=0, column=2, padx=(12, 0))
        ttk.Label(config_row, textvariable=self.skipped_var, style="Muted.TLabel").grid(row=0, column=3, sticky="w", padx=(24, 0))
        ttk.Label(config_row, textvariable=self.errors_var, style="Muted.TLabel").grid(row=0, column=4, sticky="w", padx=(12, 0))

        ttk.Label(card, textvariable=self.progress_label_var, style="Muted.TLabel").grid(row=6, column=0, sticky="w", pady=(16, 6))
        self.progress_bar = ttk.Progressbar(card, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=7, column=0, sticky="ew")

        action_row = ttk.Frame(card, style="Card.TFrame")
        action_row.grid(row=8, column=0, sticky="ew", pady=(18, 12))
        action_row.columnconfigure(0, weight=1)
        self.rebuild_button = ttk.Button(action_row, text="Rebuild Index", style="Primary.TButton", command=self._on_rebuild)
        self.rebuild_button.grid(row=0, column=0, sticky="w")

        stats_row = ttk.Frame(card, style="StatusCard.TFrame")
        stats_row.grid(row=9, column=0, sticky="ew")
        stats_row.columnconfigure(0, weight=1)
        stats_row.columnconfigure(1, weight=1)

        stats_col = ttk.Frame(stats_row, style="StatusCard.TFrame")
        stats_col.grid(row=0, column=0, sticky="nsew")
        stats_col.columnconfigure(0, weight=1)
        ttk.Label(stats_col, textvariable=self.documents_var, style="StatusValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(stats_col, textvariable=self.last_index_var, style="StatusCaption.TLabel").grid(row=1, column=0, sticky="w")

        test_box = ttk.Frame(stats_row, style="Card.TFrame")
        test_box.grid(row=0, column=1, sticky="nsew")
        test_box.columnconfigure(0, weight=1)
        ttk.Label(test_box, text="Test query", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(test_box, textvariable=self.test_query_var)
        entry.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        entry.bind("<Return>", lambda _e: self._on_test_query())
        self.test_btn = ttk.Button(test_box, text="Run Test", command=self._on_test_query)
        self.test_btn.grid(row=1, column=1, padx=(8, 0))
        ttk.Label(test_box, textvariable=self.test_result_var, style="Muted.TLabel", wraplength=280, justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._refresh_policy_lists()

    def _refresh_policy_lists(self):
        self.allowed_listbox.delete(0, tk.END)
        self._allowed_items = []
        for path in self.app_core.allowed_roots:
            text = str(path)
            self.allowed_listbox.insert(tk.END, text)
            self._allowed_items.append(text)

        self.excluded_listbox.delete(0, tk.END)
        self._excluded_items = []
        defaults = {str(p) for p in self.app_core.default_excluded}
        for path in self.app_core.excluded_paths:
            text = str(path)
            is_system = text in defaults
            label = f"{text} (system)" if is_system else text
            self.excluded_listbox.insert(tk.END, label)
            self._excluded_items.append((text, is_system))

    def _build_gpu_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=2, column=0, sticky="ew", pady=(24, 0))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="GPU Settings", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text="Max VRAM (GiB)", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))

        self.vram_var = tk.DoubleVar(value=self.app_core.ai_handler.max_vram_usage)
        ttk.Entry(card, textvariable=self.vram_var, width=6).grid(row=1, column=1, sticky="w", padx=(12, 0))
        ttk.Button(card, text="Apply", command=self._on_vram_change).grid(row=1, column=2, padx=(16, 0))

    # ------------------------------------------------------------------
    # Event handlers
    def _on_add_allowed_root(self):
        selected = filedialog.askdirectory(title="Select allowed root")
        if not selected:
            return
        path = Path(selected)
        self.app_core.add_allowed_root(path)
        self._refresh_policy_lists()
        self.app_core.show_toast(f"Allowed root added: {path}")

    def _on_remove_allowed_root(self):
        selection = self.allowed_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._allowed_items):
            return
        path_str = self._allowed_items[index]
        path = Path(path_str)
        if path == self.app_core.index_root:
            messagebox.showinfo("Allowed Roots", "Cannot remove the active index folder.")
            return
        self.app_core.remove_allowed_root(path)
        self._refresh_policy_lists()

    def _on_add_excluded_path(self):
        folder = filedialog.askdirectory(title="Select folder to exclude")
        path = None
        if folder:
            path = Path(folder)
        else:
            file_path = filedialog.askopenfilename(title="Select file to exclude")
            if file_path:
                path = Path(file_path)
        if not path:
            return
        self.app_core.add_excluded_path(path)
        self._refresh_policy_lists()
        self.app_core.show_toast(f"Excluded path added: {path}")

    def _on_remove_excluded_path(self):
        selection = self.excluded_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._excluded_items):
            return
        path_str, is_system = self._excluded_items[index]
        if is_system:
            messagebox.showinfo("Excluded Paths", "System exclusions cannot be removed.")
            return
        self.app_core.remove_excluded_path(Path(path_str))
        self._refresh_policy_lists()

    def _on_apply_max_file_size(self):
        try:
            value = float(self.max_file_size_var.get())
        except (TypeError, ValueError):
            messagebox.showerror("Knowledge Index", "Enter a valid file size in megabytes.")
            return
        self.app_core.set_max_index_file_size(value)
        self.app_core.show_toast(f"Max index size set to {value:.0f} MB")

    def _on_mode_change(self):
        self.app_core.set_mode(self.mode_var.get())

    def _on_choose_folder(self):
        self.app_core.prompt_index_folder()

    def _on_rebuild(self):
        self.app_core.start_knowledge_index()

    def _on_open_folder(self):
        base = Path(self.base_path_var.get())
        if not base.exists():
            messagebox.showerror("Open Folder", "Directory does not exist.")
            return

        destination = str(base.resolve())
        try:
            if hasattr(os, "startfile"):
                os.startfile(destination)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", destination])
            else:
                subprocess.Popen(["xdg-open", destination])
        except Exception as exc:
            messagebox.showerror("Open Folder", f"Unable to open folder: {exc}")

    def _on_test_query(self):
        self.app_core.test_knowledge_index(self.test_query_var.get())

    def _on_vram_change(self):
        try:
            value = float(self.vram_var.get())
        except ValueError:
            messagebox.showerror("GPU Settings", "Please enter a valid number.")
            return
        self.app_core.ai_handler.update_gpu_limits(vram_gb=value)
        messagebox.showinfo("GPU Settings", f"Max VRAM usage set to {value:.1f} GiB.")

    def _on_toggle_memory(self):
        enabled = self.memory_enabled_var.get()
        self.app_core.set_memory_enabled(enabled)
        self.refresh_memory(self.app_core.memory_stats())

    def _on_clear_memory(self):
        if not messagebox.askyesno("Clear Memory", "Remove all stored memory items?"):
            return
        self.app_core.clear_memory()
        self.memory_results_var.set("Memory cleared.")
        self.refresh_memory(self.app_core.memory_stats())

    def _on_export_memory(self):
        path = self.app_core.export_memory()
        messagebox.showinfo("Export Memory", f"Memory exported to\n{path}")

    def _on_memory_search(self):
        query = self.memory_search_var.get().strip()
        if not query:
            self.memory_results_var.set("Enter a keyword to search.")
            return
        results = self.app_core.search_memory(query, limit=5)
        if not results:
            self.memory_results_var.set("No matching memories.")
            return
        lines = []
        for item in results:
            key = item.get("key", "")
            value = item.get("value", "")
            lines.append(f"{key}: {value}")
        self.memory_results_var.set("\n".join(lines))

    # ------------------------------------------------------------------
    # Callbacks consumed by the controller
    def set_index_running(self, running: bool):
        state = "disabled" if running else "normal"
        self.rebuild_button.config(state=state)
        self.test_btn.config(state=state)
        self.change_folder_btn.config(state=state)
        self.view_folder_btn.config(state=state)
        for btn in getattr(self, "mode_buttons", []):
            btn.config(state=state)
        self.add_allowed_btn.config(state=state)
        self.remove_allowed_btn.config(state=state)
        self.add_excluded_btn.config(state=state)
        self.remove_excluded_btn.config(state=state)
        self.apply_max_size_btn.config(state=state)
        list_state = "disabled" if running else "normal"
        self.allowed_listbox.configure(state=list_state)
        self.excluded_listbox.configure(state=list_state)
        self.max_size_spin.configure(state=state)

    def update_progress(self, current: int, total: int, path: str):
        percent = 0 if total == 0 else (current / total) * 100
        self.progress_value.set(percent)
        display = Path(path).name if path else ""
        suffix = f" - {display}" if display else ""
        self.progress_label_var.set(f"Indexed {current} of {total} files{suffix}")

    def update_status(self, text: str):
        self.index_status_var.set(text)

    def refresh_memory(self, stats):
        count = stats.get("count", 0)
        label = "1 stored item" if count == 1 else f"{count} stored items"
        self.memory_count_var.set(label)
        enabled = stats.get("enabled", True)
        if self.memory_enabled_var.get() != enabled:
            self.memory_enabled_var.set(enabled)

    def refresh_stats(self, stats):
        docs = stats.get("documents", 0)
        self.documents_var.set(f"{docs} documents")
        last = stats.get("last_indexed", "Never")
        self.last_index_var.set(f"Last indexed: {last}")
        base = stats.get("base_path")
        if base:
            self.base_path_var.set(base)
        skipped = stats.get("skipped", 0)
        errors = stats.get("errors", 0)
        self.skipped_var.set(f"{skipped} skipped")
        self.errors_var.set(f"{errors} errors")
        self.max_file_size_var.set(self.app_core.max_index_file_size_mb)
        self._refresh_policy_lists()

    def show_test_results(self, text: str):
        self.test_result_var.set(text)

    def reset_progress(self):
        self.progress_value.set(0)
        self.progress_label_var.set("Waiting to start")

    def set_mode(self, mode: str):
        if self.mode_var.get() != mode:
            self.mode_var.set(mode)

    def set_runtime_flags(self, internet_enabled: bool, deep_think_enabled: bool):
        # Placeholders for runtime indicators; UI toggles live in chat view
        self._internet_enabled = bool(internet_enabled)
        self._deep_think_enabled = bool(deep_think_enabled)







