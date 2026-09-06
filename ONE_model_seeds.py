import os
import gc
import signal
import argparse
from random import randint
import torch
from icecream import ic
from diffusers import StableDiffusionPipeline, LCMScheduler

def exit_gracefully(signum, frame):
    print("\n[*] Ctrl+C / termination signal received. Exiting cleanly...")
    os._exit(0)

signal.signal(signal.SIGINT, exit_gracefully)
signal.signal(signal.SIGTERM, exit_gracefully)
torch.set_num_threads(4)

MODELS = [
    "comiccraftLCM_beta4.safetensors",
    "dreamshaper_8LCM.safetensors",
    "possibleLoveliesLCM_v10.safetensors",
    "cyberphotonlcm_v10.safetensors",
    "semirealxLCM_v10.safetensors",
    "coldfleshRealisticLCM_v10.safetensors",
    "silversRealmixLCM_v10.safetensors",
    "xenoxtcLCMEditionArtToon_v10.safetensors",
    "truevisionLCM77_v10.safetensors",
    "delusionsLCM_v20.safetensors",
    "frtMixmodelLCM_realisticV10.safetensors",
    "epicphotogasmLCM_ultimatefidelity.safetensors",
    "realmodelbase02LCM_v10.safetensors",
    "cyberrealisticLCM_cyberrealistic42.safetensors",
    "realisticLCMBYStable_v10.safetensors",
    "xenogasmLCMEditionSFWNSFW_lcmV5.safetensors",
    "photonLCM_v10.safetensors",
    "linierflowLCM_v10.safetensors",
    "madnessLCMV1_v10.safetensors",
    "kitschInSyncAndABagOfChips_v2.safetensors",
    "xxmix9realistic_v40+LCM_LoRA_Weights_SD15.fp16.safetensors",
    "angraRealflexLCMV6_v10.safetensors"
]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_DIR = "/home/jack/Desktop/Comfy-UI/models/checkpoints"
DEFAULT_LORA = "/home/jack/Desktop/Comfy-UI/models/loras/more_details.safetensors"
DEFAULT_MODEL = "delusionsLCM_v20.safetensors"

def resolve_model(m):
    """Resolve a model name, stem, or index to an exact filename in MODELS or CHECKPOINT_DIR."""
    m_clean = m.strip()
    if m_clean.isdigit():
        idx = int(m_clean)
        if 0 <= idx < len(MODELS):
            return MODELS[idx]
        return None

    # Exact match in MODELS
    if m_clean in MODELS:
        return m_clean

    # Match with .safetensors appended
    if f"{m_clean}.safetensors" in MODELS:
        return f"{m_clean}.safetensors"

    # Case-insensitive match in MODELS (with or without extension)
    m_lower = m_clean.lower()
    for cand in MODELS:
        cand_stem = cand.replace(".safetensors", "")
        if m_lower in (cand.lower(), cand_stem.lower()):
            return cand

    # Direct file check in CHECKPOINT_DIR
    if os.path.exists(os.path.join(CHECKPOINT_DIR, m_clean)):
        return m_clean
    if os.path.exists(os.path.join(CHECKPOINT_DIR, f"{m_clean}.safetensors")):
        return f"{m_clean}.safetensors"

    return None

def encode_chunked(tokenizer, text_encoder, prompt, max_chunks=None):
    raw_tokens = tokenizer(prompt, padding=False, truncation=False, return_tensors="pt").input_ids[0]
    bos = raw_tokens[0:1]
    eos = raw_tokens[-1:]
    content = raw_tokens[1:-1]
    
    if len(raw_tokens) <= 77 and (max_chunks is None or max_chunks == 1):
        inputs = tokenizer(prompt, padding="max_length", max_length=77, truncation=True, return_tensors="pt")
        with torch.no_grad():
            return text_encoder(inputs.input_ids.to(text_encoder.device))[0]
            
    chunks = [content[i:i+75] for i in range(0, max(1, len(content)), 75)]
    embs = []
    for c in chunks:
        t = torch.cat([bos, c, eos])
        pad_len = 77 - len(t)
        if pad_len > 0:
            t = torch.nn.functional.pad(t, (0, pad_len), value=tokenizer.pad_token_id)
        with torch.no_grad():
            embs.append(text_encoder(t.unsqueeze(0).to(text_encoder.device))[0])
            
    return torch.cat(embs, dim=1)

