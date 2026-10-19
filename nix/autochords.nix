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
}
