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
    "angraRealflexLCMV6_v10.safetensors",
    "rmbtestLCM_rmbtest4V10.safetensors",
    "dreamcrafterLCM_v10.safetensors"
]

CHECKPOINT_DIR = "/home/jack/Desktop/Comfy-UI/models/checkpoints"

DEFAULT_LORA = "/home/jack/Desktop/Comfy-UI/models/loras/more_details.safetensors"
OUTPUT_DIR = "static/novel_images/"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

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

def generate_with_model(
    prompt,
    seed,
    model_filename,
    num_steps=4,
    guidance_scale=1.5,
    lora_path=None,
    lora_scale=0.3,
    vae_path=None
):
    model_path = os.path.join(CHECKPOINT_DIR, model_filename)
    if not os.path.exists(model_path):
        print(f"[!] Warning: Model file not found: {model_path}, skipping.")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    print(f"\n" + "=" * 60)
    print(f"[*] Loading model: {model_filename} on {device} ({torch_dtype})")
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

    generator = torch.Generator(device=device).manual_seed(seed)

    print(f"[*] Generating image with seed {seed}, steps {num_steps}, cfg {guidance_scale}...")
    image = pipe(
        prompt_embeds=emb,
        negative_prompt_embeds=neg_emb,
        generator=generator,
        width=512,
        height=768,
        num_inference_steps=num_steps,
        guidance_scale=guidance_scale,
    ).images[0]

    output_path = os.path.join(OUTPUT_DIR, f"{seed}_{model_filename}_output.png")
    image.save(output_path)
    print(f"[+] Successfully saved output: {output_path}")

    # Explicit memory cleanup between models
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
    parser = argparse.ArgumentParser(description="Run SD1.5 LCM inference across models with memory cleanup.")
    parser.add_argument("-p", "--prompt", default=(
    "Dense Bosch-style surreal nightmare painting, horror vacui composition"
    "hundreds of intertwined grotesque creatures, skulls, tentacles, hybrid monsters"
    "medieval minstrel with lute, fish with human faces, crowned beast, candlelight chiaroscuro"
    "muted earth tones, aged oil painting texture, Northern Renaissance dark fantasy"
    "highly detailed, chaotic symbolic tableau"), help="Prompt text")
    parser.add_argument("-s", "--seed", type=int, default=234567, help="Random seed")
    parser.add_argument("--steps", type=int, default=4, help="Inference steps (default: 4)")
    parser.add_argument("--guidance", type=float, default=1.5, help="Guidance scale (default: 1.5)")
    parser.add_argument("-m", "--model", default=None, help="Specific model name, index, or comma-separated list (default: all)")
    parser.add_argument("--lora", default=DEFAULT_LORA, help="Path to LoRA file (default: more_details.safetensors)")
    parser.add_argument("--lora-scale", type=float, default=0.25, help="LoRA scale weight (0 to disable, default: 0.25)")
    parser.add_argument("--vae", default=None, help="Optional path to custom VAE (default: uses model's built-in VAE)")
    args = parser.parse_args()

    target_models = MODELS
    if args.model:
        if args.model.isdigit():
            idx = int(args.model)
            if 0 <= idx < len(MODELS):
                target_models = [MODELS[idx]]
        else:
            selected = [m.strip() for m in args.model.split(",")]
            target_models = [m for m in selected if m in MODELS]
        
        if not target_models:
            print(f"[!] No valid models matched selection: {args.model}")
            return

    total = len(target_models)
    print(f"[*] Starting batch generation for {total} model(s)...")

    for idx, model_name in enumerate(target_models, 1):
        ic(f"[{idx}/{total}] Processing model: {model_name}")
        try:
            generate_with_model(
                prompt=args.prompt,
                seed=args.seed,
                model_filename=model_name,
                num_steps=args.steps,
                guidance_scale=args.guidance,
                lora_path=args.lora,
                lora_scale=args.lora_scale,
                vae_path=args.vae
            )
        except Exception as e:
            print(f"[!] Error processing {model_name}: {e}")
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    print("\n[✓] All requested models processed successfully!")

if __name__ == '__main__':
    main()