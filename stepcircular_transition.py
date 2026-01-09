#!/var/www/Make_Art/flask_env/bin/python
import numpy as np
from moviepy.editor import ImageSequenceClip, ImageClip, VideoFileClip, ColorClip, CompositeVideoClip, AudioFileClip
from PIL import Image, ImageDraw
import os
import glob
import random
import shutil
import uuid
from icecream import ic

def create_circular_mask(size, radius):
    """
    Creates a circular mask of the given radius.
    The mask is a white circle (revealing) on a black background (hiding).
    """
    img = Image.new("L", size, 0)  # Black background
    draw = ImageDraw.Draw(img)
    center = (size[0] // 2, size[1] // 2)  # Center of the image
    draw.ellipse((center[0] - radius, center[1] - radius, 
                  center[0] + radius, center[1] + radius), fill=255)  # White circle
    return np.array(img)

def apply_mask(top_img, bottom_img, mask):
    """
    Combines the top and bottom images using the mask.
    The mask should be a 3D array where the last dimension is 1, to match image dimensions.
    """
    mask_rgb = np.repeat(mask, 3, axis=2)  # Expand mask to 3 channels
    return np.where(mask_rgb == 255, bottom_img, top_img)

def create_transition(duration=2, fps=24):
    """
    Creates a transition video where the top image gradually reveals the next image in the list.
    Saves the resulting video as 'circular_mask_transition.mp4'.
    
    :param duration: Duration of each transition.
    :param fps: Frames per second.
    """
    frames = []
    num_frames = duration * fps  # Total number of frames
    image_list = glob.glob('static/vid_resources/*.jpg') + glob.glob('static/vid_resources/*.png')  # Get all jpg and png files
    #print(image_list)
    image_list.sort(key=os.path.getmtime, reverse=False)  # Sort by modification time, oldest first
    image_list=image_list[:5]
    print(image_list)    
    if len(image_list) < 2:
        ic(len(image_list))
        print("Not enough images in the directory to create a transition.")
        return

    # Loop through all pairs of images in the directory
    for i in range(len(image_list) - 1):
        top_img_path = image_list[i]
        bottom_img_path = image_list[i + 1]

        # Load images
        top_img = Image.open(top_img_path).convert("RGB")  # Ensure 3-channel RGB
        bottom_img = Image.open(bottom_img_path).convert("RGB")  # Ensure 3-channel RGB

        # Resize both images to the same size as the mask
        target_size = (512, 768)  # (width, height)
        top_img = np.array(top_img.resize(target_size))
        bottom_img = np.array(bottom_img.resize(target_size))

        # Use height for the maximum radius to continue the transition until the entire image is covered
        max_radius = target_size[1] // 2  # Based on image height, to cover the entire height

        # Create frames for the transition from top_img to bottom_img
        for j in range(num_frames):
            radius = int((j / num_frames) * max_radius)
            mask = create_circular_mask(target_size, radius)
            mask = np.expand_dims(mask, axis=2)  # Expand to 3D for broadcasting
            frame = apply_mask(top_img, bottom_img, mask)
            frames.append(ImageClip(frame, duration=1 / fps))

    # Create and save the video
    video_clip = ImageSequenceClip([np.array(f.img) for f in frames], fps=fps)
    video_clip.write_videofile('static/temp_exp/circular_mask_transition.mp4', codec='libx264')

def add_title(video_path, hex_color="#A52A2A"):
    hex_color = random.choice(["#A52A2A", "#ad1f1f", "#16765c", "#7a4111", "#9b1050", "#8e215d", "#2656ca"])
    directory_path = "tempp"
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"Directory '{directory_path}' created.")
    else:
        print(f"Directory '{directory_path}' already exists.") 

    # Load the video file and title image
    video_clip = VideoFileClip(video_path)
    width, height = video_clip.size
    title_image_path = "static/assets/circular_512x768.png"

    padded_size = (width + 50, height + 50)
    x_position = (padded_size[0] - width) / 2
    y_position = (padded_size[1] - height) / 2

    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    rgb_tuple = (r, g, b)

    blue_background = ColorClip(padded_size, color=rgb_tuple)
    padded_video_clip = CompositeVideoClip([blue_background, video_clip.set_position((x_position, y_position))])
    padded_video_clip = padded_video_clip.set_duration(video_clip.duration)

    title_image = ImageClip(title_image_path)
    title_image = title_image.set_duration(video_clip.duration)
    title_image = title_image.set_position((0, -5)).resize(padded_video_clip.size)

    composite_clip = CompositeVideoClip([padded_video_clip, title_image]).set_duration(video_clip.duration)

    mp3_files = glob.glob("static/music/*.mp3")
    random.shuffle(mp3_files)
    mp_music = random.choice(mp3_files)
    music_clip = AudioFileClip(mp_music).set_duration(video_clip.duration)
    fade_duration = 1.0
    music_clip = music_clip.audio_fadein(fade_duration).audio_fadeout(fade_duration)
    composite_clip = composite_clip.set_audio(music_clip)

    uid = uuid.uuid4().hex
    output_path = 'static/temp_exp/circular_mask_transitionX.mp4'
    composite_clip.write_videofile(output_path)
    mp4_file = f"static/vids/Ready_Post_{uid}.mp4"
    shutil.copyfile(output_path, mp4_file)     
    print(mp4_file)
    return output_path

# Example usage
create_transition(duration=2, fps=24)
video_path = 'static/temp_exp/circular_mask_transition.mp4'
add_title(video_path, hex_color="#A52A2A")
