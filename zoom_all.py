#!/home/jack/miniconda3/envs/PY39/bin/python
# make_zoom
import glob
import random
from PIL import Image, ImageFilter
import PIL
import os
import logging
import subprocess
import uuid
import shutil
from moviepy.editor import *

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Get the current directory where the script is run
current_dir = os.getcwd()

def process_and_size_images(source_dir):
    # Step 1: Ensure the originals directory exists
    originals_dir = os.path.join(source_dir, 'originals')
    os.makedirs(originals_dir, exist_ok=True)

    # Step 2: Iterate over images in the source directory
    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        logging.debug(f"Attempting to process file: {filepath}")
        if not os.path.isfile(filepath):
            logging.debug(f"Skipping directory or non-file: {filepath}")
            continue
        if not filename.lower().endswith(('png', 'jpg', 'jpeg')):
            logging.warning(f"Skipping non-image file: {filename}")
            continue

        # Step 3: Move the original to the originals directory (if not already there)
        original_path = os.path.join(originals_dir, filename)
        if not os.path.exists(original_path):
            os.rename(filepath, original_path)

        try:
            # Step 4: Open the image
            with Image.open(original_path) as img:
                original_width, original_height = img.size
                logging.debug(f"Opened image: {filename}, Size: {original_width}x{original_height}")

                # Check if the image is already 512x768
                if original_width == 512 and original_height == 768:
                    # Save it back as a JPG if necessary
                    new_filename = os.path.splitext(filename)[0] + ".jpg"
                    new_filepath = os.path.join(source_dir, new_filename)
                    img.convert("RGB").save(new_filepath, format='JPEG', quality=95)
                    continue

                # Step 5: Create a blurred background
                blurred = img.resize((512, 768)).filter(ImageFilter.GaussianBlur(15))

                # Step 6: Resize the original image while maintaining aspect ratio
                aspect_ratio = original_width / original_height
                if aspect_ratio > (512 / 768):  # Wider than the target aspect
                    new_width = 512
                    new_height = int(512 / aspect_ratio)
                else:  # Taller than the target aspect
                    new_height = 768
                    new_width = int(768 * aspect_ratio)
                
                resized_original = img.resize((new_width, new_height), Image.LANCZOS)

                # Step 7: Overlay the resized original onto the blurred background
                offset_x = (512 - new_width) // 2
                offset_y = (768 - new_height) // 2
                blurred.paste(resized_original, (offset_x, offset_y))

                # Step 8: Save the resulting image as a JPG
                new_filename = os.path.splitext(filename)[0] + ".jpg"  # Change extension to .jpg
                new_filepath = os.path.join(source_dir, new_filename)
                blurred.convert("RGB").save(new_filepath, format='JPEG', quality=95)
        except PIL.UnidentifiedImageError as e:
            logging.error(f"Failed to open image {filename}: {e}")
            continue  # Skip this file and move on to the next

def prep_homedirectory():
    # Get the current directory where the script is being executed
    image_directory = os.path.join(current_dir, 'temp_images_exp')
    logging.info(f"Image directory: {image_directory}")

    # Create or clear the image directory
    if os.path.exists(image_directory):
        shutil.rmtree(image_directory)
        logging.info(f"Cleared contents of image directory: {image_directory}")
    os.makedirs(image_directory, exist_ok=True)
    logging.info(f"Created image directory: {image_directory}")

    # Process images and copy them to temp_images_exp after resizing
    process_and_size_images(current_dir)  # Ensure images are processed and sized

    # Copy processed images from the originals folder to temp_images_exp
    originals_dir = os.path.join(current_dir, 'originals')
    for f in os.listdir(originals_dir):
        if f.endswith(('.jpg', '.jpeg', '.png')):
            logging.info(f"Copying {f} to {image_directory}")
            shutil.copy(os.path.join(originals_dir, f), image_directory)

    # Get and shuffle the list of image files in the directory
    image_files = [f for f in os.listdir(image_directory) if f.endswith(('.jpg', '.jpeg', '.png'))]
    random.shuffle(image_files)
    logging.info(f"Shuffled image files: {image_files}")

    return image_files

