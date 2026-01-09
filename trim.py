#!/usr/bin/env python3

import os
import subprocess
import uuid
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from icecream import ic

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "results")
CLIP_DIR = os.path.join(BASE_DIR, "static", "clips")
FINAL_DIR = os.path.join(BASE_DIR, "static", "results")

for d in [UPLOAD_DIR, CLIP_DIR, FINAL_DIR]:
    os.makedirs(d, exist_ok=True)

# --------------------------------------------------
# HTML UI
# --------------------------------------------------

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>FFmpeg Video Trimmer</title>
<style>
body{background:#111;color:#eee;font-family:Arial;padding:20px}
.panel{background:#1c1c1c;padding:12px;border-radius:8px;margin-bottom:12px}
input,button{padding:6px;margin:4px}
video{width:300px;display:block;margin:6px 0}
.segment{border:1px solid #333;padding:6px;margin:6px 0}
</style>
</head>

<body>
<h2>LAN Video Trimmer & Stitcher</h2>

<div class="panel">
<h3>Upload Video</h3>
<input type="file" id="file">
<button onclick="upload()">Upload</button>
<div id="uploadStatus"></div>
</div>

<div class="panel">
<h3>Videos</h3>
<select id="videoSelect" onchange="loadVideo()"></select>
<video id="player" controls></video>
</div>

<div class="panel">
<h3>Trim Segments</h3>
Start <input id="start" placeholder="00:00:05">
End <input id="end" placeholder="00:00:10">
<button onclick="addSegment()">Add Segment</button>
<div id="segments"></div>
<button onclick="render()">Render Final Video</button>
</div>

<div class="panel">
<h3>Final Output</h3>
<video id="finalVideo" controls></video>
</div>

<script>
let segments = []

async function upload(){
    let f = document.getElementById("file").files[0]
    let fd = new FormData()
    fd.append("file", f)
    let r = await fetch("/upload",{method:"POST",body:fd})
    let j = await r.json()
    document.getElementById("uploadStatus").innerText = JSON.stringify(j)
    loadVideos()
}

async function loadVideos(){
    let r = await fetch("/videos")
    let j = await r.json()
    let sel = document.getElementById("videoSelect")
    sel.innerHTML = ""
    j.videos.forEach(v=>{
        let o=document.createElement("option")
        o.value=v
        o.text=v
        sel.appendChild(o)
    })
    loadVideo()
}

function loadVideo(){
    let v=document.getElementById("videoSelect").value
    if(!v)return
    document.getElementById("player").src="/static/results/"+v
}

function addSegment(){
    let s=document.getElementById("start").value
    let e=document.getElementById("end").value
    segments.push({start:s,end:e})
    renderSegments()
}

function renderSegments(){
    let d=document.getElementById("segments")
    d.innerHTML=""
    segments.forEach((s,i)=>{
        let div=document.createElement("div")
        div.className="segment"
        div.innerText = i+": "+s.start+" → "+s.end
        d.appendChild(div)
    })
}

async function render(){
    let v=document.getElementById("videoSelect").value
    let r=await fetch("/render",{method:"POST",headers:{'Content-Type':'application/json'},
        body:JSON.stringify({video:v,segments:segments})})
    let j=await r.json()
    document.getElementById("finalVideo").src="/static/final/"+j.output
}

loadVideos()
</script>
</body>
</html>
"""

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files["file"]
    fname = f.filename
    path = os.path.join(UPLOAD_DIR, fname)
    f.save(path)
    ic("Uploaded", path)
    return jsonify(ok=True, file=fname)

@app.route("/videos")
def videos():
    vids = sorted(os.listdir(UPLOAD_DIR))
    ic("Videos", vids)
    return jsonify(videos=vids)

@app.route("/render", methods=["POST"])
def render_video():
    data = request.json
    video = data["video"]
    segments = data["segments"]

    src = os.path.join(UPLOAD_DIR, video)
    clip_files = []

    for i, seg in enumerate(segments):
        clip_name = f"clip_{i}_{uuid.uuid4().hex}.mp4"
        clip_path = os.path.join(CLIP_DIR, clip_name)

        cmd = [
            "ffmpeg","-y",
            "-i",src,
            "-ss",seg["start"],
            "-to",seg["end"],
            "-c","copy",
            clip_path
        ]
        ic("TRIM", cmd)
        subprocess.run(cmd, check=True)
        clip_files.append(clip_path)

    list_file = os.path.join(CLIP_DIR, "concat.txt")
    with open(list_file,"w") as f:
        for c in clip_files:
            f.write(f"file '{c}'\n")

    out_name = f"final_{uuid.uuid4().hex}.mp4"
    out_path = os.path.join(FINAL_DIR, out_name)

    cmd = [
        "ffmpeg","-y",
        "-f","concat",
        "-safe","0",
        "-i",list_file,
        "-c","copy",
        out_path
    ]
    ic("CONCAT", cmd)
    subprocess.run(cmd, check=True)

    return jsonify(output=out_name)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    ic("Starting server")
    app.run(host="0.0.0.0", port=5800, debug=True)
