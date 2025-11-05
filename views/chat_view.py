import tkinter as tk
from tkinter import ttk
from pathlib import Path
import json
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

from theme.themes import THEMES
from modules.telemetry import log_event


class ToolTip:
    def __init__(self, widget, text, app_core=None):
        self.widget = widget
        self.text = text
        self.tipwin = None
        self.app_core = app_core
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tipwin or not self.text:
            return
        x = event.x_root + 10
        y = event.y_root + 10
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        theme_name = self.app_core.current_theme_name if self.app_core else "modern_midnight"
        theme = THEMES[theme_name]
        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background=theme["chat_bg"],
            foreground=theme["text"],
            relief="solid",
            borderwidth=1,
            wraplength=250,
            padx=6,
            pady=4,
        )
        label.pack()
        self.tipwin = tw

    def hide(self, event=None):
        if self.tipwin:
            self.tipwin.destroy()
            self.tipwin = None


class ChatView(ttk.Frame):
    def __init__(self, parent, model="default", app_core=None, title="General AI Assistant", models=None, on_model_change=None, show_model_selector=True):
        super().__init__(parent)
        self.model = model
        self.app_core = app_core
        self.title_text = title
        self.available_models = models or []
        self.on_model_change = on_model_change
        self.show_model_selector = show_model_selector

        self.mode = "secure"
        self.internet_available = False
        self.internet_enabled = False
        self.deep_think_enabled = False
        if self.app_core:
            if hasattr(self.app_core, "get_mode"):
                self.mode = self.app_core.get_mode()
            if hasattr(self.app_core, "is_internet_search_available"):
                self.internet_available = self.app_core.is_internet_search_available()
            if hasattr(self.app_core, "is_internet_search_enabled"):
                self.internet_enabled = self.app_core.is_internet_search_enabled()
            if hasattr(self.app_core, "is_deep_think_enabled"):
                self.deep_think_enabled = self.app_core.is_deep_think_enabled()

        self.message_labels = []
        self.message_senders = []
        self.message_bubbles = []
        self.message_context_sections = []
        self.message_badges = []
        self.file_context = None
        self.context_path = None

        self.placeholder_text = ""
        self._has_placeholder = False
        self._current_wrap = 720

        theme = self._current_theme()


        self.configure(style="ChatView.TFrame")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(1, weight=1)

        # Header
        self.header = ttk.Frame(self, style="ChatHeader.TFrame", padding=(24, 18, 24, 8))
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.header.columnconfigure(0, weight=1)
        self.header.columnconfigure(1, weight=0)

        self.title_label = ttk.Label(self.header, text=title, style="ChatHeader.Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.model_controls = ttk.Frame(self.header, style="ChatHeader.TFrame")
        self.model_controls.grid(row=0, column=1, sticky="e")

        self.mode_badge = ttk.Label(self.model_controls, text=self.mode.title(), style="StatusChip.TLabel")
        self.mode_badge.pack(side="left", padx=(0, 8))

        self.status_badge = ttk.Label(self.model_controls, text=str(model).upper(), style="Badge.TLabel")
        self.status_badge.pack(side="left", padx=(0, 8))

        self.model_var = tk.StringVar(value=model)
        self.model_selector = ttk.Combobox(
            self.model_controls,
            textvariable=self.model_var,
            values=self.available_models,
            state="readonly",
            width=16,
        )
        self.model_selector.bind("<<ComboboxSelected>>", self._on_model_selected)

        self.subtitle_label = ttk.Label(self.header, text="", style="ChatHeader.Subtitle.TLabel")
        self.subtitle_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._refresh_model_selector()

        self.update_model_list(self.available_models, model)

        # Chat transcript area
        self.chat_area = tk.Canvas(
            self,
            borderwidth=0,
            highlightthickness=0,
            background=theme["chat_bg"],
        )
        self.chat_area.grid(row=1, column=0, sticky="nsew", padx=(24, 0), pady=(0, 12))

        self.chat_scroll = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.chat_area.yview,
            style="Custom.Vertical.TScrollbar",
        )
        self.chat_area.configure(yscrollcommand=self.chat_scroll.set)
        self.chat_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 12))

        self.chat_frame = ttk.Frame(self.chat_area, style="ChatFrame.TFrame")
        self.chat_window = self.chat_area.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_frame.bind(
            "<Configure>",
            lambda e: self.chat_area.configure(scrollregion=self.chat_area.bbox("all"))
        )
        self.chat_area.bind("<Configure>", self._resize_chat_frame)
        self.chat_area.bind("<Enter>", lambda _: self.chat_area.bind_all("<MouseWheel>", self._on_mousewheel))
        self.chat_area.bind("<Leave>", lambda _: self.chat_area.unbind_all("<MouseWheel>"))

        # Composer
        self.entry_frame = ttk.Frame(self, style="ChatEntry.TFrame", padding=(24, 12, 24, 24))
        self.entry_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.entry_frame.columnconfigure(0, weight=1)

        self.input_wrapper = ttk.Frame(self.entry_frame, style="InputWrapper.TFrame", padding=1)
        self.input_wrapper.grid(row=0, column=0, sticky="ew")
        self.input_wrapper.columnconfigure(0, weight=1)

        self.input_inner = ttk.Frame(self.input_wrapper, style="InputInner.TFrame", padding=(12, 10))
        self.input_inner.grid(row=0, column=0, sticky="ew")
        self.input_inner.columnconfigure(0, weight=1)

        self.user_input = tk.Text(
            self.input_inner,
            height=3,
            wrap="word",
            font=("Segoe UI", 10),
            bd=0,
            highlightthickness=0,
            relief="flat",
            bg=theme["input_bg"],
            fg=theme["text"],
            insertbackground=theme["text"],
        )
        self.user_input.grid(row=0, column=0, sticky="ew")

        button_frame = ttk.Frame(self.entry_frame, style="ChatEntry.TFrame")
        button_frame.grid(row=0, column=1, sticky="e", padx=(12, 0))
        button_frame.columnconfigure(0, weight=0)
        button_frame.columnconfigure(1, weight=0)
        button_frame.columnconfigure(2, weight=0)

        self.spinner = ttk.Progressbar(button_frame, mode="indeterminate", length=90)
        self.spinner.grid(row=0, column=2, padx=(12, 0))
        self.spinner.grid_remove()

        self.search_button = ttk.Button(
            button_frame,
            text="Search",
            command=self._trigger_search,
        )
        self.search_button.grid(row=0, column=0, padx=(0, 8))

        self.send_button = ttk.Button(
            button_frame,
            text="Send",
            style="Primary.TButton",
            command=self.send_message,
        )
        self.send_button.grid(row=0, column=1)

        self._suspend_toggle_callbacks = False
        self.toggle_frame = ttk.Frame(self.entry_frame, style="ChatEntry.TFrame")
        self.toggle_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.deep_think_var = tk.BooleanVar(value=self.deep_think_enabled)
        self.deep_think_toggle = ttk.Checkbutton(
            self.toggle_frame,
            text="Deep Think",
            variable=self.deep_think_var,
            command=self._on_deep_think_toggle,
        )
        self.deep_think_toggle.grid(row=0, column=0, padx=(0, 12))

        self.internet_search_var = tk.BooleanVar(value=self.internet_enabled)
        self.internet_toggle = ttk.Checkbutton(
            self.toggle_frame,
            text="Internet Search",
            variable=self.internet_search_var,
            command=self._on_internet_toggle,
        )
        self.internet_toggle.grid(row=0, column=1, padx=(0, 12))

        self._busy_state = False
        self.user_input.bind("<FocusIn>", self._handle_focus_in)
        self.user_input.bind("<FocusOut>", self._handle_focus_out)
        self.user_input.bind("<Return>", self._handle_return)
        self.user_input.bind("<Shift-Return>", self._handle_shift_return)
        self.user_input.bind("<Control-Return>", self._handle_search_shortcut)

        self._set_placeholder(force=True, theme=theme)
        self._update_header()
        self.update_mode(
            mode=self.mode,
            internet_available=self.internet_available,
            internet_enabled=self.internet_enabled,
            deep_think_enabled=self.deep_think_enabled,
        )

    def _current_theme(self):
        theme_name = self.app_core.current_theme_name if self.app_core else "modern_midnight"
        return THEMES[theme_name]

    def _resize_chat_frame(self, event):
        width = event.width
        self.chat_area.itemconfig(self.chat_window, width=width)
        self._current_wrap = min(max(width - 160, 320), 900)
        self.refresh_messages()

    def _on_mousewheel(self, event):
        if event.delta:
            delta = int(-1 * (event.delta / 120))
        else:
            num = getattr(event, "num", 0)
            delta = -1 if num == 4 else 1
        self.chat_area.yview_scroll(delta, "units")

    def set_file_context(self, path, content):
        self.context_path = path
        self.file_context = content[:2000] if content else None
        # File metadata is surfaced via the editor status chip
        # no chat-level notification required.

    def _get_user_text(self):
        if self._has_placeholder:
            return ""
        return self.user_input.get("1.0", "end").strip()

    def _clear_input(self):
        self._set_placeholder(force=True)

    def _set_placeholder(self, force=False, theme=None):
        if not force and self._get_user_text():
            return
        theme = theme or self._current_theme()
        self.user_input.configure(state="normal")
        self.user_input.delete("1.0", "end")
        self.user_input.insert("1.0", self.placeholder_text)
        self.user_input.configure(fg=theme.get("muted_text", theme["text"]))
        self.user_input.mark_set("insert", "1.0")
        self._has_placeholder = True

    def _clear_placeholder(self):
        if not self._has_placeholder:
            return
        theme = self._current_theme()
        self.user_input.delete("1.0", "end")
        self.user_input.configure(fg=theme["text"])
        self._has_placeholder = False

    def _handle_focus_in(self, _):
        self._clear_placeholder()

    def _handle_focus_out(self, _):
        self._set_placeholder()

    def _handle_return(self, event):
        self.send_message()
        return "break"

    def _handle_shift_return(self, event):
        self.user_input.insert("insert", "\n")
        return "break"

    def _handle_search_shortcut(self, event):
        self._trigger_search()
        return "break"

    def _trigger_search(self):
        query = self._get_user_text()
        if not query:
            self.display_message("Please enter something to search for.", "system")
            self.focus_entry()
            return
        self.handle_file_search(query)
        self.focus_entry()

    def _on_deep_think_toggle(self):
        if self._suspend_toggle_callbacks:
            return
        value = bool(self.deep_think_var.get())
        self.deep_think_enabled = value
        if self.app_core and hasattr(self.app_core, "set_deep_think_enabled"):
            self.app_core.set_deep_think_enabled(value)
        else:
            log_event("deep_think.toggle_ui", enabled=value)

    def _on_internet_toggle(self):
        if self._suspend_toggle_callbacks:
            return
        value = bool(self.internet_search_var.get())
        if self.app_core and hasattr(self.app_core, "set_internet_search_enabled"):
            self.app_core.set_internet_search_enabled(value)
        else:
            self.internet_enabled = value
            log_event("network.search_toggle_ui", enabled=value)

    def send_message(self):
        if self._busy_state:
            if hasattr(self.app_core, "show_toast"):
                self.app_core.show_toast("Assistant is still responding. Please wait.", 2500)
            return
        user_msg = self._get_user_text()
        if not user_msg:
            return
        self.display_message(user_msg, "user")
        self._clear_input()

        if self.file_context and self.context_path:
            prompt = (
                f"File: {Path(self.context_path).name}\n"
                f"{self.file_context}\n\n"
                f"User: {user_msg}"
            )
        else:
            prompt = user_msg

        deep_think = self.app_core.is_deep_think_enabled() if self.app_core else bool(self.deep_think_var.get())
        internet_available = self.app_core.is_internet_search_available() if self.app_core else self.internet_available
        internet_enabled = self.app_core.is_internet_search_enabled() if self.app_core else bool(self.internet_search_var.get())
        self._start_async_query(prompt, user_msg, deep_think, internet_available, internet_enabled)

    def ai_query(self, prompt):
        related_context, knowledge_context, knowledge_sources, file_context, file_sources = self._collect_context(prompt)
        system_context, system_sources = self._build_local_facts(prompt)
        local_sections = [part for part in [file_context, system_context] if part]
        combined_local_context = "\n\n".join(local_sections)


        combined_local_sources = (file_sources or []) + (system_sources or [])
        full_prompt = self._prepare_prompt(
            prompt,
            knowledge_context=knowledge_context,
            related_context=related_context,
            local_context=combined_local_context,
        )
        res = self.app_core.ai_handler.query_with_retry(full_prompt)
        if res["success"]:
            context_items = self._build_context_metadata(knowledge_sources, [], combined_local_sources)
            self.display_message(res["response"], sender="ai", context=context_items)
        else:
            self.display_message(f"Error: {res['error']}", sender="system")

    def _build_local_facts(self, prompt):
        lower = (prompt or "").lower()
        now_local = datetime.now().astimezone()
        lines = []
        if any(keyword in lower for keyword in ["date", "today", "day is it", "current date"]):
            lines.append(now_local.strftime("Current local date: %A, %d %B %Y"))
        if any(keyword in lower for keyword in ["time", "current time", "time is it", "clock"]):
            lines.append(now_local.strftime("Current local time: %H:%M %Z"))
        if any(keyword in lower for keyword in ["year", "what year"]):
            lines.append(f"Current year: {now_local.year}")
        if not lines:
            return "", []
        preview = "\n".join(lines)
        info_items = [{"path": "System Info", "preview": preview, "type": "system"}]
        return "System Info:\n" + preview, info_items

    def _extract_file_contexts(self, prompt, max_files: int = 3):
        if not self.app_core:
            return "", []
        raw_matches = re.findall(r"[\w./\\:-]+\.(?:txt|log|json|md|csv)", prompt, re.IGNORECASE)
        matches = []
        for candidate in raw_matches:
            if candidate not in matches:
                matches.append(candidate)
            if len(matches) >= max_files:
                break
        resolver = getattr(self.app_core, 'resolve_user_path', None)
        reader = getattr(self.app_core, 'read_file_preview', None)
        if not resolver or not reader:
            return "", []
        sections = []
        sources = []
        for match in matches:
            resolved = resolver(match)
            if not resolved:
                continue
            preview = reader(resolved)
            if not preview:
                continue
            sections.append(f"File: {resolved.name}\nLocation: {resolved}\nExcerpt:\n{preview[:800]}")
            sources.append({"path": str(resolved), "preview": preview[:200], "type": "file"})
        if not sections:
            return "", []
        return "\n\n".join(sections), sources

    def _collect_context(self, prompt):
        current_path = getattr(self, "current_file_path", None)
        if not current_path:
            current_path = Path.home() / "Documents"

        related_context = ""
        needs_context = any(
            trigger in prompt.lower()
            for trigger in ["related files", "same folder", "all files here", "compare this", "other config", "check nearby"]
        )

        path_obj = Path(current_path)
        if needs_context and path_obj.is_file():
            folder = path_obj.parent
            related_files = [
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in {".txt", ".md", ".py", ".json"}
            ]
            snippets = []
            for file_path in related_files:
                try:
                    size_ok = file_path.stat().st_size < 100_000
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    snippets.append(f"{file_path.name}:\n{content[:2000 if not size_ok else None]}")
                except Exception:
                    continue
            related_context = "\n\n".join(snippets)

        knowledge_context = ""
        knowledge_sources = []
        if hasattr(self.app_core, "get_knowledge_context"):
            try:
                knowledge_context, knowledge_sources = self.app_core.get_knowledge_context(prompt)
                if not isinstance(knowledge_sources, list):
                    knowledge_sources = []
            except TypeError:
                knowledge_context = self.app_core.get_knowledge_context(prompt)
                knowledge_sources = []

        file_context, file_sources = self._extract_file_contexts(prompt)

        return related_context, knowledge_context, knowledge_sources, file_context, file_sources


    def _prepare_prompt(
        self,
        prompt,
        *,
        knowledge_context="",
        related_context="",
        local_context="",
        web_sources=None,
        reasoning_notes=None,
    ):
        prompt_sections = []
        if reasoning_notes:
            summary = "\n".join(f"- {note}" for note in reasoning_notes if note)
            if summary:
                prompt_sections.append("Reasoning Summary:\n" + summary)
        if knowledge_context:
            prompt_sections.append("Knowledge Base Excerpts:\n" + knowledge_context)
        if related_context:
            prompt_sections.append("Related Folder Files:\n" + related_context)
        if local_context:
            prompt_sections.append(local_context)
        if web_sources:
            formatted = []
            for item in web_sources:
                title = item.get("title") or item.get("url") or "Source"
                snippet = (item.get("snippet") or "").strip()
                domain = item.get("domain") or ""
                line = f"{title} ({domain})" if domain else title
                if snippet:
                    line += f": {snippet}"
                formatted.append(line)
            if formatted:
                prompt_sections.append("Web Search Findings:\n" + "\n".join(formatted))
        prompt_sections.append("User Request:\n" + prompt)

        full_prompt = "\n\n".join(prompt_sections)
        return full_prompt

    def _build_context_metadata(self, knowledge_sources, web_sources, local_sources=None):
        items = []
        for src in knowledge_sources or []:
            items.append(
                {
                    "path": src.get("path"),
                    "preview": src.get("preview"),
                    "type": "local",
                }
            )
        for src in (local_sources or []):
            items.append(src)
        for src in web_sources or []:
            title = src.get("title") or src.get("url") or "Source"
            preview = (src.get("snippet") or "").strip()
            domain = src.get("domain") or ""
            if not domain:
                url = src.get("url") or ""
                if url:
                    domain = urlparse(url).netloc
            items.append(
                {
                    "path": title,
                    "preview": preview,
                    "domain": domain,
                    "type": "web",
                }
            )
        return items

    def _run_reasoning(self, prompt, has_knowledge, has_file_context, internet_available, internet_enabled):
        notes = []
        notes.append("Analyzed user request.")
        if has_knowledge:
            notes.append("Local knowledge likely sufficient.")
        else:
            notes.append("Local knowledge limited.")
        notes.append("Active file context available." if has_file_context else "No active file context.")

        lower_prompt = (prompt or "").lower()
        keyword_triggers = {"latest", "news", "update", "today", "current", "recent", "release", "forecast"}
        question_triggers = any(lower_prompt.startswith(prefix) for prefix in ("who", "what", "when", "where", "why", "how"))
        prompt_tokens = set(lower_prompt.split())

        should_search = False
        if internet_available and internet_enabled:
            if not has_knowledge or keyword_triggers.intersection(prompt_tokens) or question_triggers:
                should_search = True
                notes.append("Will supplement with web search.")
            else:
                notes.append("Skipping web search; local resources appear sufficient.")
        else:
            if not internet_available:
                notes.append("Internet search unavailable in current mode.")
            elif not internet_enabled:
                notes.append("Internet search toggle is off.")

        log_event(
            "reasoning.plan",
            has_knowledge=has_knowledge,
            has_file_context=has_file_context,
            internet_available=internet_available,
            internet_enabled=internet_enabled,
            should_search=should_search,
        )
        return notes, should_search

    def _append_sources(self, message: str, web_sources) -> str:
        entries = []
        seen = set()
        for src in web_sources or []:
            title = src.get("title") or src.get("url") or "Source"
            domain = src.get("domain") or ""
            if not domain:
                url = src.get("url") or ""
                if url:
                    domain = urlparse(url).netloc
            key = (title, domain)
            if key in seen:
                continue
            seen.add(key)
            if domain:
                entries.append(f"{title} ({domain})")
            else:
                entries.append(title)
        if not entries:
            return message
        suffix = "Sources: " + "; ".join(entries)
        if not message:
            return suffix
        separator = "\n\n" if not message.endswith("\n") else "\n"
        return message + separator + suffix

    def _start_async_query(self, prompt, user_message, deep_think, internet_available, internet_enabled):
        if self._busy_state:
            return
        self._set_busy(True)
        thread = threading.Thread(
            target=self._perform_query,
            args=(prompt, user_message, deep_think, internet_available, internet_enabled),
            daemon=True,
        )
        thread.start()

    def _perform_query(self, prompt, user_message, deep_think, internet_available, internet_enabled):
        web_sources = []
        context_items = []
        reasoning_notes = None
        try:
            related_context, knowledge_context, knowledge_sources, file_context, file_sources = self._collect_context(prompt)
            has_knowledge = bool(knowledge_context.strip())
            has_file_context = bool(file_context or self.file_context)

            should_search = False
            plan_notes = []
            if deep_think or internet_enabled:
                plan_notes, should_search = self._run_reasoning(
                    user_message,
                    has_knowledge=has_knowledge,
                    has_file_context=has_file_context,
                    internet_available=internet_available,
                    internet_enabled=internet_enabled,
                )
                if deep_think:
                    reasoning_notes = plan_notes

            system_context, system_sources = self._build_local_facts(user_message or prompt)

            if should_search and internet_available and internet_enabled and self.app_core:
                web_sources = self.app_core.perform_internet_search(user_message or prompt, limit=3) or []
            elif should_search and not internet_available:
                log_event("reasoning.search_blocked", mode=getattr(self.app_core, "get_mode", lambda: "secure")(), query=user_message)
                if self.app_core and hasattr(self.app_core, "show_toast"):
                    self.app_core.show_toast("Search disabled in Secure Mode.")
            elif should_search and internet_available and not internet_enabled:
                log_event("reasoning.search_blocked", mode=getattr(self.app_core, "get_mode", lambda: "secure")(), query=user_message)
                if self.app_core and hasattr(self.app_core, "show_toast"):
                    self.app_core.show_toast("Internet search is toggled off.")

            local_context_parts = [part for part in [file_context, system_context] if part]
            combined_local_context = "\n\n".join(local_context_parts)


            local_sources = (file_sources or []) + (system_sources or [])

            full_prompt = self._prepare_prompt(
                prompt=prompt,
                knowledge_context=knowledge_context,
                related_context=related_context,
                local_context=combined_local_context,
                web_sources=web_sources,
                reasoning_notes=reasoning_notes if deep_think else None,
            )
            context_items = self._build_context_metadata(knowledge_sources, web_sources, local_sources)
            result = self.app_core.ai_handler.query_with_retry(full_prompt)
        except Exception as exc:
            context_items = []
            web_sources = []
            result = {"success": False, "response": None, "error": str(exc)}
        self.after(0, lambda: self._finalize_query(result, context_items, web_sources, deep_think))

    def _finalize_query(self, result, context_items, web_sources, deep_think_used):
        self._set_busy(False)
        context_items = context_items or []
        web_sources = web_sources or []
        if result.get("success"):
            message = result.get("response", "") or ""
            if web_sources:
                message = self._append_sources(message, web_sources)
            badges = ["Reasoned"] if deep_think_used else []
            self.display_message(message, sender="ai", context=context_items, badges=badges)
        else:
            error = result.get("error") or "Unknown error"
            self.display_message(f"Error: {error}", sender="system")
        self.focus_entry()


    def display_message(self, message, sender="ai", context=None, badges=None):
        sender = "ai" if sender == "bot" else sender
        bubble_styles = {
            "user": ("UserBubble.TFrame", "UserBubble.TLabel"),
            "ai": ("AIBubble.TFrame", "AIBubble.TLabel"),
            "system": ("SystemBubble.TFrame", "SystemBubble.TLabel"),
        }
        frame_style, label_style = bubble_styles.get(sender, bubble_styles["ai"])
        badges = badges or []

        container = ttk.Frame(self.chat_frame, style="ChatFrame.TFrame")
        container.pack(
            fill="x",
            expand=True,
            anchor="e" if sender == "user" else "w",
            padx=(24, 24),
            pady=(4, 10),
        )
        container.columnconfigure(0, weight=1)

        bubble = ttk.Frame(container, padding=(14, 12), style=frame_style)
        bubble.grid(row=0, column=0, sticky="e" if sender == "user" else "w")

        badge_widgets = []
        if badges and sender == "ai":
            badge_frame = ttk.Frame(bubble, style=frame_style)
            badge_frame.pack(anchor="w", pady=(0, 6))
            for badge in badges:
                badge_label = ttk.Label(badge_frame, text=badge, style="Badge.Inverse.TLabel")
                badge_label.pack(side="left", padx=(0, 6))
                badge_widgets.append(badge_label)

        label = ttk.Label(
            bubble,
            text=message,
            wraplength=self._current_wrap,
            justify="left",
            style=label_style,
            anchor="w",
        )
        label.pack(fill="both", expand=True)

        context_meta = None
        if context and sender == "ai":
            context_meta = self._render_context_section(bubble, context, frame_style)

        self.message_labels.append(label)
        self.message_senders.append(sender)
        self.message_bubbles.append(bubble)
        self.message_context_sections.append(context_meta)
        self.message_badges.append(badge_widgets)

        self.chat_area.update_idletasks()
        self.chat_area.yview_moveto(1.0)
        self._update_header()

    def _render_context_section(self, parent, items, frame_style):
        container = ttk.Frame(parent, style=frame_style)
        container.pack(fill="x", expand=True, pady=(8, 0))

        toggle_frame = ttk.Frame(container, style=frame_style)
        toggle_frame.pack(fill="x", expand=True)

        details = ttk.Frame(container, style=frame_style)
        details_visible = {"value": False}
        labels = []

        wrap = max(self._current_wrap - 80, 240)
        for src in items:
            path = src.get("path") or ""
            preview = (src.get("preview") or "").strip()
            entry_type = src.get("type", "local")
            if entry_type == "web":
                domain = src.get("domain") or src.get("source") or ""
                if preview:
                    if domain:
                        label_text = f"{path} [{domain}]\n{preview}"
                    else:
                        label_text = f"{path}\n{preview}"
                else:
                    label_text = f"{path} [{domain}]" if domain else path
            else:
                label_text = f"{path}\n{preview}" if preview else path
            lbl = ttk.Label(details, text=label_text, style="Muted.TLabel", justify="left", wraplength=wrap)
            lbl.pack(anchor="w", pady=(2, 2))
            labels.append(lbl)

        def toggle():
            if details_visible["value"]:
                details.pack_forget()
                details_visible["value"] = False
                toggle_btn.configure(text="Context +")
            else:
                details.pack(fill="x", expand=True, pady=(6, 0))
                details_visible["value"] = True
                toggle_btn.configure(text="Context -")

        toggle_btn = ttk.Button(toggle_frame, text="Context +", style="TButton", command=toggle)
        toggle_btn.pack(anchor="w")

        metadata = {
            "container": container,
            "toggle": toggle_btn,
            "details": details,
            "labels": labels,
            "frame_style": frame_style,
        }
        return metadata

    def _on_model_selected(self, _=None):
        choice = self.model_var.get() if hasattr(self, 'model_var') else None
        if choice:
            self._update_model_badge(choice)
        if self.on_model_change and choice:
            self.on_model_change(choice)

    def _refresh_model_selector(self):
        if not hasattr(self, "model_selector"):
            return
        if not self.show_model_selector or len(self.available_models) <= 1:
            if self.model_selector.winfo_manager():
                self.model_selector.pack_forget()
        else:
            self.model_selector.configure(values=self.available_models)
            if not self.model_selector.winfo_manager():
                self.model_selector.pack(side="left", padx=(12, 0))

    def _update_model_badge(self, name: str | None):
        label = (name or "N/A").strip() or "N/A"
        self.status_badge.configure(text=label.upper())

    def set_model_selection(self, model_name: str, update_only: bool = False):
        model_name = (model_name or "").strip()
        if not model_name and self.available_models:
            model_name = self.available_models[0]
        if not model_name:
            self._update_model_badge("N/A")
            return
        lowered = model_name.lower()
        existing = next((name for name in self.available_models if name.lower() == lowered), None)
        if not existing and not update_only:
            self.available_models.append(model_name)
        if existing:
            model_name = existing
        if hasattr(self, "model_var"):
            self.model_var.set(model_name)
        if self.model_selector:
            self.model_selector.configure(values=self.available_models)
            self.model_selector.set(model_name)
        self.model = model_name
        self._update_model_badge(self.model)
        self._refresh_model_selector()

    def update_model_list(self, models, selected=None):
        self.available_models = []
        seen = set()
        for name in models or []:
            name = (name or "").strip()
            if not name:
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            self.available_models.append(name)

        chosen = (selected or "").strip()
        if chosen and chosen.lower() not in seen:
            self.available_models.insert(0, chosen)
            seen.add(chosen.lower())
        elif not chosen and self.available_models:
            chosen = self.available_models[0]

        if hasattr(self, "model_var"):
            self.model_var.set(chosen)
        if self.model_selector:
            self.model_selector.configure(values=self.available_models)
            if chosen:
                self.model_selector.set(chosen)

        if chosen:
            self.model = chosen
            self._update_model_badge(chosen)
        elif self.model:
            self._update_model_badge(self.model)
        else:
            self._update_model_badge("N/A")

        self._refresh_model_selector()

    def _set_busy(self, busy: bool):
        if busy == self._busy_state:
            return
        self._busy_state = busy
        if busy:
            self.spinner.grid()
            self.spinner.start(12)
            self.send_button.configure(state="disabled")
            self.search_button.configure(state="disabled")
            self.user_input.configure(state="disabled")
        else:
            self.spinner.stop()
            self.spinner.grid_remove()
            self.send_button.configure(state="normal")
            self.search_button.configure(state="normal")
            self.user_input.configure(state="normal")

    def refresh_messages(self):
        width = self.chat_area.winfo_width()
        max_w = min(max(width - 80, 300), 1100)
        for label in self.message_labels:
            label.configure(wraplength=max_w)
        wrap_context = max(max_w - 80, 240)
        for meta in self.message_context_sections:
            if not meta:
                continue
            for lbl in meta.get("labels", []):
                lbl.configure(wraplength=wrap_context)

    def _open_file_from_search(self, path):
        files_view = self.app_core.views["files"]
        files_view.load_file(path)
        self.app_core.show_files()

    def handle_file_search(self, query):
        query = (query or "").strip()
        if not query:
            return

        file_manager = self.app_core.views["files"].file_manager
        total_files = file_manager.index.get("_meta", {}).get("total_files", 0)
        test_path = Path(file_manager.index_file).parent / "index_test.json"
        has_test_index = test_path.exists()

        if total_files == 0 and not has_test_index:
            self.display_message(
                "No index data found. Please run Start Index or Test Index first.",
                "system",
            )
            return

        self.display_message(f"Searching for: {query}", "system")

        results = file_manager.search_index(query)
        if not results:
            self.display_message("No files found matching that query.", "system")
            return

        main_data = file_manager.index.get("files", {})
        test_data = {}
        if has_test_index:
            try:
                test_data = json.loads(test_path.read_text(encoding="utf-8")).get("files", {})
            except Exception:
                test_data = {}

        for entry in results:
            name, path = entry["name"], entry["path"]
            stored = main_data.get(path) or test_data.get(path) or {}
            summary = stored.get("summary", "No summary available.")
            self._render_search_result(name, path, summary)

        self.chat_area.update_idletasks()
        self.chat_area.yview_moveto(1.0)

    def _render_search_result(self, name, path, summary):
        container = ttk.Frame(self.chat_frame, style="ChatFrame.TFrame")
        container.pack(fill="x", expand=True, anchor="w", padx=(24, 24), pady=(2, 8))

        bubble = ttk.Frame(container, style="AIBubble.TFrame", padding=(14, 12))
        bubble.pack(anchor="w", fill="x")

        title = ttk.Label(bubble, text=name, style="AIBubble.TLabel", font=("Segoe UI", 10, "bold"), cursor="hand2")
        title.pack(anchor="w")

        meta = ttk.Label(bubble, text=path, style="AIBubble.TLabel", font=("Segoe UI", 9), cursor="hand2")
        meta.pack(anchor="w", pady=(2, 6))

        summary_label = ttk.Label(
            bubble,
            text=summary,
            style="AIBubble.TLabel",
            wraplength=self._current_wrap - 120,
            justify="left",
        )
        summary_label.pack(anchor="w")

        title.bind("<Button-1>", lambda _evt, p=path: self._open_file_from_search(p))
        meta.bind("<Button-1>", lambda _evt, p=path: self._open_file_from_search(p))
        ToolTip(title, summary, app_core=self.app_core)

    def get_state(self):
        return {
            "messages": [
                {
                    "message": label.cget("text"),
                    "sender": sender,
                    "badges": self.message_badges[idx] if idx < len(self.message_badges) else [],
                }
                for idx, (label, sender) in enumerate(zip(self.message_labels, self.message_senders))
            ],
            "file_context": self.file_context,
            "context_path": self.context_path,
        }

    def set_state(self, state):
        self.file_context = state.get("file_context")
        self.context_path = state.get("context_path")
        self.message_labels.clear()
        self.message_senders.clear()
        self.message_bubbles.clear()
        self.message_context_sections.clear()
        self.message_badges.clear()
        for child in self.chat_frame.winfo_children():
            child.destroy()
        for message in state.get("messages", []):
            self.display_message(
                message["message"],
                message["sender"],
                badges=message.get("badges"),
            )
        self._update_header()

    def apply_theme(self, theme_key):
        theme = THEMES[theme_key]
        ttk.Style()

        self.configure(style="ChatView.TFrame")
        self.header.configure(style="ChatHeader.TFrame")
        self.title_label.configure(style="ChatHeader.Title.TLabel")
        self.subtitle_label.configure(style="ChatHeader.Subtitle.TLabel")
        self.mode_badge.configure(style="StatusChip.TLabel")
        self.status_badge.configure(style="Badge.TLabel")

        self.chat_area.configure(bg=theme["chat_bg"])
        self.chat_frame.configure(style="ChatFrame.TFrame")
        self.entry_frame.configure(style="ChatEntry.TFrame")
        self.input_wrapper.configure(style="InputWrapper.TFrame")
        self.input_inner.configure(style="InputInner.TFrame")
        self.toggle_frame.configure(style="ChatEntry.TFrame")

        self._refresh_input_theme(theme)

        self.search_button.configure(style="TButton")
        self.send_button.configure(style="Primary.TButton")
        self.deep_think_toggle.configure(style="TCheckbutton")
        self.internet_toggle.configure(style="TCheckbutton")

        for bubble, label, sender in zip(self.message_bubbles, self.message_labels, self.message_senders):
            frame_style, label_style = {
                "user": ("UserBubble.TFrame", "UserBubble.TLabel"),
                "ai": ("AIBubble.TFrame", "AIBubble.TLabel"),
                "system": ("SystemBubble.TFrame", "SystemBubble.TLabel"),
            }[sender]
            bubble.configure(style=frame_style)
            label.configure(style=label_style)
        for badge_widgets in self.message_badges:
            for badge_label in badge_widgets:
                badge_label.configure(style="Badge.Inverse.TLabel")

    def _refresh_input_theme(self, theme=None):
        theme = theme or self._current_theme()
        self.user_input.configure(
            bg=theme["input_bg"],
            insertbackground=theme["text"],
        )
        if self._has_placeholder:
            self.user_input.configure(fg=theme.get("muted_text", theme["text"]))
        else:
            self.user_input.configure(fg=theme["text"])

    def focus_entry(self):
        if self._has_placeholder:
            self.user_input.mark_set("insert", "1.0")
        else:
            self.user_input.mark_set("insert", "end")
        self.user_input.focus_set()

    def _update_header(self):
        model_name = str(self.model).replace("_", " ").title()
        total = len(self.message_labels)
        if total == 0:
            detail = "No messages yet"
        elif total == 1:
            detail = "1 message so far"
        else:
            detail = f"{total} messages so far"
        self.subtitle_label.configure(text=f"{model_name} ready - {detail}")
        self._update_model_badge(self.model)

    def update_mode(self, mode, internet_available, internet_enabled, deep_think_enabled):
        self.mode = mode
        self.internet_available = bool(internet_available)
        self.internet_enabled = bool(internet_available and internet_enabled)
        self.deep_think_enabled = bool(deep_think_enabled)
        self._suspend_toggle_callbacks = True
        self.deep_think_var.set(self.deep_think_enabled)
        if self.internet_available:
            self.internet_search_var.set(self.internet_enabled)
            if not self.internet_toggle.winfo_ismapped():
                self.internet_toggle.grid(row=0, column=1, padx=(0, 12))
            self.internet_toggle.state(["!disabled"])
        else:
            self.internet_search_var.set(False)
            if self.internet_toggle.winfo_ismapped():
                self.internet_toggle.grid_remove()
            self.internet_toggle.state(["disabled"])
        self.mode_badge.configure(text=mode.title())
        self.deep_think_toggle.state(["!disabled"])
        self._suspend_toggle_callbacks = False
        self._update_header()