def encode_matching_negative(tokenizer, text_encoder, negative_prompt, target_chunks):
    neg_tokens = tokenizer(negative_prompt, padding=False, truncation=False, return_tensors="pt").input_ids[0]
    bos, eos = neg_tokens[0:1], neg_tokens[-1:]
    content = neg_tokens[1:-1]

    embs = []
    for i in range(target_chunks):
        c = content[:75] if len(content) else content
        t = torch.cat([bos, c, eos])
        pad_len = 77 - len(t)
        if pad_len > 0:
            t = torch.nn.functional.pad(t, (0, pad_len), value=tokenizer.pad_token_id)
        with torch.no_grad():
            embs.append(text_encoder(t.unsqueeze(0).to(text_encoder.device))[0])
    return torch.cat(embs, dim=1)

def generate_seeds_for_model(
    model_filename,
    prompt,
    base_seed=123456,
    num_seeds=30,
    num_steps=4,
    guidance_scale=1.5,
    lora_path=None,
    lora_scale=0.25,
    vae_path=None,
    output_base_dir=BASE_DIR
):
    model_path = os.path.join(CHECKPOINT_DIR, model_filename)
    if not os.path.exists(model_path):
        print(f"[!] Warning: Model file not found: {model_path}, skipping.")
        return
    uid = str(randint(111111,999999))
    # Output directory matches the model name (without .safetensors)
    model_dir_name = model_filename.replace(".safetensors", "")
    output_dir = os.path.join("static","novel_images", model_dir_name)
    os.makedirs(output_dir, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    print(f"\n" + "=" * 60)
    print(f"[*] Loading model: {model_filename} on {device} ({torch_dtype})")
    print(f"[*] Destination directory: {output_dir}")
    print(f"=" * 60)

    pipe_kwargs = {
        "torch_dtype": torch_dtype,
        "use_safetensors": True,
    }

    # Optional custom VAE
    if vae_path and os.path.exists(vae_path):
        from diffusers import AutoencoderKL
        print(f"[*] Loading custom VAE from {vae_path}...")
        pipe_kwargs["vae"] = AutoencoderKL.from_single_file(vae_path, torch_dtype=torch_dtype)

    pipe = StableDiffusionPipeline.from_single_file(model_path, **pipe_kwargs)
    pipe.to(device)

    # Swap in LCM scheduler
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)

    # CPU / Memory Optimization
    if device == "cpu":
        pipe.enable_attention_slicing(1)
        if hasattr(pipe, "vae") and pipe.vae is not None:
            if hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
            if hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()

    # Optional LoRA (e.g. more_details.safetensors)
    if lora_path and os.path.exists(lora_path) and lora_scale > 0:
        print(f"[*] Applying LoRA {os.path.basename(lora_path)} with scale {lora_scale}...")
        pipe.load_lora_weights(lora_path)
        pipe.fuse_lora(lora_scale=lora_scale)

    tokenizer = pipe.tokenizer
    text_encoder = pipe.text_encoder

    emb = encode_chunked(tokenizer, text_encoder, prompt)
    num_chunks = emb.shape[1] // 77
    neg_emb = encode_matching_negative(tokenizer, text_encoder, "blurry, low quality, deformed", num_chunks)

    print(f"[*] Generating {num_seeds} seeds (base seed: {base_seed}, steps: {num_steps}, cfg: {guidance_scale})...")

    try:
        for inc in range(num_seeds):
            current_seed = base_seed + inc
            ic(f"[{inc + 1}/{num_seeds}] Processing model: {model_filename} | Seed: {current_seed}")
            try:
                generator = torch.Generator(device=device).manual_seed(current_seed)
                image = pipe(
                    prompt_embeds=emb,
                    negative_prompt_embeds=neg_emb,
                    generator=generator,
                    width=512,
                    height=768,
                    num_inference_steps=num_steps,
                    guidance_scale=guidance_scale,
                ).images[0]

                output_path = os.path.join("static", "novel_images", f"{current_seed}_{model_filename}_output.png")
                image.save(output_path)
                print(f"[+] Successfully saved output: {output_path}")
            except Exception as e:
                print(f"[!] Error generating seed {current_seed} for {model_filename}: {e}")
    finally:
        del pipe
        del tokenizer
        del text_encoder
        del emb
        del neg_emb
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

