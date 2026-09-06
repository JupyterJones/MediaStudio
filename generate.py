#!/usr/bin/env python3
import os
import gc
import argparse
import json
from datetime import datetime
import torch
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler, LCMScheduler

MODELS=["/home/jack/Desktop/Comfy-UI/models/checkpoints/realisticLCMBYStable_v10.safetensors",
"/home/jack/Desktop/Comfy-UI/models/checkpoints/photonLCM_v10.safetensors",
"/home/jack/Desktop/Comfy-UI/models/checkpoints/animatediffLCMMotion_v10.ckpt",
"/home/jack/Desktop/Comfy-UI/models/checkpoints/dreamshaper_8LCM.safetensors"]

def main():
    parser = argparse.ArgumentParser(description="Offline Stable Diffusion CLI Generator (Corrected & Optimized)")
    parser.add_argument("--prompt", type=str, required=True, help="Positive prompt for generation")
    parser.add_argument("--negative_prompt", type=str, default=None, help="Negative prompt for generation")
    parser.add_argument("--mode", type=str, default="txt2img", choices=["txt2img", "img2img"], help="Pipeline mode: txt2img or img2img")
    parser.add_argument("--init_image", type=str, default=None, help="Path to initial image for img2img mode")
    parser.add_argument("--strength", type=float, default=0.65, help="Transformation strength for img2img (0.05 to 1.0)")
    parser.add_argument("--model", type=str, default=MODELS[0], help="Path to local .safetensors model file")
    parser.add_argument("--vae", type=str, default=None, help="Path to local VAE safetensors/ckpt file (optional)")
    parser.add_argument("--lora", type=str, default=None, help="Path to primary local LoRA safetensors file (optional)")
    parser.add_argument("--lora_scale", type=float, default=0.75, help="Scale/strength of primary LoRA")
    parser.add_argument("--lora2", type=str, default=None, help="Path to secondary local LoRA safetensors file (optional)")
    parser.add_argument("--lora2_scale", type=float, default=0.75, help="Scale/strength of secondary LoRA")
    parser.add_argument("--steps", type=int, default=5, help="Number of inference steps (Standard: 25-45, LCM: 4-8)")
    parser.add_argument("--guidance", type=float, default=1.2, help="CFG guidance scale (Standard: 7.0-9.0, LCM: 1.0-2.0)")
    parser.add_argument("--width", type=int, default=512, help="Image width (e.g., 512, 768, 1024)")
    parser.add_argument("--height", type=int, default=768, help="Image height (e.g., 512, 768, 1024)")
    parser.add_argument("--seed", type=int, default=12345, help="Random seed for deterministic generation")
    parser.add_argument("--output_dir", type=str, default="./static/novel_images", help="Directory to save generated images")
    parser.add_argument("--device", type=str, default="auto", help="Execution device: auto, cuda, mps, or cpu")
    parser.add_argument("--num_images", type=int, default=1, help="Number of images to generate (default: 1)")
    parser.add_argument("--threads", type=int, default=4, help="Limit CPU execution threads (default: 4)")
    args = parser.parse_args()

    # Configure CPU thread limits
    if args.threads > 0:
        torch.set_num_threads(args.threads)
        try:
            torch.set_num_interop_threads(args.threads)
        except Exception:
            pass
        os.environ["OMP_NUM_THREADS"] = str(args.threads)
        os.environ["MKL_NUM_THREADS"] = str(args.threads)
        os.environ["OPENBLAS_NUM_THREADS"] = str(args.threads)
        os.environ["NUMEXPR_NUM_THREADS"] = str(args.threads)
        print(f"[*] CPU thread limit set to: {args.threads}")

    # 1. Device selection
    if args.device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    else:
        device = args.device
    
    print(f"[*] Target generation device: {device.upper()}")
    if device == "cpu":
        print("[!] WARNING: Running on CPU")

    # 2. Determine if LCM or Standard model based on name/steps
    model_path = args.model
    if os.path.isdir(model_path):
        print(f"[*] Detected that --model is a directory: {model_path}")
        checkpoints = []
        for root, dirs, files in os.walk(model_path):
            for file in files:
                if file.endswith((".safetensors", ".ckpt")):
                    checkpoints.append(os.path.join(root, file))
        
        if not checkpoints:
            print(f"\n[CRITICAL ERROR] The directory '{model_path}' contains no '.safetensors' or '.ckpt' model files!")
            print("[*] Please download a Stable Diffusion checkpoint (e.g. v1-5-pruned-emaonly.safetensors) and place it there, or point to a specific file path.")
            return
        elif len(checkpoints) == 1:
            selected_model = checkpoints[0]
            print(f"[+] Found exactly one model in the directory: {os.path.basename(selected_model)}")
            print(f"[*] Automatically loading: {selected_model}")
            model_path = selected_model
        else:
            print(f"\n[CRITICAL ERROR] The path provided is a directory containing MULTIPLE checkpoints:")
            for cp in checkpoints:
                print(f"   - {cp}")
            print("\n[*] Please specify the exact file path to the model you want to run. For example:")
            print(f"    python generate.py --prompt \"{args.prompt}\" --model \"{checkpoints[0]}\"")
            return

    is_lcm_model = "lcm" in model_path.lower() or args.steps <= 12
    print(f"[*] Detected model type: {'Latent Consistency Model (LCM)' if is_lcm_model else 'Standard SD 1.5'}")

    # 3. Load single file pipeline (from_single_file)
    print(f"[*] Loading model checkpoint from: {model_path}")
    try:
        # Load pipeline in fp16 if running on CUDA for 2x speedup and 50% memory savings
        torch_dtype = torch.float16 if device == "cuda" else torch.float32
        
        pipe = StableDiffusionPipeline.from_single_file(
            model_path,
            torch_dtype=torch_dtype,
            use_safetensors=True,
            safety_checker=None,
            requires_safety_checker=False
        )
    except Exception as e:
        print(f"[ERROR] Failed to load model from path. Ensure the file exists and is valid. Details: {e}")
        return

    pipe = pipe.to(device)

    # 4. CPU / Memory Optimization
    if device == "cpu":
        pipe.enable_attention_slicing(1)
        if hasattr(pipe, "vae") and pipe.vae is not None:
            if hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
            if hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()
    elif device == "cuda":
        # Memory optimization for GPUs
        pipe.enable_xformers_memory_efficient_attention() if hasattr(pipe, "enable_xformers_memory_efficient_attention") else pipe.enable_attention_slicing()

    # 5. Fix Scheduler / Sampler configuration
    # Crucial step: Standard models and LCM models require fundamentally different schedulers!
    if is_lcm_model:
        print("[*] Setting scheduler to LCMScheduler (required for Latent Consistency)")
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    else:
        print("[*] Setting scheduler to DPMSolverMultistepScheduler (DPM++ 2M Karras equivalent for standard models)")
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            use_karras_sigmas=True
        )

    # 5.5. Load custom VAE if provided
    if args.vae and os.path.exists(args.vae):
        print(f"[*] Loading custom VAE from: {args.vae}")
        try:
            from diffusers import AutoencoderKL
            custom_vae = AutoencoderKL.from_single_file(args.vae, torch_dtype=torch_dtype)
            pipe.vae = custom_vae.to(device)
            if hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
            if hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()
            print(f"[+] Attached custom VAE: {os.path.basename(args.vae)}")
        except Exception as e:
            print(f"[!] Warning: Failed to load custom VAE ({e}). Continuing with model VAE.")

    # 6. Load and fuse LoRA weights if provided
    if args.lora and os.path.exists(args.lora):
        print(f"[*] Loading primary LoRA from: {args.lora} with scale {args.lora_scale}")
        try:
            pipe.load_lora_weights(args.lora, adapter_name="custom_lora1")
            pipe.fuse_lora(lora_scale=args.lora_scale)
        except Exception as e:
            print(f"[!] Warning: Failed to load LoRA 1 ({e})")
    elif args.lora:
        print(f"[!] Warning: Primary LoRA path '{args.lora}' not found. Skipping.")

    if args.lora2 and os.path.exists(args.lora2):
        print(f"[*] Loading secondary LoRA from: {args.lora2} with scale {args.lora2_scale}")
        try:
            pipe.load_lora_weights(args.lora2, adapter_name="custom_lora2")
            pipe.fuse_lora(lora_scale=args.lora2_scale)
        except Exception as e:
            print(f"[!] Warning: Failed to load LoRA 2 ({e})")
    elif args.lora2:
        print(f"[!] Warning: Secondary LoRA path '{args.lora2}' not found. Skipping.")

    # 7. Create output directories
    os.makedirs(args.output_dir, exist_ok=True)
    db_path = os.path.join(args.output_dir, "generations.json")

    # 8. Load generations history database
    db = {"next_image_id": 1, "runs": []}
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                db = json.load(f)
        except Exception:
            pass

    # 8.5 Setup Img2Img if requested
    init_image = None
    if args.mode == "img2img":
        if not args.init_image or not os.path.exists(args.init_image):
            print(f"[CRITICAL ERROR] Initial image '{args.init_image}' not found for img2img mode!")
            return
        try:
            from PIL import Image
            from diffusers import StableDiffusionImg2ImgPipeline
            init_image = Image.open(args.init_image).convert("RGB")
            init_image = init_image.resize((args.width, args.height), Image.Resampling.LANCZOS)
            pipe = StableDiffusionImg2ImgPipeline(**pipe.components)
            print(f"[*] Initialized Img2Img pipeline with source: {args.init_image} (strength: {args.strength})")
        except Exception as e:
            print(f"[ERROR] Failed to initialize img2img pipeline: {e}")
            return

    # 9. Perform Generation Loop
    current_seed = args.seed
    model_name = os.path.basename(model_path).replace(".", "_")

    for i in range(args.num_images):
        print(f"[*] Run {i+1}/{args.num_images} [{args.mode}]: Generating with seed={current_seed}, steps={args.steps}, CFG={args.guidance}")
        generator = torch.Generator(device=device).manual_seed(current_seed)
        
        gc.collect()
        with torch.inference_mode():
            try:
                if args.mode == "img2img":
                    output = pipe(
                        prompt=args.prompt,
                        negative_prompt=args.negative_prompt,
                        image=init_image,
                        strength=args.strength,
                        num_inference_steps=args.steps,
                        guidance_scale=args.guidance,
                        generator=generator
                    )
                else:
                    output = pipe(
                        prompt=args.prompt,
                        negative_prompt=args.negative_prompt,
                        num_inference_steps=args.steps,
                        guidance_scale=args.guidance,
                        width=args.width,
                        height=args.height,
                        generator=generator
                    )
                image = output.images[0]
            except Exception as e:
                print(f"[ERROR] Generation failed: {e}")
                break

        # Save image
        img_id = db.get("next_image_id", 1)
        filename = f"{model_name}_{args.mode}_img_{img_id:06d}.png"
        save_path = os.path.join(args.output_dir, filename)
        image.save(save_path)
        print(f"[+] Saved image to: {save_path}")

        # Record generation log
        db["runs"].append({
            "image_id": img_id,
            "file": filename,
            "timestamp": datetime.now().isoformat(),
            "mode": args.mode,
            "prompt": args.prompt,
            "negative_prompt": args.negative_prompt,
            "steps": args.steps,
            "guidance_scale": args.guidance,
            "seed": current_seed,
            "width": args.width,
            "height": args.height,
            "model": model_path,
            "strength": args.strength if args.mode == "img2img" else None,
            "init_image": args.init_image if args.mode == "img2img" else None
        })
        db["next_image_id"] = img_id + 1
        
        # Save updated database
        with open(db_path, "w") as f:
            json.dump(db, f, indent=4)

        current_seed += 1

    print(f"[*] DONE. All {args.num_images} image(s) processed and logged.")

if __name__ == "__main__":
    main()
