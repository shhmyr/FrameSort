# frameSorter

### Local photo and video organizer

## 📌 Overview

frameSorter is a desktop tool for reviewing a local media library and organizing photos and videos into person-named folders. It runs on your computer; files are not uploaded.

## 🎯 Features

- Browse a gallery and preview photos or video poster frames.
- Create destination folders while sorting.
- Assign items with keyboard shortcuts and continue to the next unsorted item.
- Search filenames, review folder counts, and undo the latest move.
- Confirm moves by default. Existing files are never overwritten; name conflicts receive a numbered filename.
- Move a selected photo or video to the computer's Trash after confirmation; restore it from Trash if needed.
- Open videos in the computer's default video player.
- Display the custom frameSorter logo in the splash and app window.

## ⚙️ Setup

Install Python 3.10 or newer, then open a terminal in this folder:

```sh
python -m venv .venv
```

Activate the environment:

```sh
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies and launch:

```sh
python -m pip install -r requirements.txt
python app.py
```

Choose the folder containing your unsorted media. frameSorter remembers it for the next launch.

## ⌨️ Shortcuts

| Key | Action |
| --- | --- |
| ← / → | Browse items |
| ↑ / ↓ | Move through gallery rows |
| 1–9 | Move to one of the first nine folders |
| 0 | Return the item to the library root |
| Delete | Ask before moving the selected item to Trash |
| Ctrl+Z | Undo the latest move |
| Ctrl+F | Search filenames |
| Ctrl+O | Choose another library |

## 🧭 Library layout

The selected folder is the library root. frameSorter scans media directly inside it and inside each immediate child folder; deeper nested folders are not scanned. Each child folder appears as a destination category. For the best results, choose a folder arranged this way:

```text
My Photos/
├── unsorted-photo.jpg
├── unsorted-video.mp4
├── Person A/
└── Person B/
```

## 🎞️ Preview support

Photos preview in the app. Install `ffmpeg` to show video poster frames; **Play video** opens the original file in the default player. For optional HEIC/HEIF image support, install `pillow-heif` with `python -m pip install pillow-heif`.

## 🛡️ File handling

frameSorter does not permanently delete files. The **Move to Trash** action asks first and uses the computer's recoverable Trash. Organizing moves stay inside the selected library, avoid replacing files with the same name, and can be undone during the current session.