def generate_with_model(
    prompt,
    seed,
    model_filename,
    output_dir=None,
    num_steps=4,
    guidance_scale=1.5,
    lora_path=None,
    lora_scale=0.25,
    vae_path=None
):
    if output_dir is None:
        model_dir_name = model_filename.replace(".safetensors", "")
        output_dir = os.path.join(BASE_DIR, model_dir_name)
    os.makedirs(output_dir, exist_ok=True)

    model_path = os.path.join(CHECKPOINT_DIR, model_filename)
    if not os.path.exists(model_path):
        print(f"[!] Warning: Model file not found: {model_path}, skipping.")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    pipe_kwargs = {
        "torch_dtype": torch_dtype,
        "use_safetensors": True,
    }

    if vae_path and os.path.exists(vae_path):
        from diffusers import AutoencoderKL
        pipe_kwargs["vae"] = AutoencoderKL.from_single_file(vae_path, torch_dtype=torch_dtype)

    pipe = StableDiffusionPipeline.from_single_file(model_path, **pipe_kwargs)
    pipe.to(device)
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)

    # CPU / Memory Optimization
    if device == "cpu":
        pipe.enable_attention_slicing(1)
        if hasattr(pipe, "vae") and pipe.vae is not None:
            if hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
            if hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()

    if lora_path and os.path.exists(lora_path) and lora_scale > 0:
        pipe.load_lora_weights(lora_path)
        pipe.fuse_lora(lora_scale=lora_scale)

    tokenizer = pipe.tokenizer
    text_encoder = pipe.text_encoder

    emb = encode_chunked(tokenizer, text_encoder, prompt)
    num_chunks = emb.shape[1] // 77
    neg_emb = encode_matching_negative(tokenizer, text_encoder, "blurry, low quality, deformed", num_chunks)

    generator = torch.Generator(device=device).manual_seed(seed)
    image = pipe(
        prompt_embeds=emb,
        negative_prompt_embeds=neg_emb,
        generator=generator,
        width=512,
        height=768,
        num_inference_steps=num_steps,
        guidance_scale=guidance_scale,
    ).images[0]

    output_path = os.path.join(output_dir, f"{seed}_{model_filename}_output.png")
    image.save(output_path)
    print(f"[+] Successfully saved output: {output_path}")

    del pipe
    del tokenizer
    del text_encoder
    del emb
    del neg_emb
    del image
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

def main():
    parser = argparse.ArgumentParser(description="Run SD1.5 LCM inference across seeds for model(s).")
    parser.add_argument("-p", "--prompt", default=(
        "Extremely old colossal carved stone statues, the size of giant trees"
        "depicting farm animals such as ducks, roosters, chickens, and horses."
        "Their surfaces are cracked and weathered, with peeling dark green and burnt orange paint"
        "The stone statues of animals resemble an ancient dystopian zoo overgrown with weeds and dead vines"
    ), help="Prompt text")
    parser.add_argument("-s", "--seed", type=int, default=123456, help="Random starting seed (default: 123456)")
    parser.add_argument("-n", "--num-seeds", type=int, default=30, help="Number of seeds to generate (default: 30)")
    parser.add_argument("--steps", type=int, default=4, help="Inference steps (default: 4)")
    parser.add_argument("--guidance", type=float, default=1.5, help="Guidance scale (default: 1.5)")
    parser.add_argument("-m", "--model", default="delusionsLCM_v20", help="Specific model name, index, or comma-separated list (default: delusionsLCM_v20)")
    parser.add_argument("--lora", default=DEFAULT_LORA, help="Path to LoRA file (default: more_details.safetensors)")
    parser.add_argument("--lora-scale", type=float, default=0.25, help="LoRA scale weight (0 to disable, default: 0.25)")
    parser.add_argument("--vae", default=None, help="Optional path to custom VAE (default: uses model's built-in VAE)")
    args = parser.parse_args()

    target_models = []
    if args.model:
        if args.model.strip().lower() == "all":
            target_models = list(MODELS)
        else:
            for item in args.model.split(","):
                resolved = resolve_model(item)
                if resolved and resolved not in target_models:
                    target_models.append(resolved)
                elif not resolved:
                    print(f"[!] Warning: No model matched '{item.strip()}'")
    else:
        target_models = [DEFAULT_MODEL]

    if not target_models:
        print(f"[!] No valid models matched selection: {args.model}")
        return

    total = len(target_models)
    print(f"[*] Starting seed batch generation for {total} model(s)...")

    for idx, model_filename in enumerate(target_models, 1):
        print(f"\n[*] [{idx}/{total}] Processing model: {model_filename}")
        try:
            generate_seeds_for_model(
                model_filename=model_filename,
                prompt=args.prompt,
                base_seed=args.seed,
                num_seeds=args.num_seeds,
                num_steps=args.steps,
                guidance_scale=args.guidance,
                lora_path=args.lora,
                lora_scale=args.lora_scale,
                vae_path=args.vae,
                output_base_dir=BASE_DIR
            )
        except Exception as e:
            print(f"[!] Error processing model {model_filename}: {e}")

    print("\n[✓] All requested models and seeds processed successfully!")

if __name__ == '__main__':
    main()