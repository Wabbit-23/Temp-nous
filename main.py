import tkinter as tk
from app_core import NousApp
import os

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Nous AI – Demo")

    # Optional icon
    icon_path = os.path.join("assets", "icon.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception as e:
            print(f"Failed to load icon: {e}")

    app = NousApp(root)
    app.run()
