import os
import humanize
import threading
import time
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime

from views.home_view     import HomeView
from views.files_view    import FilesView
from views.chat_view     import ChatView
from views.settings_view import SettingsView

from theme.themes            import THEMES, THEME_LOGOS
from theme.theme_persistence import save_theme, load_theme
from theme.theme             import apply_theme

from PIL import Image, ImageTk
from watchdog.observers import Observer
from watchdog.events    import FileSystemEventHandler

from modules.ai_handler import AIHandler
from modules.data_indexer import DataIndexer
from modules.memory_store import MemoryStore, set_default_store
from modules.config_manager import ConfigManager
from modules.model_registry import detect_local_models
from modules.toast import ToastManager
from modules.path_policies import (
    default_allowed_roots,
    default_excluded_paths,
    normalise_paths,
    is_allowed,
)
from modules.telemetry import log_event


def _coerce_list(value):
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item]
    if isinstance(value, str):
        return [value] if value else []
    return []

class FSHandler(FileSystemEventHandler):
    def __init__(self, app):
        self.app = app
        self.fm = app.views["files"].file_manager

    def _notify(self, message: str) -> None:
        if not message:
            return
        self.app.root.after(0, lambda: self.app.show_toast(message))

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        self._notify(f"File created: {path.name}")
        self.fm._summary_queue.put(str(path))

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        self._notify(f"File modified: {path.name}")
        self.fm._summary_queue.put(str(path))

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        fid = str(path)
        self.fm.index["files"].pop(fid, None)
        self.fm._save_index()
        self._notify(f"File deleted: {path.name}")
        self.app.root.after(0, self.app._update_index_status)

class NousApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nous AI Assistant")
        self.root.geometry("1400x800")
        self.config = ConfigManager(Path(__file__).parent / "data" / "app_state.json")
        self.selected_model = self.config.get("selected_model", "mistral")
        self.available_models = []
        self.custom_models = _coerce_list(self.config.get("custom_models", []))
        self.model_search_paths = _coerce_list(self.config.get("model_paths", []))
        self.file_manager_split = float(self.config.get("file_manager_split", 0.5))
        self._chat_divider_ratio = float(self.config.get("chat_divider", 0.75))

        self.app_data_dir = Path(__file__).parent / "data"
        self.index_db_path = Path(
            self.config.get("index_db_path", str(self.app_data_dir / "knowledge_index.db"))
        ).expanduser().resolve()
        self.max_index_file_size_mb = float(self.config.get("max_index_file_size_mb", 8.0))
        self.memory_enabled = bool(self.config.get("memory_enabled", True))

        default_base = self.app_data_dir
        index_root = self.config.get("index_root", str(default_base))
        self.index_root = Path(index_root).expanduser().resolve()

        self.allowed_roots = normalise_paths(self.config.get("allowed_roots", []))
        if not self.allowed_roots:
            self.allowed_roots = default_allowed_roots()
        self.excluded_custom = normalise_paths(self.config.get("excluded_paths", []))
        self.default_excluded = default_excluded_paths()
        self.excluded_paths = []
        self._rebuild_exclusion_list()
        downloads_path = Path.home() / "Downloads"
        if downloads_path.exists() and downloads_path not in self.allowed_roots:
            self.allowed_roots.append(downloads_path)
            self._persist_allowed_roots()
        allowed, _ = is_allowed(self.index_root, self.allowed_roots, self.excluded_paths)
        if not allowed:
            self.allowed_roots.append(self.index_root)
            self._persist_allowed_roots()

        self.mode = (self.config.get("mode", "secure") or "secure").lower()
        if self.mode not in ("secure", "advanced"):
            self.mode = "secure"
        self.internet_search_enabled = bool(self.config.get("internet_search_enabled", False))
        self.deep_think_enabled = bool(self.config.get("deep_think_enabled", False))
        self._secure_allowed_roots_snapshot = list(self.allowed_roots)

        # Theme setup
        saved_theme = load_theme() or "nocturne"
        self.current_theme_name = saved_theme if saved_theme in THEMES else "nocturne"
        self.style = ttk.Style()
        apply_theme(self.style, self.current_theme_name)
        self.root.configure(background=THEMES[self.current_theme_name]["main_bg"])

        self.toast_manager = ToastManager(self.root, lambda: THEMES[self.current_theme_name])

        detected_models = detect_local_models(self.custom_models, self.model_search_paths)
        self.available_models = list(detected_models)
        if not self.available_models:
            if self.selected_model:
                self.available_models = [self.selected_model]
            else:
                self.available_models = []
        if self.available_models and self.selected_model not in self.available_models:
            self.selected_model = self.available_models[0]
        if not self.available_models:
            self.selected_model = "mistral"

        if not detected_models:
            self.root.after(500, lambda: self.show_toast("No local AI models detected."))

        # AI handler + knowledge systems
        self.ai_handler = AIHandler(model=self.selected_model, app_core=self)
        self.data_indexer = DataIndexer(
            base_path=self.index_root,
            db_path=self.index_db_path,
            allowed_roots=[str(p) for p in self.allowed_roots],
            excluded_paths=[str(p) for p in self.excluded_paths],
            max_file_size_mb=self.max_index_file_size_mb,
        )
        self.base_memory_path = Path(__file__).parent / "data" / "base_memory.txt"
        self.memory_store = MemoryStore(Path(__file__).parent / "data" / "memory_store.db")
        set_default_store(self.memory_store)
        self.memory_store.seed_from_file(self.base_memory_path)
        self.config.update({
            "index_db_path": str(self.index_db_path),
            "index_root": str(self.index_root),
            "max_index_file_size_mb": self.max_index_file_size_mb,
        })
        self._persist_allowed_roots()
        self._persist_excluded_paths()
        self.config.set("memory_enabled", self.memory_enabled)
        self._initialize_mode_state()

        # File-AI panel state
        self.file_ai_visible   = True
        self.file_ai_docked    = True
        self.file_ai_height    = 300
        self.file_ai_popout    = None
        self._popout_container = None
        self._chat_state       = None
        self.file_ai_ctrl      = None

        # Threads and indexing tracking
        self._manual_index_thread = None

        # Build UI
        self.setup_main_frame()
        self.setup_navigation()
        self.setup_ai_panels()
        self.setup_views()
        self._broadcast_mode_update(initial=True)
        self._update_index_status()

        # Link file-chat
        self.views['files'].set_chat_view(self.file_chat_view)

        # Filesystem watcher
        self._start_fs_watcher()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def setup_main_frame(self):
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var,
                  anchor='w', style='Status.TLabel').pack(side=tk.BOTTOM, fill=tk.X)

        self.main_frame    = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.nav_frame     = ttk.Frame(self.main_frame, width=200, style='CustomBackdrop.TFrame')
        self.nav_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.file_ai_container = ttk.Frame(
            self.content_frame,
            height=self.file_ai_height,
            style='FileAI.TFrame'
        )

    def setup_navigation(self):
        hdr = ttk.Frame(self.nav_frame, style='CustomBackdrop.TFrame')
        hdr.pack(fill=tk.X, pady=(10, 20))

        logo_path = THEME_LOGOS.get(self.current_theme_name, "assets/nous_logo_white.png")
        if os.path.exists(logo_path):
            img = Image.open(logo_path).resize((130, 130), Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(img)
            ttk.Label(hdr, image=self.logo_tk, style='Nav.TLabel').pack(pady=5)

        buttons = [
            ("Dashboard", self.show_home),
            ("File Manager", self.show_files),
            ("Settings", self.show_settings),
        ]
        for text, callback in buttons:
            btn = ttk.Button(self.nav_frame, text=text, style='Nav.TButton', command=callback)
            btn.pack(fill=tk.X, padx=12, pady=4)

    def setup_ai_panels(self):
        self.file_chat_view = ChatView(
            self.file_ai_container,
            model=self.selected_model,
            app_core=self,
            title="Workspace Assistant",
            models=self.available_models,
            on_model_change=self.switch_model,
            show_model_selector=False,
        )
        self.file_chat_view.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

    def remove_file_ai_ctrl(self):
        ctrl = getattr(self, "file_ai_ctrl", None)
        if ctrl is not None:
            ctrl.destroy()
            self.file_ai_ctrl = None

    def setup_views(self):
        self.views = {
            'home':     HomeView(self.content_frame, app_core=self),
            'files':    FilesView(self.content_frame, app_core=self),
            'settings': SettingsView(self.content_frame, app_core=self),
        }
        for v in self.views.values():
            v.pack(fill=tk.BOTH, expand=True)
            v.pack_forget()

        if hasattr(self.views['home'], "chat_view"):
            self.main_chat_view = self.views['home'].chat_view
            self.main_chat_view.update_model_list(self.available_models, self.selected_model)
            self.main_chat_view.set_model_selection(self.selected_model)

        self.show_home()

    def _start_fs_watcher(self):
        handler  = FSHandler(self)
        observer = Observer()
        self._observer = observer
        fm = self.views['files'].file_manager
        for p in fm.include_paths:
            if os.path.isdir(p):
                try:
                    observer.schedule(handler, p, recursive=True)
                except:
                    pass
        observer.daemon = True
        observer.start()

    def _on_close(self):
        if self._manual_index_thread and self._manual_index_thread.is_alive():
            if not messagebox.askyesno("Index in progress", "Close anyway?"):
                return
        try:
            self._observer.stop()
            self._observer.join(timeout=1)
        except:
            pass
        if self.file_ai_popout:
            try: self.file_ai_popout.destroy()
            except: pass
        self.data_indexer.close()
        self.memory_store.close()
        self.root.destroy()

    def show_home(self):
        self.current_view = self.views['home']
        self.file_ai_container.pack_forget()
        # Always dock for simplicity
        self.file_ai_docked = True
        self.file_ai_visible = True
        self.remove_file_ai_ctrl()
        self.update_view()

    def show_files(self):
        self.current_view = self.views['files']
        self.file_ai_container.pack_forget()
        self.remove_file_ai_ctrl()

        # Always dock for simplicity
        self.file_ai_docked = True
        self.file_ai_visible = True

        ctrl = ttk.Frame(self.content_frame)
        self.file_ai_ctrl = ctrl
        ctrl.pack(fill=tk.X, pady=(5,0))

        ttk.Button(ctrl, text="Toggle Knowledge Panel", style='TButton',
                   command=self.toggle_file_ai_panel).pack(side=tk.LEFT, padx=5)

        s = ttk.Frame(ctrl, width=10, height=10, cursor='sb_v_double_arrow')
        s.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        s.bind("<Button-1>", self.start_file_ai_resize)
        s.bind("<B1-Motion>", self.resize_file_ai_panel)

        # Always show docked panel
        self.file_ai_container.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False)
        # Ensure FilesView uses the latest chat_view
        self.views['files'].set_chat_view(self.file_chat_view)

        self.update_view()

    def show_settings(self):
        self._update_index_status()
        settings = self.views['settings']
        settings.show_test_results("")
        self.current_view = self.views['settings']
        self.file_ai_container.pack_forget()
        # Always dock for simplicity
        self.file_ai_docked = True
        self.file_ai_visible = True
        self.remove_file_ai_ctrl()
        self.update_view()

    def update_view(self):
        for v in self.views.values():
            v.pack_forget()
        self.current_view.pack(fill=tk.BOTH, expand=True)

    def toggle_file_ai_panel(self):
        self.file_ai_visible = not self.file_ai_visible
        self.update_file_ai_panel_visibility()

    def update_file_ai_panel_visibility(self):
        self.file_ai_container.pack_forget()
        if self.file_ai_visible and self.file_ai_docked:
            self.file_ai_container.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False)

    def start_file_ai_resize(self, e):
        self.file_ai_resize_start_y = e.y_root

    def resize_file_ai_panel(self, e):
        delta = self.file_ai_resize_start_y - e.y_root
        nh    = self.file_ai_container.winfo_height() + delta
        if 150 <= nh <= 600:
            self.file_ai_container.config(height=nh)
        self.file_ai_resize_start_y = e.y_root

    def set_theme(self, theme_key):
        """
        Switch to a new theme, update memory, and apply everywhere.
        """
        from theme.themes import THEMES

        # Validate
        if theme_key not in THEMES:
            print(f"Theme '{theme_key}' not found. No change made.")
            return

        self.current_theme_name = theme_key
        self.theme = THEMES[theme_key]

        # Save to config for persistence across restarts
        if hasattr(self, "save_config"):
            self.save_config()

        # Apply theme to all views
        for view in self.views.values():
            if hasattr(view, "apply_theme"):
                view.apply_theme(theme_key)

        # Update root background and file AI container directly
        self.root.configure(background=THEMES[theme_key]["main_bg"])
        self.file_ai_container.configure(style="FileAI.TFrame")
        self.file_ai_container.configure(style="ChatView.TFrame")

        print(f"Theme changed to {theme_key}")
    
    # ----- MEMORY METHODS -----
    def memory_stats(self):
        stats = self.memory_store.stats()
        stats["enabled"] = self.is_memory_enabled()
        return stats

    def clear_memory(self):
        self.memory_store.clear()
        self.memory_store.seed_from_file(self.base_memory_path)

    def search_memory(self, query: str, limit: int = 5):
        return self.memory_store.search_memory(query, limit=limit)

    def switch_model(self, model_name: str):
        model = (model_name or "").strip()
        if not model:
            return
        if model not in self.available_models:
            self.available_models.append(model)
        unique = []
        seen = set()
        for name in self.available_models:
            if not name:
                continue
            key = name.lower()
            if key not in seen:
                seen.add(key)
                unique.append(name)
        self.available_models = unique
        self.selected_model = model
        self.ai_handler.set_model(model)
        self.config.set("selected_model", model)
        if "home" in self.views and hasattr(self.views["home"], "chat_view"):
            self.views["home"].chat_view.update_model_list(self.available_models, model)
            self.views["home"].chat_view.set_model_selection(model)
        if hasattr(self, "file_chat_view"):
            self.file_chat_view.update_model_list(self.available_models, model)
            self.file_chat_view.set_model_selection(model, update_only=True)
        self.show_toast(f"Model switched to {model}")

    def export_memory(self, destination: Path | None = None) -> Path:
        dest = Path(destination) if destination else Path(__file__).parent / "data" / "memory_export.json"
        data = self.memory_store.export()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return dest

    def get_file_manager_split(self) -> float:
        return getattr(self, "file_manager_split", 0.5)

    def set_file_manager_split(self, ratio: float):
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            return
        ratio = max(0.1, min(0.9, ratio))
        self.file_manager_split = ratio
        self.config.set("file_manager_split", ratio)

    def _persist_allowed_roots(self):
        self.allowed_roots = normalise_paths([str(p) for p in self.allowed_roots])
        self.config.set("allowed_roots", [str(p) for p in self.allowed_roots])
        self._sync_indexer_policy()

    def _persist_excluded_paths(self):
        self.excluded_custom = normalise_paths([str(p) for p in self.excluded_custom])
        self._rebuild_exclusion_list()
        self.config.set("excluded_paths", [str(p) for p in self.excluded_custom])
        self._sync_indexer_policy()

    def _rebuild_exclusion_list(self):
        self.excluded_paths = self.default_excluded + [
            path for path in self.excluded_custom if path not in self.default_excluded
        ]

    def _sync_indexer_policy(self):
        if hasattr(self, "data_indexer"):
            self.data_indexer.update_policy(
                allowed_roots=[str(p) for p in self.allowed_roots],
                excluded_paths=[str(p) for p in self.excluded_paths],
                max_file_size_mb=self.max_index_file_size_mb,
            )

    def is_path_allowed(self, path: Path) -> bool:
        return is_allowed(path, self.allowed_roots, self.excluded_paths)[0]

    def resolve_user_path(self, text: str) -> Path | None:
        candidate = Path(text.strip().strip("\"").strip("'"))
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve()
            except OSError:
                return None
            return candidate if self.is_path_allowed(candidate) else None
        for root in self.allowed_roots:
            attempt = Path(root) / candidate
            try:
                resolved = attempt.resolve()
            except OSError:
                continue
            if self.is_path_allowed(resolved):
                return resolved
        return None




    def read_file_preview(self, path: Path, limit: int = 4000) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return None
        except Exception:
            return None
        return text[:limit]

    def _initialize_mode_state(self):
        self._advanced_search_pref = bool(self.internet_search_enabled)
        self._apply_mode(self.mode, initial=True)

    def _discover_system_roots(self) -> list[Path]:
        roots: list[Path] = []
        if os.name == "nt":
            for letter in map(chr, range(ord("A"), ord("Z") + 1)):
                drive = Path(f"{letter}:/")
                if drive.exists():
                    roots.append(drive)
        else:
            roots.append(Path("/"))
            for candidate in (Path("/Volumes"), Path("/mnt")):
                if candidate.exists():
                    for child in candidate.iterdir():
                        if child.exists():
                            roots.append(child)
        roots.append(self.index_root)
        return normalise_paths(roots)

    def _apply_mode(self, mode: str, initial: bool = False):
        mode = (mode or "secure").lower()
        if mode not in ("secure", "advanced"):
            mode = "secure"
        if mode == "secure":
            self._advanced_search_pref = bool(self.internet_search_enabled)
            self.mode = "secure"
            self.internet_search_enabled = False
            if self._secure_allowed_roots_snapshot:
                self.allowed_roots = normalise_paths(self._secure_allowed_roots_snapshot)
            else:
                self.allowed_roots = default_allowed_roots()
            self._persist_allowed_roots()
            log_event("mode.secure", internet_search=False, initial=initial)
            self.config.set("mode", "secure")
            self.config.set("internet_search_enabled", False)
            if not initial:
                self.show_toast("Mode changed: Secure")
                self.root.after(150, lambda: self.show_toast("Read access only."))
        else:
            if self.mode == "secure":
                self._secure_allowed_roots_snapshot = list(self.allowed_roots)
            self.mode = "advanced"
            expanded = self._discover_system_roots()
            if self._secure_allowed_roots_snapshot:
                expanded.extend(self._secure_allowed_roots_snapshot)
            self.allowed_roots = normalise_paths(expanded)
            self._persist_allowed_roots()
            self.internet_search_enabled = bool(getattr(self, "_advanced_search_pref", True))
            self.config.set("mode", "advanced")
            self.config.set("internet_search_enabled", self.internet_search_enabled)
            log_event(
                "mode.advanced",
                internet_search=self.internet_search_enabled,
                initial=initial,
            )
            if not initial:
                self.show_toast("Mode changed: Advanced Access")
                self.root.after(150, lambda: self.show_toast("Read access only."))
        self.config.set("deep_think_enabled", bool(self.deep_think_enabled))
        if not initial:
            self._broadcast_mode_update()
        else:
            self._sync_indexer_policy()
            log_event("mode.init", mode=self.mode)

    def _broadcast_mode_update(self, initial: bool = False):
        internet_available = self.mode == "advanced"
        if hasattr(self, "main_chat_view"):
            self.main_chat_view.update_mode(
                mode=self.mode,
                internet_available=internet_available,
                internet_enabled=self.internet_search_enabled,
                deep_think_enabled=self.deep_think_enabled,
            )
        if hasattr(self, "file_chat_view"):
            self.file_chat_view.update_mode(
                mode=self.mode,
                internet_available=internet_available,
                internet_enabled=self.internet_search_enabled,
                deep_think_enabled=self.deep_think_enabled,
            )
        if "settings" in getattr(self, "views", {}):
            settings = self.views["settings"]
            if hasattr(settings, "set_mode"):
                settings.set_mode(self.mode)
            if hasattr(settings, "set_runtime_flags"):
                settings.set_runtime_flags(
                    internet_enabled=self.internet_search_enabled,
                    deep_think_enabled=self.deep_think_enabled,
                )
        if initial:
            self.root.after(400, lambda: self.show_toast("Read access only."))

    def get_mode(self) -> str:
        return self.mode

    def set_mode(self, mode: str) -> None:
        if (mode or "").lower() == self.mode:
            return
        self._apply_mode(mode, initial=False)

    def is_internet_search_available(self) -> bool:
        return self.mode == "advanced"

    def is_internet_search_enabled(self) -> bool:
        return self.mode == "advanced" and bool(self.internet_search_enabled)

    def set_internet_search_enabled(self, enabled: bool) -> None:
        if self.mode != "advanced":
            self.internet_search_enabled = False
            self.config.set("internet_search_enabled", False)
            self.show_toast("Search disabled in Secure Mode.")
            log_event("network.blocked", mode=self.mode, reason="secure_mode_toggle")
            self._broadcast_mode_update()
            return
        enabled = bool(enabled)
        if self.internet_search_enabled == enabled:
            return
        self.internet_search_enabled = enabled
        self._advanced_search_pref = self.internet_search_enabled
        self.config.set("internet_search_enabled", self.internet_search_enabled)
        log_event("network.search_toggle", enabled=self.internet_search_enabled)
        if self.internet_search_enabled:
            self.show_toast("Internet search enabled.")
        else:
            self.show_toast("Internet search disabled.")
        self._broadcast_mode_update()

    def is_deep_think_enabled(self) -> bool:
        return bool(self.deep_think_enabled)

    def set_deep_think_enabled(self, enabled: bool) -> None:
        self.deep_think_enabled = bool(enabled)
        self.config.set("deep_think_enabled", self.deep_think_enabled)
        log_event("deep_think.toggle", enabled=self.deep_think_enabled)
        self._broadcast_mode_update()

    def perform_internet_search(self, query: str, limit: int = 3) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        if self.mode != "advanced":
            log_event("network.blocked", mode=self.mode, reason="secure_mode_search", query=query)
            self.show_toast("Search disabled in Secure Mode.")
            return []
        if not self.internet_search_enabled:
            log_event("network.search_skipped", mode=self.mode, reason="toggle_off", query=query)
            return []
        try:
            from modules.internet_search import search_web
        except Exception as exc:
            log_event("network.error", message=str(exc))
            self.show_toast("Unable to run internet search.")
            return []
        results = search_web(query, max_results=limit)
        log_event("network.search", query=query, results=len(results))
        return results

    def set_max_index_file_size(self, value: float):
        try:
            size = float(value)
        except (TypeError, ValueError):
            return
        size = max(1.0, min(size, 2048.0))
        self.max_index_file_size_mb = size
        self.config.set("max_index_file_size_mb", self.max_index_file_size_mb)
        self._sync_indexer_policy()

    def add_allowed_root(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        if resolved not in self.allowed_roots:
            self.allowed_roots.append(resolved)
            self._persist_allowed_roots()
            if self.mode == "secure":
                self._secure_allowed_roots_snapshot = list(self.allowed_roots)

    def remove_allowed_root(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        if resolved == self.index_root:
            return
        self.allowed_roots = [p for p in self.allowed_roots if p != resolved]
        if not self.allowed_roots:
            self.allowed_roots = default_allowed_roots()
        self._persist_allowed_roots()
        if self.mode == "secure":
            self._secure_allowed_roots_snapshot = list(self.allowed_roots)

    def add_excluded_path(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        if resolved not in self.excluded_custom and resolved not in self.default_excluded:
            self.excluded_custom.append(resolved)
            self._persist_excluded_paths()

    def remove_excluded_path(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self.excluded_custom = [p for p in self.excluded_custom if p != resolved]
        self._persist_excluded_paths()

    def get_chat_divider(self):
        return getattr(self, "_chat_divider_ratio", 0.75)

    def set_chat_divider(self, value: float):
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return
        ratio = max(0.2, min(0.95, ratio))
        self._chat_divider_ratio = ratio
        self.config.set("chat_divider", ratio)

    def show_toast(self, message: str, duration: int = 3000):
        if hasattr(self, "toast_manager"):
            self.toast_manager.show(message, duration)

    # ----- KNOWLEDGE INDEX METHODS -----
    def is_memory_enabled(self) -> bool:
        return getattr(self, "memory_enabled", True)

    def set_memory_enabled(self, enabled: bool) -> None:
        self.memory_enabled = bool(enabled)
        self.config.set("memory_enabled", self.memory_enabled)

    def start_knowledge_index(self):
        if self._manual_index_thread and self._manual_index_thread.is_alive():
            return

        settings = self.views['settings']
        settings.set_index_running(True)
        settings.reset_progress()
        settings.update_status("Indexing knowledge base...")

        def task():
            stats = self.data_indexer.rebuild_index(on_progress=self._index_progress_callback)
            self.root.after(0, lambda: self._on_index_complete(stats))

        self._manual_index_thread = threading.Thread(target=task, daemon=True)
        self._manual_index_thread.start()

    def _index_progress_callback(self, current: int, total: int, path: str) -> None:
        self.root.after(0, lambda: self.views['settings'].update_progress(current, total, path))

    def _on_index_complete(self, stats):
        settings = self.views['settings']
        settings.set_index_running(False)
        summary = f"Indexed {stats['documents']} of {stats['total_scanned']} files."
        settings.update_status(summary)
        self._update_index_status()
        self.file_chat_view.display_message(
            f"Knowledge base refreshed with {stats['documents']} documents.",
            "system"
        )

    def prompt_index_folder(self):
        initial = str(self.data_indexer.get_base_path())
        selected = filedialog.askdirectory(title="Choose folder to index", initialdir=initial)
        if not selected:
            return
        try:
            path = Path(selected).expanduser().resolve()
        except OSError as exc:
            messagebox.showerror("Knowledge Index", f"Unable to use that folder: {exc}")
            return
        allowed, _ = is_allowed(path, self.allowed_roots, self.excluded_paths)
        if not allowed:
            self.add_allowed_root(path)
        try:
            self.data_indexer.set_base_path(path)
            self.index_root = path
            self.config.set("index_root", str(self.index_root))
            self._sync_indexer_policy()
            self.views['settings'].update_status(f"Index folder updated to {path}.")
            self._update_index_status()
        except (FileNotFoundError, PermissionError) as exc:
            messagebox.showerror("Knowledge Index", str(exc))

    def test_knowledge_index(self, query: str):
        cleaned = (query or "").strip()
        if not cleaned:
            self.views['settings'].show_test_results("Enter a query to test the index.")
            return

        self.views['settings'].show_test_results("Searching...")

        def task():
            results = self.data_indexer.search(cleaned, limit=3)
            self.root.after(0, lambda: self._render_test_results(cleaned, results))

        threading.Thread(target=task, daemon=True).start()

    def _render_test_results(self, query, results):
        if not results:
            self.views['settings'].show_test_results(f"No matches for '{query}'.")
            return

        lines = []
        for hit in results:
            name = Path(hit['path']).name
            preview = hit.get('preview', '').strip() or 'No preview available.'
            lines.append(f"{name}: {preview}")
        joined = "\n\n".join(lines)
        self.views['settings'].show_test_results(joined)

    def _update_index_status(self):
        stats = self.data_indexer.stats()
        self.views['settings'].refresh_stats(stats)

    def get_knowledge_context(self, prompt: str, limit: int = 3):
        results = self.data_indexer.search(prompt, limit=limit)
        if not results:
            return "", []
        blocks = []
        sources = []
        for hit in results:
            raw_path = hit.get('path')
            path = Path(raw_path) if raw_path else Path()
            preview = (hit.get('snippet') or hit.get('preview') or "").strip()
            blocks.append(f"File: {path.name}\nLocation: {raw_path}\nExcerpt: {preview}")
            sources.append({'path': raw_path, 'preview': preview})
        return "\n\n".join(blocks), sources

    def run(self):
        self.root.mainloop()


