# The fonts caracole's PDFs are set in (src/caracole/pdf_fonts.py): GNOME's Adwaita Sans
# and Adwaita Mono (nixpkgs adwaita-fonts), the system fonts a GNOME desktop shows,
# Firefox's pages among them, as the four files ChordPro 6.050.7 draws right:
#   regular.ttf, bold.ttf, italic.ttf  static instances of Adwaita Sans's variable fonts
#                                      (weight 400, 700 and 400 italic), each glyph record
#                                      padded to an even length (./pdf-fonts.py);
#   mono.ttf                           Adwaita Mono Regular, as it is;
#   licenses/Adwaita-OFL.txt           their licence, the SIL Open Font License 1.1,
#                                      from adwaita-fonts' source.
# About 2.5 MB. package.nix's wrapper points CARACOLE_PDF_FONTS at it.
{
  lib,
  stdenvNoCC,
  adwaita-fonts,
  python3,
}:
stdenvNoCC.mkDerivation {
  pname = "caracole-pdf-fonts";
  # The source is adwaita-fonts' own, for its LICENSE; the fonts are the ones it installs.
  inherit (adwaita-fonts) version src;

  nativeBuildInputs = [ (python3.withPackages (ps: [ ps.fonttools ])) ];

  dontConfigure = true;

  buildPhase = ''
    runHook preBuild
    python3 ${./pdf-fonts.py} ${adwaita-fonts}/share/fonts/Adwaita instances
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    for role in regular bold italic; do
      install -Dm444 instances/$role.ttf $out/$role.ttf
    done
    install -Dm444 ${adwaita-fonts}/share/fonts/Adwaita/AdwaitaMono-Regular.ttf $out/mono.ttf
    install -Dm444 LICENSE $out/licenses/Adwaita-OFL.txt
    runHook postInstall
  '';

  meta = {
    description = "Adwaita Sans and Adwaita Mono as the files caracole's PDFs are set in";
    homepage = "https://gitlab.gnome.org/GNOME/adwaita-fonts";
    license = lib.licenses.ofl;
    platforms = lib.platforms.all;
  };
}
