# modules/ai_handler.py

import json
import subprocess
import time
import os
import platform
import urllib.request
import tkinter as tk
import re
from difflib import SequenceMatcher

from tkinter import messagebox
from pathlib import Path
from datetime import datetime

# ========== GPU Monitoring ==========

# Requires: pip install nvidia-ml-py3
try:
    from pynvml import (
        nvmlInit,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetTemperature,
        nvmlDeviceGetMemoryInfo,
        NVML_TEMPERATURE_GPU
    )
    nvmlInit()
    _GPU_HANDLE = nvmlDeviceGetHandleByIndex(0)

    def get_gpu_temp():
        return nvmlDeviceGetTemperature(_GPU_HANDLE, NVML_TEMPERATURE_GPU)

    def get_vram_usage_gb():
        mem = nvmlDeviceGetMemoryInfo(_GPU_HANDLE)
        return mem.used / (1024 ** 3)

except Exception:
    _GPU_HANDLE = None
    def get_gpu_temp(): return 0
    def get_vram_usage_gb(): return 0

MAX_SAFE_TEMP   = 80.0  # °C
MAX_VRAM_USAGE  = 7.5   # GiB
COOLDOWN_TEMP   = 70.0  # °C

# ========== Settings Persistence ==========

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"

def load_gpu_settings():
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_gpu_settings(settings: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

# ========== AI Handler ==========

class AIHandler:
    def __init__(self, model="mistral", app_core=None):
        self.model = model
        self.app_core = app_core

        settings = load_gpu_settings()
        self.max_vram_usage = settings.get("max_vram_usage", MAX_VRAM_USAGE)

        self.ensure_ollama_installed()
        # Install any bundled Ollama models so they're ready for use.
        self.install_ollama_plugins()
        self.ensure_model_pulled()

    def set_status(self, msg):
        if self.app_core and hasattr(self.app_core, "status_var"):
            self.app_core.status_var.set(msg)

    def install_ollama(self):
        if platform.system() == "Windows":
            url = "https://ollama.com/download/OllamaSetup.exe"
            local_installer = "OllamaSetup.exe"
            if not os.path.exists(local_installer):
                urllib.request.urlretrieve(url, local_installer)
            subprocess.Popen([local_installer], shell=True)
            root = tk.Tk(); root.withdraw()
            messagebox.showinfo("Ollama Installation", "Installing Ollama… please finish and restart.")
            self.set_status("Restart after installation.")
            raise SystemExit()
        else:
            raise RuntimeError("Auto-install only on Windows.")

    def ensure_ollama_installed(self):
        try:
            subprocess.run(["ollama", "--version"], check=True, capture_output=True)
        except FileNotFoundError:
            self.set_status("Ollama not found. Installing...")
            self.install_ollama()

    def install_ollama_plugins(self):
        """Install all Ollama models found in the repository.

        Models are expected to reside in an ``ollama`` directory at the
        repository root. Each model can either be represented by a directory
        containing a ``Modelfile`` or by a standalone ``<name>.modelfile``
        file. If a model already exists in the local Ollama installation it
        will be skipped.
        """
        plugin_dir = Path(__file__).parent.parent / "ollama"
        if not plugin_dir.exists():
            return

        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            installed = result.stdout
        except Exception as e:
            self.set_status("Error listing models.")
            print(f"Error: {e}")
            return

        modelfiles = set()
        modelfiles.update(plugin_dir.glob("*.modelfile"))
        modelfiles.update(plugin_dir.glob("*.Modelfile"))
        modelfiles.update(plugin_dir.glob("**/Modelfile"))
        modelfiles.update(plugin_dir.glob("**/*.modelfile"))

        for mf in modelfiles:
            if mf.is_dir():
                continue
            name = mf.stem if mf.name.lower() != "modelfile" else mf.parent.name
            if name in installed:
                continue
            try:
                self.set_status(f"Installing model '{name}'…")
                subprocess.run(["ollama", "create", name, "-f", str(mf)], check=True)
            except Exception as e:
                print(f"⚠️ Failed to install model {name}: {e}")

    def load_base_memory(self):
        if self.app_core and hasattr(self.app_core, "memory_store"):
            stored_base = self.app_core.memory_store.get_memory("base_policy")
            if stored_base:
                return stored_base
        path = Path(__file__).parent.parent / "data" / "base_memory.txt"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                return path.read_text(encoding="utf-8", errors="ignore").strip()
        return ""

    def _wait_for_gpu_safe(self):
        messagebox.showwarning(
            "GPU Protection",
            f"GPU temp or VRAM too high.\n\n"
            f"Temp: {get_gpu_temp():.1f}°C / {MAX_SAFE_TEMP}°C  •  "
            f"VRAM: {get_vram_usage_gb():.1f}GiB / {self.max_vram_usage}GiB\n\n"
            "Pausing until safe..."
        )
        while True:
            if get_gpu_temp() < COOLDOWN_TEMP and get_vram_usage_gb() < self.max_vram_usage:
                break
            time.sleep(5)
        messagebox.showinfo("GPU Protection", "Conditions normalized. Resuming.")

    def _check_and_throttle(self):
        if _GPU_HANDLE:
            if get_gpu_temp() >= MAX_SAFE_TEMP or get_vram_usage_gb() >= self.max_vram_usage:
                self._wait_for_gpu_safe()

    def update_gpu_limits(self, vram_gb: float = None):
        if vram_gb is not None:
            self.max_vram_usage = vram_gb
        save_gpu_settings({"max_vram_usage": self.max_vram_usage})

    def _interactions_path(self):
        return Path(__file__).parent.parent / "data" / "ai_interactions.json"

    def _read_interactions(self):
        path = self._interactions_path()
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            print("Warning: ai_interactions.json is not valid JSON; starting fresh.")
        except Exception as e:
            print(f"Warning: Failed to read interactions: {e}")
        return []

    def _write_interactions(self, data):
        path = self._interactions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def save_interaction(self, prompt, response):
        from uuid import uuid4

        interaction = {
            "id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "response": response
        }

        data = self._read_interactions()
        data.append(interaction)

        try:
            self._write_interactions(data)
        except Exception as e:
            print(f'[storage] Failed to save interaction: {e}')
        else:
            self._update_profile_from_message(prompt, response)

    def forget_by_keyword(self, keyword):
        path = self._interactions_path()
        data = self._read_interactions()

        if not data:
            return 0

        new_data = [
            entry for entry in data
            if keyword.lower() not in entry['prompt'].lower()
            and keyword.lower() not in entry['response'].lower()
        ]

        if len(new_data) == len(data):
            return 0

        try:
            self._write_interactions(new_data)
        except Exception as e:
            print(f"Error deleting interactions: {e}")
            return 0

        return len(data) - len(new_data)

    def load_recent_history(self, limit=5):
        data = self._read_interactions()
        return data[-limit:] if data else []

    def _tokenize(self, text: str) -> set[str]:
        if not text:
            return set()
        return {token for token in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(token) > 2}

    def _select_relevant_history(self, prompt: str, history) -> list:
        prompt_text = (prompt or "").strip()
        prompt_tokens = self._tokenize(prompt_text)
        if not prompt_tokens:
            return []
        relevant = []
        for entry in reversed(history):
            candidate = (entry.get('prompt') or '').strip()
            if not candidate:
                continue
            candidate_tokens = self._tokenize(candidate)
            if not candidate_tokens:
                continue
            token_overlap = prompt_tokens & candidate_tokens
            similarity = SequenceMatcher(None, prompt_text.lower(), candidate.lower()).ratio()
            if len(token_overlap) >= 2 or similarity >= 0.55:
                relevant.append(entry)
            if len(relevant) >= 2:
                break
        return list(reversed(relevant))

    def _build_profile_context(self, limit: int = 6) -> str:
        store = self._memory_store()
        if not store or not hasattr(store, "list_profile_facts"):
            return ""
        facts = store.list_profile_facts(limit=limit)
        if not facts:
            return ""
        lines = [f"- {fact}" for fact in facts]
        return "User Profile:\n" + "\n".join(lines)

    def _update_profile_from_message(self, prompt: str, response: str) -> None:
        store = self._memory_store()
        if not store or not hasattr(store, "add_profile_fact"):
            return
        text = (prompt or "").strip()
        if not text:
            return
        lower = text.lower()
        facts: set[str] = set()

        name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z\s'-]{1,40})", lower)
        if name_match:
            name = name_match.group(1).strip()
            if name:
                facts.add(f"Name: {name.title()}")

        like_match = re.search(r"\bi (?:really\s+)?like\s+([a-z0-9 ,'\-&]+)", lower)
        if like_match:
            item = like_match.group(1).split(".")[0].strip()
            if item:
                facts.add(f"Likes: {item}")

        birthday_match = re.search(r"\bmy birthday is\s+([a-z0-9 ,/]+)", lower)
        if birthday_match:
            date_text = birthday_match.group(1).split(".")[0].strip()
            if date_text:
                facts.add(f"Birthday: {date_text}")

        location_match = re.search(r"\bi am from\s+([a-zA-Z][a-zA-Z\s',-]{1,60})", lower)
        if location_match:
            location = location_match.group(1).strip()
            if location:
                facts.add(f"Location: {location.title()}")

        profession_match = re.search(r"\bi (?:work as|am a|am an)\s+([a-zA-Z][a-zA-Z\s'-]{1,60})", lower)
        if profession_match:
            role = profession_match.group(1).strip()
            if role:
                facts.add(f"Role: {role.title()}")

        for fact in facts:
            store.add_profile_fact(fact)


    def _memory_store(self):
        if self.app_core and hasattr(self.app_core, "memory_store"):
            return self.app_core.memory_store
        return None

    def _memory_enabled(self):
        if self.app_core and hasattr(self.app_core, "is_memory_enabled"):
            try:
                return bool(self.app_core.is_memory_enabled())
            except TypeError:
                return True
        return True

    def _build_memory_context(self, prompt: str, limit: int = 5) -> str:
        if not self._memory_enabled():
            return ""
        store = self._memory_store()
        if not store:
            return ""
        matches = store.search_memory(prompt, limit=limit)
        if not matches:
            return ""
        lines = [
            f"- {item['key']}: {item['value']}"
            for item in matches
            if item.get("value")
        ]
        if not lines:
            return ""
        return "Memory Context:\n" + "\n".join(lines)

    def ensure_model_pulled(self):
        if not self.model:
            return
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            if self.model not in result.stdout:
                self.set_status(f"Pulling model '{self.model}'…")
                subprocess.run(["ollama", "pull", self.model], check=True)
        except Exception as e:
            self.set_status("Error pulling model.")
            print(f"Error: {e}")

    def set_model(self, model_name: str):
        model_name = (model_name or "").strip()
        if not model_name:
            return
        if model_name == self.model:
            return
        self.model = model_name
        self.ensure_model_pulled()

    def query(self, prompt, timeout=120, save=True, memory=True):
        self._check_and_throttle()

        if memory:
            sections = []
            base_memory = self.load_base_memory()
            if base_memory:
                sections.append(base_memory)

            memory_context = self._build_memory_context(prompt)
            if memory_context:
                sections.append(memory_context)

            profile_context = self._build_profile_context()
            if profile_context:
                sections.append(profile_context)

        history = self.load_recent_history(limit=5)
        relevant_history = []
        if history:
            relevant_history = self._select_relevant_history(prompt, history)
            if relevant_history:
                history_lines = [
                    f"User previously said: {entry['prompt']}"
                    for entry in relevant_history
                ]
                sections.append("Conversation Context:\n" + "\n".join(history_lines))


        fallback_history = []
        if not relevant_history and history:
            fallback_history = history[-1:]


        if not sections and fallback_history:
            sections.append("Conversation Context:\n" + "\n".join(entry['prompt'] for entry in fallback_history))

        if sections:
            context = "\n\n".join(sections)
            full_prompt = f"{context}\n\nUser: {prompt}"
        else:
            full_prompt = prompt



        try:
            self.set_status("Querying AI…")
            result = subprocess.run(
                ["ollama", "run", self.model, full_prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace'
            )
            self.set_status("AI responded.")
            response = result.stdout.strip()

            if save:
                self.save_interaction(prompt, response)

            return {'success': True, 'response': response, 'error': None}

        except subprocess.TimeoutExpired:
            self.set_status("AI timed out.")
            return {'success': False, 'response': None, 'error': f"Timeout after {timeout}s"}
        except FileNotFoundError:
            self.set_status("Ollama not installed.")
            return {'success': False, 'response': None, 'error': "Ollama missing."}
        except Exception as e:
            self.set_status("AI failed.")
            return {'success': False, 'response': None, 'error': str(e)}

    def query_with_retry(self, prompt, max_retries=3, initial_timeout=60):
        for i in range(max_retries):
            res = self.query(prompt, initial_timeout * (i + 1))
            if res['success']:
                return res
            time.sleep(2)
        return res
