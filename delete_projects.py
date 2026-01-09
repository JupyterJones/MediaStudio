#!/usr/bin/env python3
import os
import subprocess
from flask import Flask, request, render_template_string, redirect, url_for, send_from_directory
from icecream import ic

app = Flask(__name__)

BASE_DIR = os.getcwd()
PROJECT_DIR = os.path.join(BASE_DIR, "static", "projects")

# ensure directory exists
if not os.path.isdir(PROJECT_DIR):
    os.makedirs(PROJECT_DIR)
    ic("Created project directory:", PROJECT_DIR)


# ----------------------------- PARSE TIME -----------------------------
def parse_time(t):
    """
    Parse HH:MM:SS, MM:SS, or SS string to total seconds (int)
    """
    try:
        parts = t.strip().split(':')
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2:
            return parts[0]*60 + parts[1]
        elif len(parts) == 1:
            return parts[0]
    except Exception as e:
        ic("Time parse error:", e)
    return 0


# ----------------------------- TRIM FUNCTION -----------------------------
def trim_video(input_path, seconds):
    """
    Create a trimmed copy using originalname_trimmed.ext
    """
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_trimmed{ext}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-t", str(seconds),
        output_path
    ]

    ic("Running trim command:", cmd)

    try:
        subprocess.run(cmd, check=True)
        ic("Trim successful:", output_path)
        return output_path
    except Exception as e:
        ic("Trim error:", e)
        return None


# ----------------------------- TRIM ROUTE -----------------------------
@app.route("/trim/<filename>", methods=["POST"])
def trim_route(filename):
    time_input = request.form.get("trim_seconds", "").strip()
    seconds = parse_time(time_input)
    if seconds <= 0:
        ic("Invalid trim time:", time_input)
        return redirect(url_for("index"))

    input_path = os.path.join(PROJECT_DIR, filename)
    if not os.path.exists(input_path):
        ic("File missing:", input_path)
        return redirect(url_for("index"))

    trim_video(input_path, seconds)
    return redirect(url_for("index"))


# ----------------------------- HOME ROUTE -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    # Delete selected files
    if request.method == "POST" and "delete_items" in request.form:
        selected = request.form.getlist("delete_items")
        for fname in selected:
            fpath = os.path.join(PROJECT_DIR, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    ic("Deleted:", fpath)
                except Exception as e:
                    ic("Delete error:", e)
        return redirect(url_for("index"))

    # Scan directory
    all_files = os.listdir(PROJECT_DIR)
    images = []
    videos = []

    for f in all_files:
        fl = f.lower()
        if fl.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            images.append(f)
        elif fl.endswith((".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".m4a")):
            videos.append(f)

    images.sort()
    videos.sort()

    # Inline template
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Project Viewer</title>
        <style>
            body { font-family: Arial; background:#222; color:#eee; }
            h2 { margin-top: 30px; }
            .grid { display: flex; flex-wrap: wrap; gap: 20px; }
            .item { background:#333; padding:15px; border-radius:10px; width:220px; }
            img, video { width:100%; border-radius:8px; }
            .delete-box { margin-top:10px; }
            button { margin-top:20px; padding:10px 20px; font-size:16px; border:none; border-radius:8px; cursor:pointer; background:#ff5555; color:white; }
            button:hover { background:#ff2222; }
            .trim-form input { width:80px; padding:4px; margin-top:6px; }
            .trim-form button { background:#4499ff; margin-top:8px; }
            .trim-form button:hover { background:#1e7be5; }
        </style>
    </head>
    <body>
        <h1>Static Project Browser</h1>

        <form method="POST">

        <h2>Images</h2>
        <div class="grid">
            {% for img in images %}
            <div class="item">
                <img src="{{ url_for('project_file', filename=img) }}">
                <div class="delete-box">
                    <input type="checkbox" name="delete_items" value="{{ img }}"> Delete
                </div>
            </div>
            {% endfor %}
        </div>

        <h2>Videos</h2>
        <div class="grid">
            {% for vid in videos %}
            <div class="item">
                <video controls>
                    <source src="{{ url_for('project_file', filename=vid) }}">
                </video>

                <pre style="white-space: pre-wrap; word-break: break-word;">{{ vid }}</pre>

                <!-- TRIM FORM -->
                <form method="POST" action="{{ url_for('trim_route', filename=vid) }}" class="trim-form">
                    <label>Trim to (HH:MM:SS / MM:SS / seconds):</label><br>
                    <input type="text" name="trim_seconds" placeholder="00:10:00">
                    <button type="submit">Trim Copy</button>
                </form>

                <div class="delete-box">
                    <input type="checkbox" name="delete_items" value="{{ vid }}"> Delete
                </div>
            </div>
            {% endfor %}
        </div>

        <button type="submit">Delete Selected</button>
        </form>

    </body>
    </html>
    """

    return render_template_string(html, images=images, videos=videos)


# ----------------------------- SERVE FILES -----------------------------
@app.route("/static/projects/<path:filename>")
def project_file(filename):
    return send_from_directory(PROJECT_DIR, filename)


# ----------------------------- MAIN -----------------------------
if __name__ == "__main__":
    ic("Starting server, watching directory:", PROJECT_DIR)
    app.run(host="0.0.0.0", port=5300, debug=True)