def image_dir_to_zoom():
    selected_directory = os.path.join(current_dir, 'temp_images_exp')
    os.makedirs(selected_directory, exist_ok=True)
    
    try:
        # Updated glob pattern to handle file extensions better
        image_files = glob.glob(f'{selected_directory}/*.[jp][pn][g]')
        if not image_files:
            logging.error("No images found in the directory.")
            return

        SIZE = Image.open(random.choice(image_files)).size
    except Exception as e:
        logging.error(f"Error opening image: {e}")
        return

    output_video = 'generated_video_exp.mp4'
    frame_rate = 60
    zoom_increment = 0.0005
    zoom_duration = 300
    #width, height = 512, 768
    width,height = SIZE

    ffmpeg_cmd = (
        f"ffmpeg -hide_banner -pattern_type glob -framerate {frame_rate} "
        f"-i '{selected_directory}/*.jpg' "
        f"-vf \"scale=8000:-1,zoompan=z='min(zoom+{zoom_increment},1.5)':x='iw/2':y='ih/2-4000':d={zoom_duration}:s={width}x{height},crop={width}:{height}:0:256\" "
        f"-c:v libx264 -pix_fmt yuv420p -r {frame_rate} -s {width}x{height} -y {output_video}"
    )

    logging.info(f"FFmpeg command: {ffmpeg_cmd}")
    try:
        subprocess.run(ffmpeg_cmd, shell=True, check=True)
        logging.info("Video generated successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"FFmpeg command failed: {e}")
        return None

    video_name = str(uuid.uuid4()) + '_zoom_exp.mp4'
    if not os.path.exists('assets_exp'):
        os.makedirs('assets_exp')    
    shutil.copy(output_video, os.path.join('assets_exp', video_name))

    output_vid = os.path.join('assets_exp', video_name)
    logging.info(f"Generated video: {output_vid}")
    return output_vid

def add_title_image(video_path, hex_color="#A52A2A"):
    directory_path = os.path.join(current_dir, "temp_exp")
    os.makedirs(directory_path, exist_ok=True)
    
    video_clip = VideoFileClip(video_path)
    width, height = video_clip.size
    padded_size = (width + 40, height + 40)
    x_position = (padded_size[0] - width) / 2
    y_position = (padded_size[1] - height) / 2

    # Convert hex to RGB and create background clip
    rgb_tuple = tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))
    background_clip = ColorClip(padded_size, color=rgb_tuple)
    padded_video_clip = CompositeVideoClip([background_clip, video_clip.set_position((x_position, y_position))]).set_duration(video_clip.duration)

    # Load and resize title image
    title_image = ImageClip("/home/jack/Desktop/MediaStudio/static/assets/zoom_images.png").resize(padded_video_clip.size).set_position((0, -5)).set_duration(video_clip.duration)
    composite_clip = CompositeVideoClip([padded_video_clip, title_image]).set_duration(video_clip.duration)

    # Load background music
    mp3_files = glob.glob("/home/jack/Desktop/HDD500/collections/music_long/*.mp3")
    random.shuffle(mp3_files)
    music_clip = AudioFileClip(random.choice(mp3_files)).audio_fadein(0.5).audio_fadeout(0.5).set_duration(video_clip.duration)
    final_clip = composite_clip.set_audio(music_clip)
    
    final_output_path = os.path.join(directory_path, 'final_output.mp4')
    final_clip.write_videofile(final_output_path, codec="libx264", audio_codec="aac")
    logging.info(f"Final video saved as {final_output_path}")
    return final_output_path

def create_zoom_video():
    image_files = prep_homedirectory()
    logging.info("Starting the zoom video generation.")
    video_path = image_dir_to_zoom()
    if video_path:
        final_video = add_title_image(video_path)
        logging.info(f"Final video generated at: {final_video}")
    else:
        logging.error("Video generation failed.")

create_zoom_video()
