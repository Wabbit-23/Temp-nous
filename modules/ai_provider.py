"""AI provider abstraction layer.

Detects available AI backends and exposes a small uniform interface.

Supported providers (auto-detected):
- Ollama CLI (recommended when available)
- OpenAI via REST (when OPENAI_API_KEY is set)
- Local CLI named `llama` or `llama.cpp` (best-effort)

The module exposes `get_provider(preferred=None)` which returns an
instance implementing `is_available()` and `query(prompt, model, timeout)`.
If no provider is available, `get_provider()` returns None.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import json
import time
import urllib.request
import urllib.error
from typing import Optional


class BaseProvider:
    name: str = "base"

    def is_available(self) -> bool:
        return False

    def query(self, prompt: str, model: str = "mistral", timeout: int = 120) -> dict:
        raise NotImplementedError()


class OllamaProvider(BaseProvider):
    name = "ollama"

    def is_available(self) -> bool:
        return shutil.which("ollama") is not None

    def query(self, prompt: str, model: str = "mistral", timeout: int = 120) -> dict:
        try:
            proc = subprocess.run([
                "ollama", "run", model, prompt
            ], capture_output=True, text=True, timeout=timeout)
            return {"success": proc.returncode == 0, "response": proc.stdout.strip(), "error": None if proc.returncode == 0 else proc.stderr}
        except FileNotFoundError:
            return {"success": False, "response": None, "error": "ollama not found"}
        except subprocess.TimeoutExpired:
            return {"success": False, "response": None, "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"success": False, "response": None, "error": str(e)}


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def query(self, prompt: str, model: str = "gpt-3.5-turbo", timeout: int = 120) -> dict:
        if not self.api_key:
            return {"success": False, "response": None, "error": "OPENAI_API_KEY not set"}

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
        }

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_txt = resp.read().decode("utf-8")
                j = json.loads(res_txt)
                # Extract text from chat completion
                choices = j.get("choices") or []
                if choices:
                    content = choices[0].get("message", {}).get("content") or choices[0].get("text")
                    return {"success": True, "response": content, "error": None}
                return {"success": False, "response": None, "error": "No choices in response"}
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8")
                return {"success": False, "response": None, "error": f"HTTPError: {e.code} {body}"}
            except:
                return {"success": False, "response": None, "error": f"HTTPError: {e.code}"}
        except Exception as e:
            return {"success": False, "response": None, "error": str(e)}


class LocalCLIProvider(BaseProvider):
    name = "local_cli"

    def is_available(self) -> bool:
        # Check for common local CLI names
        for cmd in ("llama", "llama.cpp", "llamacpp"):
            if shutil.which(cmd):
                self.cmd = cmd
                return True
        return False

    def query(self, prompt: str, model: str = "unknown", timeout: int = 120) -> dict:
        # Best-effort: try calling the CLI with prompt as arg or stdin
        try:
            if hasattr(self, "cmd") and self.cmd:
                proc = subprocess.run([self.cmd, prompt], capture_output=True, text=True, timeout=timeout)
                return {"success": proc.returncode == 0, "response": proc.stdout.strip(), "error": None if proc.returncode == 0 else proc.stderr}
            return {"success": False, "response": None, "error": "No local CLI command found"}
        except subprocess.TimeoutExpired:
            return {"success": False, "response": None, "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"success": False, "response": None, "error": str(e)}


def get_provider(preferred: Optional[str] = None) -> Optional[BaseProvider]:
    """Return an instance of the preferred provider if available, otherwise the first available provider.

    preferred: optional string like 'ollama' or 'openai'.
    """
    candidates = []
    if preferred:
        p = preferred.lower()
        if p == "ollama":
            prov = OllamaProvider();
            if prov.is_available():
                return prov
        if p == "openai":
            prov = OpenAIProvider();
            if prov.is_available():
                return prov
        if p == "local":
            prov = LocalCLIProvider();
            if prov.is_available():
                return prov

    # Auto-detect order: Ollama -> OpenAI -> Local
    prov = OllamaProvider()
    if prov.is_available():
        return prov

    prov = OpenAIProvider()
    if prov.is_available():
        return prov

    prov = LocalCLIProvider()
    if prov.is_available():
        return prov

    return None


def list_available_providers() -> list:
    out = []
    for cls in (OllamaProvider, OpenAIProvider, LocalCLIProvider):
        p = cls()
        if p.is_available():
            out.append(p.name)
    return out
