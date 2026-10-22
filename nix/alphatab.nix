# alphaTab, which caracole serve's Guitar Pro page draws and plays a Guitar Pro
# file with (src/caracole/web/alphatab.py), as a fixed-output fetch of its npm
# package: not in nixpkgs, and nothing is downloaded at run time.
#
# Only the three files the page needs, and their licences, go in the store path:
#   alphaTab.min.js  alphaTab 1.8.4's browser build (UMD), MPL-2.0;
#   Bravura.woff2    the music font, SIL Open Font License 1.1;
#   sonivox.sf3      the SoundFont its synthesizer plays, Apache-2.0;
# about 2.4 MB. package.nix's wrapper points CARACOLE_ALPHATAB_DIR at it.
{
  lib,
  stdenvNoCC,
  fetchurl,
}:
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "alphatab";
  version = "1.8.4";

  src = fetchurl {
    url = "https://registry.npmjs.org/@coderline/alphatab/-/alphatab-${finalAttrs.version}.tgz";
    hash = "sha256-cLLHeryWmKBV2QoR13MItrQSR5Nkdulp2Fdw49TbRgI=";
  };

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm444 dist/alphaTab.min.js $out/alphaTab.min.js
    install -Dm444 dist/font/Bravura.woff2 $out/Bravura.woff2
    install -Dm444 dist/soundfont/sonivox.sf3 $out/sonivox.sf3
    install -Dm444 LICENSE $out/licenses/alphaTab-LICENSE
    install -Dm444 LICENSE.header $out/licenses/alphaTab-LICENSE.header
    install -Dm444 dist/font/Bravura-OFL.txt $out/licenses/Bravura-OFL.txt
    install -Dm444 dist/soundfont/LICENSE $out/licenses/sonivox-LICENSE
    install -Dm444 dist/soundfont/README.md $out/licenses/sonivox-README.md
    runHook postInstall
  '';

  meta = {
    description = "alphaTab's browser build, the Bravura font and the Sonivox SoundFont, for caracole serve";
    homepage = "https://www.alphatab.net";
    license = with lib.licenses; [
      mpl20
      ofl
      asl20
    ];
    platforms = lib.platforms.all;
  };
})
