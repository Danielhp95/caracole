# Model weights for the auto-chords unit, as fixed-output derivations.
#
# The unit runs with PrivateNetwork = true, so nothing may download at run time.
# package.nix's auto-chords variant points CARACOLE_BTC_WEIGHTS and
# CARACOLE_BEAT_CHECKPOINT at these store paths (wrapper defaults, which the NixOS
# module's options and [autochords] in caracole.toml override).
{ fetchurl }:
{
  # BTC large-vocabulary weights (170 chord classes), from the authors' repository
  # at a fixed commit. MIT License, Copyright (c) 2019 Jonggwon Park. The same file
  # is mirrored, byte for byte, at huggingface.co/puar-playground/btc-chord.
  btcWeights = fetchurl {
    name = "btc_model_large_voca.pt";
    url = "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/test/btc_model_large_voca.pt";
    hash = "sha256-FnPSP4+aVa5/nouApR2mFt67ImdbjYtn6mzg7zewq1E=";
  };

  # beat_this "final0", the default checkpoint of beat_this 1.1.0 (its CHECKPOINT_URL
  # plus "/final0.ckpt"). MIT License, CPJKU. JKU publishes no versioned URL for it;
  # the hash pins the content, last modified 2024-07-01.
  beatThisCheckpoint = fetchurl {
    name = "beat_this-final0.ckpt";
    url = "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt";
    hash = "sha256-jDKLRfWdjdPf8hklP/ao1kgr5X0BM6KRQOL+u/jrgzE=";
  };

  # Whisper large-v3, for the lyrics of a song no lyrics site has. MIT License, OpenAI. The URL is
  # openai-whisper's own for it (the checkpoint's SHA-256 is its folder name), 3,087,371,615 bytes.
  whisperLargeV3 = fetchurl {
    name = "whisper-large-v3.pt";
    url = "https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt";
    hash = "sha256-5bGlW4nBNn2s+X4+Gb/YKaAVKdv97vqMrrWbPxuB2ts=";
  };

  # HTDemucs as demucs-rs reads it (safetensors), which separates the vocals from the mix so the
  # transcript can be checked against where the singing is. Demucs' code is MIT (Meta); of its weights,
  # its author's README says "The license of the weights is not clear". Converted by set-soft, pinned
  # at a commit; 84,030,696 bytes.
  htdemucs = fetchurl {
    name = "htdemucs.safetensors";
    url = "https://huggingface.co/set-soft/audio_separation/resolve/939723568b2dca203e61cc7294317ba38549964f/Demucs/htdemucs.safetensors";
    hash = "sha256-gZNQTN+zlDra8Dm4rLUkpG6H6/Iyw4OsejLICmV4Qj4=";
  };
}
