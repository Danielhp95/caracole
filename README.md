# tabarr

Turns the songs you want to learn into a private library of sing-along chord
sheets, lyrics and guitar parts. It runs nightly. The design is in
[`plan.md`](plan.md), and the step 0 findings are in
[`docs/spike-2026-10-18.md`](docs/spike-2026-10-18.md).

## Development

    nix develop
    pytest

## Install / deploy

    nix build                     # the package; its build runs the test suite
    nix build .#autochords        # with torch, beat-this and librosa
    nix flake check               # also evaluates the NixOS module's units

`nixosModules.default` runs `tabarr run` nightly as a hardened systemd
service, with an optional offline auto-chords unit and an ntfy message on
failure. [`docs/deploy.md`](docs/deploy.md) sets it up on a NixOS host, with
agenix secrets, Syncthing, restic and the first-run steps.
