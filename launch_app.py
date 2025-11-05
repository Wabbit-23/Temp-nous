#!/usr/bin/env python3

import os
import subprocess
import sys


def main() -> None:
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(repo_dir, "main.py")
    try:
        subprocess.run([sys.executable, main_script], cwd=repo_dir, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to launch Nous AI: {exc}")


if __name__ == "__main__":
    main()