import os
import gc
import signal
import argparse
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
DEFAULT_MODEL = "xenogasmLCMEditionSFWNSFW_lcmV5.safetensors"

DEFAULT_PROMPT = (
    "A highly detailed  full body image of a Beautiful Female alien cyborg art and illustration by theo el, in the style of balanced symmetry, light orange and cyan, detailed facial features, manticore, organic forms, muted tones, meticulous portraiture, complex patterns --ar 1:2 --stylize 750 --v 6"
)

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

def run_cfg_sweep(
    model_filename,
    prompt,
    seed=123456,
    num_images=50,
    cfg_start=1.0,
    cfg_step=0.04,
    num_steps=4,
    lora_path=DEFAULT_LORA,
    lora_scale=0.25,
    vae_path=None,
    output_base_dir=BASE_DIR
):
    model_path = os.path.join(CHECKPOINT_DIR, model_filename)
    if not os.path.exists(model_path):
        print(f"[!] Error: Model file not found: {model_path}")
        return

    #model_stem = model_filename.replace(".safetensors", "")
    output_dir = "static/novel_images"
    os.makedirs(output_dir, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    print("\n" + "=" * 65)
    print(f"[*] Loading model: {model_filename} on {device} ({torch_dtype})")
    print(f"[*] Destination directory: {output_dir}")
    print(f"[*] Fixed Seed: {seed}")
    print(f"[*] CFG Sweep: {num_images} images from {cfg_start:.2f} (step +{cfg_step:.2f})")
    print("=" * 65)

    pipe_kwargs = {
        "torch_dtype": torch_dtype,
        "use_safetensors": True,
    }

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

    # Apply optional LoRA
    if lora_path and os.path.exists(lora_path) and lora_scale > 0:
        print(f"[*] Applying LoRA {os.path.basename(lora_path)} with scale {lora_scale}...")
        pipe.load_lora_weights(lora_path)
        pipe.fuse_lora(lora_scale=lora_scale)

    tokenizer = pipe.tokenizer
    text_encoder = pipe.text_encoder

    # Pre-encode embeddings once for all CFG steps
    emb = encode_chunked(tokenizer, text_encoder, prompt)
    num_chunks = emb.shape[1] // 77
    neg_emb = encode_matching_negative(tokenizer, text_encoder, "blurry, low quality, deformed", num_chunks)

    try:
        for i in range(num_images):
            current_cfg = round(cfg_start + (i * cfg_step), 4)
            cfg_str = f"{current_cfg:.2f}".replace(".", "-")
            # Example filename: modelname_seed_1-04.png
            DIR = "static/novel_images/"
            filename = f"{seed}_{cfg_str}.png"
            output_path = os.path.join(output_dir, filename)

            ic(f"[{i + 1}/{num_images}] Generating image: {filename} | CFG: {current_cfg:.2f} | Seed: {seed}")

            try:
                # Same fixed seed for each generation produces identical starting noise
                generator = torch.Generator(device=device).manual_seed(seed)
                image = pipe(
                    prompt_embeds=emb,
                    negative_prompt_embeds=neg_emb,
                    generator=generator,
                    width=512,
                    height=768,
                    num_inference_steps=num_steps,
                    guidance_scale=current_cfg,
                ).images[0]

                image.save(output_path)
                print(f"[+] [{i + 1}/{num_images}] Saved: {output_path}")
            except Exception as e:
                print(f"[!] Error generating CFG {current_cfg:.2f}: {e}")

    finally:
        del pipe
        del tokenizer
        del text_encoder
        del emb
        del neg_emb
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    print(f"\n[✓] Completed CFG sweep of {num_images} images saved to: {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Run SD1.5 LCM inference sweeping CFG with fixed seed.")
    parser.add_argument("-p", "--prompt", default=DEFAULT_PROMPT, help="Prompt text")
    parser.add_argument("-s", "--seed", type=int, default=123456, help="Fixed random seed (default: 123456)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Model name or index (default: delusionsLCM_v20)")
    parser.add_argument("-n", "--num-images", type=int, default=50, help="Number of CFG stepped images (default: 50)")
    parser.add_argument("--cfg-start", type=float, default=1.0, help="Starting CFG scale (default: 1.0)")
    parser.add_argument("--cfg-step", type=float, default=0.04, help="CFG step increment (default: 0.04)")
    parser.add_argument("--steps", type=int, default=4, help="Inference steps (default: 4)")
    parser.add_argument("--lora", default=DEFAULT_LORA, help="Path to LoRA file (default: more_details.safetensors)")
    parser.add_argument("--lora-scale", type=float, default=0.25, help="LoRA scale weight (default: 0.25)")
    parser.add_argument("--vae", default=None, help="Optional custom VAE path")
    args = parser.parse_args()

    resolved_model = resolve_model(args.model)
    if not resolved_model:
        print(f"[!] No valid model found matching: {args.model}")
        return

    run_cfg_sweep(
        model_filename=resolved_model,
        prompt=args.prompt,
        seed=args.seed,
        num_images=args.num_images,
        cfg_start=args.cfg_start,
        cfg_step=args.cfg_step,
        num_steps=args.steps,
        lora_path=args.lora,
        lora_scale=args.lora_scale,
        vae_path=args.vae,
        output_base_dir=BASE_DIR
    )

if __name__ == '__main__':
    main()
