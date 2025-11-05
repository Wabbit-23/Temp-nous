import os
import sys
import threading
import argparse
from modules.file_manager import FileManager
from modules.ai_handler import AIHandler


class HeadlessNousApp:
    """
    Minimal headless runtime for Nous-AI.

    Features:
    - Build/update file index (uses FileManager)
    - CLI for simple operations: index, search, query, recent, exit
    - Uses AIHandler for queries; runs without any GUI dependencies
    """


    def __init__(self, include_paths=None, no_initial_index: bool = True):
        # File manager will spawn its summary workers automatically
        self.file_manager = FileManager(include_paths=include_paths)

        # AI handler with no GUI app_core; we provide minimal compatibility
        try:
            self.ai_handler = AIHandler(app_core=self)
        except Exception as e:
            print(f"⚠️ AI handler initialization failed: {e}")
            print("Continuing without AI functionality. Install 'ollama' to enable AI features.")
            self.ai_handler = None

        # Allow background indexing thread if desired
        self._index_lock = threading.Lock()
        self._no_initial_index = bool(no_initial_index)

    def set_status(self, msg):
        # Compatibility helper used by AIHandler (it calls app_core.status_var if present)
        print(f"[status] {msg}")

    def run_index(self):
        print("Starting metadata indexing (this may take a while)...")
        stats = self.file_manager.update_metadata_index()
        print(f"Indexing complete: {stats['new']} new/changed, {stats['total']} total files")
        return stats

    def start_index_background(self):
        # Start indexing in a background thread if not already running
        if hasattr(self, '_index_thread') and getattr(self, '_index_thread') and self._index_thread.is_alive():
            print("Indexing already in progress.")
            return
        t = threading.Thread(target=self.run_index, daemon=True)
        self._index_thread = t
        t.start()
        print("Indexing started in background.")

    def cmd_search(self, query):
        results = self.file_manager.search_index(query)
        if not results:
            print("No results")
            return
        for i, r in enumerate(results[:20], 1):
            print(f"{i}. {r.get('name')} — {r.get('path')} (score={r.get('score')})")

    def cmd_query(self, prompt):
        if not self.ai_handler:
            print("AI handler not available. Install 'ollama' and required dependencies to use this feature.")
            return
        print("Querying AI (this may take a bit)…")
        res = self.ai_handler.query(prompt)
        if res.get('success'):
            print("Response:\n")
            print(res.get('response') or "(no response)")
        else:
            print(f"Error: {res.get('error')}")

    def cmd_recent(self, limit=5):
        if not self.ai_handler:
            print("AI handler not available. No recent interactions.")
            return
        recent = self.ai_handler.load_recent_history(limit=limit)
        if not recent:
            print("No recent interactions.")
            return
        for entry in recent:
            print(f"- {entry.get('timestamp')}: {entry.get('prompt')[:80]} -> {entry.get('response')[:80]}")

    def run(self):
        print("Nous-AI (headless) — interactive mode")
        print("Commands: index | search <terms> | query <prompt> | recent [n] | exit | help")

        # Run an initial index in background to populate data unless disabled
        self._index_thread = None
        if not self._no_initial_index:
            self._index_thread = threading.Thread(target=self.run_index, daemon=True)
            self._index_thread.start()

        try:
            while True:
                raw = input("nous> ").strip()
                if not raw:
                    continue
                if raw in ("exit", "quit"):
                    print("Exiting.")
                    break
                if raw == "help":
                    print("Commands: index | search <terms> | query <prompt> | recent [n] | exit | help")
                    continue
                if raw == "index":
                    # Run indexing in background to avoid blocking when piped
                    self.start_index_background()
                    continue
                if raw.startswith("search "):
                    _, q = raw.split(" ", 1)
                    self.cmd_search(q)
                    continue
                if raw.startswith("query "):
                    _, p = raw.split(" ", 1)
                    self.cmd_query(p)
                    continue
                if raw.startswith("recent"):
                    parts = raw.split()
                    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
                    self.cmd_recent(limit=n)
                    continue

                print("Unknown command. Type 'help' for commands.")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")


def run_cli(argv=None):
    p = argparse.ArgumentParser(prog="nous-headless")
    p.add_argument("--paths", nargs="*", help="Paths to include for indexing")
    p.add_argument("--no-initial-index", action="store_true", help="Don't start indexing at startup")
    p.add_argument("--cmd", type=str, help="Run a single command non-interactively (e.g. 'index', 'search cats', 'query summarize this')")
    p.add_argument("--wait", action="store_true", help="When used with --cmd index, wait for indexing to finish before exiting")
    args = p.parse_args(argv)

    app = HeadlessNousApp(include_paths=args.paths if args.paths else None, no_initial_index=args.no_initial_index)

    # If a single command is provided, execute it and exit
    if args.cmd:
        cmd = args.cmd.strip()
        # index -> start background indexing
        if cmd == "index":
            app.start_index_background()
            if args.wait:
                if hasattr(app, '_index_thread') and app._index_thread:
                    app._index_thread.join()
            return

        if cmd.startswith("search "):
            _, q = cmd.split(" ", 1)
            app.cmd_search(q)
            return

        if cmd.startswith("query "):
            _, ptxt = cmd.split(" ", 1)
            app.cmd_query(ptxt)
            return

        if cmd.startswith("recent"):
            parts = cmd.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
            app.cmd_recent(limit=n)
            return

        # fallback: print unknown command
        print("Unknown --cmd value. Supported: index, search <q>, query <prompt>, recent [n]")
        return

    # Otherwise enter interactive mode
    app.run()


if __name__ == "__main__":
    run_cli()
