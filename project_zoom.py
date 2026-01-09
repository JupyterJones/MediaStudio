#!/home/jack/miniconda3/envs/PY39/bin/python

# make_zoom.py
import glob
import random
from PIL import Image, ImageFilter
import PIL
import os
import subprocess
import uuid
import shutil
from moviepy.editor import *
from icecream import ic

current_dir = os.getcwd()

def process_and_size_images(source_dir):
    originals_dir = os.path.join(source_dir, 'originals')
    os.makedirs(originals_dir, exist_ok=True)

    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        ic(f"Checking file: {filepath}")

        if not os.path.isfile(filepath):
            ic(f"Skipping: not a file -> {filepath}")
            continue

        if not filename.lower().endswith(('png', 'jpg', 'jpeg')):
            ic(f"Skipping non-image: {filename}")
            continue

        original_path = os.path.join(originals_dir, filename)
        if not os.path.exists(original_path):
            os.rename(filepath, original_path)

        try:
            with Image.open(original_path) as img:
                w, h = img.size
                ic(f"Opened image {filename} size {w}x{h}")

                if w == 512 and h == 768:
                    new_filename = os.path.splitext(filename)[0] + ".jpg"
                    new_filepath = os.path.join(source_dir, new_filename)
                    img.convert("RGB").save(new_filepath, format='JPEG', quality=95)
                    continue

                blurred = img.resize((512, 768)).filter(ImageFilter.GaussianBlur(15))

                aspect = w / h
                if aspect > (512 / 768):
                    new_w = 512
                    new_h = int(512 / aspect)
                else:
                    new_h = 768
                    new_w = int(768 * aspect)

                resized = img.resize((new_w, new_h), Image.LANCZOS)
                off_x = (512 - new_w) // 2
                off_y = (768 - new_h) // 2
                blurred.paste(resized, (off_x, off_y))

                new_filename = os.path.splitext(filename)[0] + ".jpg"
                new_filepath = os.path.join(source_dir, new_filename)
                blurred.convert("RGB").save(new_filepath, format='JPEG', quality=95)

        except PIL.UnidentifiedImageError as e:
            ic(f"Failed to open {filename}: {e}")
            continue

def prep_homedirectory():
    image_directory = os.path.join(current_dir, 'temp_images_exp')
    ic(f"Image directory -> {image_directory}")

    if os.path.exists(image_directory):
        shutil.rmtree(image_directory)
        ic(f"Cleared: {image_directory}")

    os.makedirs(image_directory, exist_ok=True)
    ic(f"Created: {image_directory}")

    process_and_size_images(current_dir)

    originals_dir = os.path.join(current_dir, 'originals')
    for f in os.listdir(originals_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            ic(f"Copying {f} → {image_directory}")
            shutil.copy(os.path.join(originals_dir, f), image_directory)

    files = [f for f in os.listdir(image_directory) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    random.shuffle(files)
    ic(f"Shuffled files: {files}")

    return files

def image_dir_to_zoom(required_duration_seconds):
    selected_directory = os.path.join(current_dir, 'temp_images_exp')
    os.makedirs(selected_directory, exist_ok=True)

    image_files = glob.glob(f'{selected_directory}/*.jpg')
    if not image_files:
        ic("No images found")
        return None

    output_video = 'generated_video_exp.mp4'
    frame_rate = 60
    width, height = 512, 768

    frame_count = int(frame_rate * required_duration_seconds)

    ffmpeg_cmd = (
        f"ffmpeg -y -hide_banner "
        f"-pattern_type glob -framerate 1 "
        f"-i '{selected_directory}/*.jpg' "
        f"-vf \"scale=8000:-1,zoompan=z='min(zoom+0.0005,1.5)':x='iw/2':y='ih/2-4000':"
        f"d={frame_count}:s={width}x{height},crop={width}:{height}:0:256\" "
        f"-c:v libx264 -pix_fmt yuv420p -r {frame_rate} "
        f"{output_video}"
    )

    ic(ffmpeg_cmd)

    try:
        subprocess.run(ffmpeg_cmd, shell=True, check=True)
        ic("Video generated successfully.")
    except subprocess.CalledProcessError as e:
        ic(f"FFmpeg failed: {e}")
        return None

    video_name = str(uuid.uuid4()) + '_zoom_exp.mp4'
    if not os.path.exists('assets_exp'):
        os.makedirs('assets_exp')

    shutil.copy(output_video, os.path.join('assets_exp', video_name))
    return os.path.join('assets_exp', video_name)

def add_title_image(video_path, audio_path, hex_color="#A52A2A"):
    directory_path = os.path.join(current_dir, "temp_exp")
    os.makedirs(directory_path, exist_ok=True)

    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)

    width, height = video_clip.size

    if video_clip.duration < audio_clip.duration:
        last_frame = video_clip.get_frame(video_clip.duration - 0.1)
        last_img = ImageClip(last_frame).set_duration(audio_clip.duration - video_clip.duration)
        video_clip = concatenate_videoclips([video_clip, last_img])

    rgb_tuple = tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))
    padded_size = (width + 40, height + 40)
    x_pos = (padded_size[0] - width) / 2
    y_pos = (padded_size[1] - height) / 2

    background = ColorClip(padded_size, color=rgb_tuple)
    padded = CompositeVideoClip([background, video_clip.set_position((x_pos, y_pos))]).set_duration(video_clip.duration)

    title_image = ImageClip("static/assets/zoom_images.png").resize(padded.size).set_position((0, -5)).set_duration(padded.duration)
    composite = CompositeVideoClip([padded, title_image]).set_duration(padded.duration)

    final = composite.set_audio(audio_clip)

    final_output_path = os.path.join(directory_path, 'final_output.mp4')
    final.write_videofile(final_output_path, codec="libx264", audio_codec="aac")

    ic(f"Saved final: {final_output_path}")
    return final_output_path

def create_zoom_video():
    image_files = prep_homedirectory()

    narration_audio = "narration.mp3"          # ← your TTS output here
    audio_clip = AudioFileClip(narration_audio)

    required_duration_seconds = audio_clip.duration

    ic(f"Required duration: {required_duration_seconds} seconds")

    video_path = image_dir_to_zoom(required_duration_seconds)

    if video_path:
        final_video = add_title_image(video_path, narration_audio)
        ic(f"Final video: {final_video}")
    else:
        ic("Video generation failed.")

create_zoom_video()
