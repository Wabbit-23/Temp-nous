# modules/file_manager.py

import os
import json
import threading
import queue
from pathlib import Path
from datetime import datetime
import humanize
import concurrent.futures

UNREADABLE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg',
    '.mp4', '.mkv', '.avi', '.mov', '.webm',
    '.mp3', '.wav', '.flac', '.ogg'
}

class FileManager:
    def __init__(
        self,
        include_paths=None,
        exclude_paths=None,
        index_path: Path = None,
        summary_workers: int = None
    ):
        base     = Path(__file__).parent.parent
        data_dir = base / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)

        self.index_file = index_path or (data_dir / 'nous_file_index.json')
        self.executor   = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self._lock      = threading.Lock()

        home = Path.home()
        self.include_paths = include_paths or [
            str(home / "Documents"),
            str(home / "Downloads"),
            str(home / "Desktop"),
            str(home / "Projects"),
        ]
        self.exclude_paths = exclude_paths or [
            os.path.join(home.anchor, "Windows"),
            os.path.join(home.anchor, "Program Files"),
            os.path.join(home.anchor, "Program Files (x86)"),
            os.path.join(home.anchor, "ProgramData"),
            "/usr", "/bin", "/lib", "/etc", "/var",
            str(home / ".cache"),
            str(home / "AppData" / "Local" / "Programs"),
        ]

        self.index = {
            '_meta': {
                'version':      3,
                'created':      datetime.now().isoformat(),
                'last_updated': None,
                'total_files':  0
            },
            'files': {}
        }

        if self.index_file.exists():
            threading.Thread(target=self._load_existing_index, daemon=True).start()

        self._summary_queue = queue.Queue()
        self._ai             = None

        # Spawn summary workers
        cores = os.cpu_count() or 1
        workers = summary_workers or max(1, cores-1)
        for _ in range(workers):
            t = threading.Thread(target=self._summary_worker, daemon=True)
            t.start()

    def _load_existing_index(self):
        try:
            data = json.loads(self.index_file.read_text(encoding='utf-8'))
            with self._lock:
                self.index = data
        except:
            pass

    def _save_index(self):
        with self._lock:
            txt = json.dumps(self.index, indent=2)
        self.index_file.write_text(txt, encoding='utf-8')

    def should_index(self, p: Path) -> bool:
        s = str(p)
        return (
            any(s.startswith(base) for base in self.include_paths) and
            not any(s.startswith(exc) for exc in self.exclude_paths) and
            not p.name.startswith('.')
        )

    def count_files(self) -> int:
        c = 0
        for base in self.include_paths:
            for root, _, names in os.walk(base):
                rp = Path(root)
                if not self.should_index(rp): continue
                for name in names:
                    fp = rp / name
                    if self.should_index(fp):
                        c += 1
        return c

    def update_metadata_index(self):
        all_files = []
        for base in self.include_paths:
            for root, _, names in os.walk(base):
                rp = Path(root)
                if not self.should_index(rp): continue
                for name in names:
                    fp = rp / name
                    if self.should_index(fp):
                        all_files.append(fp)

        new_or_changed = []
        with self._lock:
            for fp in all_files:
                fid = str(fp.resolve())
                stat = fp.stat()
                entry = {
                    'path':     fid,
                    'name':     fp.name,
                    'size':     humanize.naturalsize(stat.st_size),
                    'mtime':    stat.st_mtime,
                    'readable': fp.suffix.lower() not in UNREADABLE_EXTENSIONS,
                    'summary':  self.index['files'].get(fid, {}).get('summary')
                }

                old = self.index['files'].get(fid)
                if old is None or old.get('mtime') != entry['mtime']:
                    new_or_changed.append((fid, entry))

                self.index['files'][fid] = entry

            self.index['_meta']['last_updated'] = datetime.now().isoformat()
            self.index['_meta']['total_files']  = len(self.index['files'])
            self._save_index()

        for fid, entry in new_or_changed:
            if entry['readable']:
                self._summary_queue.put(fid)

        return {'new': len(new_or_changed), 'total': len(self.index['files'])}

    def _generate_summary(self, path: str) -> str:
        if self._ai is None:
            from modules.ai_handler import AIHandler
            self._ai = AIHandler(app_core=None)

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                snippet = f.read()  # full content

            prompt = (
                "Please analyze the following text and provide a structured summary\n"
                "in this exact format:\n"
                "1 - Document type (e.g., report, poem)\n"
                "2 - Primary keyword\n"
                "3 - Additional keyword\n"
                "4 - Additional keyword\n"
                "5 - Additional keyword\n\n"
                f"{snippet}"
            )
            res = self._ai.query_with_retry(prompt)
            return res['response'].strip()
        except:
            return "Unreadable"

    def _summary_worker(self):
        while True:
            fid = self._summary_queue.get()
            with self._lock:
                entry = self.index['files'].get(fid)
                if entry is None or entry.get('summary'):
                    self._summary_queue.task_done()
                    continue

            summary = self._generate_summary(entry['path'])

            with self._lock:
                self.index['files'][fid]['summary'] = summary
                self.index['_meta']['last_updated']  = datetime.now().isoformat()
                self._save_index()

            self._summary_queue.task_done()

    def search_index(self, query: str, max_results=20):
        terms = query.lower().split()
        candidates = []

        with self._lock:
            candidates.extend(self.index['files'].values())

        test_file = self.index_file.parent / "index_test.json"
        if test_file.exists():
            try:
                test_data = json.loads(test_file.read_text(encoding='utf-8')).get('files', {})
                candidates.extend(test_data.values())
            except:
                pass

        results = []
        for entry in candidates:
            score = 0
            nm, pm, sm = entry['name'].lower(), entry['path'].lower(), (entry.get('summary') or "").lower()
            for t in terms:
                if t in sm: score += 5
                if t in nm: score += 2
                if t in pm: score += 1
            if score>0:
                results.append({**entry, 'score': score})

        results.sort(key=lambda x: -x['score'])
        return results[:max_results]
