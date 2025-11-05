# modules/ai_sorter.py
import os
import json
import shutil
from pathlib import Path
from modules.file_manager import FileManager
from modules.ai_handler import AIHandler

class AISorter:
    def __init__(self, app_core):
        self.app_core = app_core
        self.file_manager = FileManager()
        self.ai = AIHandler(app_core=app_core)
        self.summary_cache = {}
        self.sort_plan_path = Path("data/ai_sort_plan.json")
        self.sort_log_path = Path("data/ai_sort_log.json")

    def run_summary_phase(self):
        files = list(self.file_manager.file_index.get("files", {}).values())
        summaries = []

        for f in files:
            path = f["path"]
            if not f.get("readable", True):
                continue
            if not os.path.exists(path):
                continue

            summary = self.file_manager.load_file_summary(path)
            if not summary:
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as file:
                        content = file.read()[:2000]
                    prompt = f"Summarize this file and determine its main topic:\n\n{content}"
                    result = self.ai.query_with_retry(prompt)
                    summary = result["response"] if result["success"] else "Miscellaneous"
                    self.file_manager.save_file_summary(path, summary)
                except:
                    summary = "Unreadable"
            summaries.append((path, summary))
        return summaries

    def run_grouping_phase(self, summaries):
        prompt = "Group the following files by topic. Return a JSON dictionary where the keys are folder names and the values are lists of file paths.\n\n"
        for path, summary in summaries:
            name = os.path.basename(path)
            prompt += f"File: {name}\nSummary: {summary}\n\n"

        result = self.ai.query_with_retry(prompt)
        if not result["success"]:
            raise Exception("AI failed to generate sorting plan.")

        # Parse the AI response
        plan = json.loads(result["response"])
        with open(self.sort_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        return plan

    def sort_files(self, plan, base_folder="Organized by AI"):
        base_path = Path.home() / "Documents" / base_folder
        base_path.mkdir(parents=True, exist_ok=True)
        move_log = []

        for folder, files in plan.items():
            folder_path = base_path / folder
            folder_path.mkdir(exist_ok=True)

            for file_path in files:
                src = Path(file_path)
                if not src.exists():
                    continue
                dest = folder_path / src.name
                if dest.exists():
                    # Avoid overwriting
                    dest = folder_path / f"{src.stem}_copy{src.suffix}"
                shutil.move(str(src), str(dest))
                move_log.append({"from": str(src), "to": str(dest)})

        with open(self.sort_log_path, "w", encoding="utf-8") as f:
            json.dump(move_log, f, indent=2)
        return move_log
