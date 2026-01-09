#!/usr/bin/env python3
from flask import Flask, request, render_template_string, redirect, url_for, flash, session
import os
import uuid
from PIL import Image
from icecream import ic
import subprocess

# -------------------------------------------------
# CONFIG
# -------------------------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STITCH_DIR = os.path.join(BASE_DIR, "static", "stitch")
RESULT_DIR = os.path.join(BASE_DIR, "static", "results")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

IMAGE_WIDTH   = 768
IMAGE_HEIGHT  = 512
TARGET_HEIGHT = 768
VIEWPORT_WIDTH = 512
FEATHER_PX    = 100
REQUIRED      = 4

TITLE_IMAGE_PATH = "/home/jack/Desktop/HDD500/DOCKER/static/assets/transtalks.png"
SCROLL_DURATION = 150  # seconds for full scroll

os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "stitch_secret_key"

# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def list_images():
    files = sorted([
        f for f in os.listdir(STITCH_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ])
    ic("Available images:", files)
    return files

def feather_mask(width, height, fade_left=False, fade_right=False):
    mask = Image.new("L", (width, height), 255)
    px = mask.load()
    for x in range(width):
        alpha = 255
        if fade_left and x < FEATHER_PX:
            alpha = int(255 * (x / FEATHER_PX))
        if fade_right and x > width - FEATHER_PX:
            alpha = int(255 * ((width - x) / FEATHER_PX))
        for y in range(height):
            px[x, y] = alpha
    return mask

def stitch_images(ordered_files):
    ic("Final stitch order:", ordered_files)
    images = [Image.open(os.path.join(STITCH_DIR, f)).convert("RGBA") for f in ordered_files]

    stitched_width = (IMAGE_WIDTH * REQUIRED) - (FEATHER_PX * (REQUIRED - 1))
    stitched_height = IMAGE_HEIGHT
    stitched = Image.new("RGBA", (stitched_width, stitched_height), (0, 0, 0, 0))

    x_offset = 0
    for idx, img in enumerate(images):
        fade_left = idx != 0
        fade_right = idx != REQUIRED - 1
        ic(f"Image {idx+1}", "fade_left:", fade_left, "fade_right:", fade_right)
        mask = feather_mask(IMAGE_WIDTH, IMAGE_HEIGHT, fade_left, fade_right)
        img.putalpha(mask)
        stitched.alpha_composite(img, (x_offset, 0))
        ic("Pasted at x =", x_offset)
        x_offset += IMAGE_WIDTH - FEATHER_PX

    # Scale to target height
    scale = TARGET_HEIGHT / stitched_height
    new_width = int(stitched_width * scale)
    ic("Scaling", stitched.size, "->", (new_width, TARGET_HEIGHT))
    stitched = stitched.resize((new_width, TARGET_HEIGHT), resample=Image.LANCZOS)

    stitched_filename = f"stitched_{uuid.uuid4().hex}.png"
    stitched_path = os.path.join(TEMP_DIR, stitched_filename)
    stitched.convert("RGB").save(stitched_path)
    ic("Saved stitched PNG:", stitched_path)

    # ----------------------------
    # FFmpeg scroll + frame overlay
    # ----------------------------
    uid = uuid.uuid4().hex
    final_mp4 = os.path.join(RESULT_DIR, f"Ready_Post_{uid}.mp4")

    ffmpeg_cmd = f"""
    ffmpeg -hide_banner -loop 1 -i "{stitched_path}" -loop 1 -i "{TITLE_IMAGE_PATH}" \
    -filter_complex "[0:v]scale={new_width}:{TARGET_HEIGHT},scroll=horizontal=0.0001,crop={VIEWPORT_WIDTH}:{TARGET_HEIGHT}:0:0[bg]; \
    [bg][1:v]overlay=0:-5:format=auto:shortest=1" \
    -t {SCROLL_DURATION} -pix_fmt yuv420p -y "{final_mp4}"
    """

    ic("Running FFmpeg:", ffmpeg_cmd)
    subprocess.run(ffmpeg_cmd, shell=True, check=True)
    ic("Saved final video:", final_mp4)

    return os.path.basename(final_mp4)

# -------------------------------------------------
# ROUTES
# -------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    images = list_images()
    if request.method == "POST":
        positions = {}
        for img in images:
            pos = request.form.get(img)
            if pos and pos != "skip":
                positions[int(pos)] = img

        ic("Submitted positions:", positions)
        if len(positions) != REQUIRED or set(positions.keys()) != {1, 2, 3, 4}:
            flash("You must assign exactly one image to positions 1–4.")
            return redirect(url_for("index"))

        ordered = [positions[i] for i in range(1, 5)]
        result_file = stitch_images(ordered)
        session["last_result"] = result_file
        return redirect(url_for("result"))

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>Visual Stitcher</title>
        <style>
            body { background:#111; color:#eee; font-family:sans-serif; }
            .grid { display:flex; flex-wrap:wrap; gap:15px; }
            .card { border:1px solid #333; padding:10px; width:220px; }
            img { width:200px; display:block; margin-bottom:8px; }
            select { width:100%; padding:5px; }
            button { margin-top:20px; padding:10px 20px; }
        </style>
    </head>
    <body>
        <h1>Preview Images & Choose Positions</h1>
        <form method="post">
            <div class="grid">
                {% for img in images %}
                <div class="card">
                    <img src="{{ url_for('static', filename='stitch/' + img) }}">
                    <select name="{{ img }}">
                        <option value="skip">skip</option>
                        <option value="1">position 1 (left)</option>
                        <option value="2">position 2</option>
                        <option value="3">position 3</option>
                        <option value="4">position 4 (right)</option>
                    </select>
                </div>
                {% endfor %}
            </div>
            <button type="submit">Stitch Selected Images</button>
        </form>
    </body>
    </html>
    """, images=images)

@app.route("/result")
def result():
    filename = session.get("last_result")
    if not filename:
        return render_template_string("""
        <html>
        <body style="background:#111;color:#eee;font-family:sans-serif">
            <h1>No result available</h1>
            <a href="/">Go back</a>
        </body>
        </html>
        """)
    return render_template_string("""
    <!doctype html>
    <html>
    <body style="background:#111;color:#eee;font-family:sans-serif">
        <h1>Stitched Result (512x768 Scrolling with Frame)</h1>
        <video src="{{ url_for('static', filename='results/' + filename) }}" controls autoplay loop></video>
        <br><br>
        <a href="/">Back</a>
    </body>
    </html>
    """, filename=filename)

# -------------------------------------------------
# MAIN
# -------------------------------------------------

if __name__ == "__main__":
    ic("Starting Stitch App")
    app.run(debug=True, host="0.0.0.0", port=5001)
