import PyInstaller.__main__

PyInstaller.__main__.run([
    'main.py',
    '--name=SmartSortDemo',
    '--onefile',
    '--noconfirm',
    '--windowed',  # use '--console' instead if you want to see terminal output
    '--add-data=data;data',
    '--add-data=views;views',
    '--add-data=modules;modules',
    '--icon=assets/icon.ico'  # optional, if you add an icon
])
