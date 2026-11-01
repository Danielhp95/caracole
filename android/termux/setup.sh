#!/data/data/com.termux/files/usr/bin/sh
# caracole on an Android phone, in Termux: the real caracole, its ChordPro, its fonts and alphaTab, and caracole
# serve kept running, as docs/deploy.md's Ubuntu steps install it on a server. Experimental: see android/README.md.
#
#   sh setup.sh [SOURCE]            every step in order, stopping at the first that fails
#   sh setup.sh --step NAME [SOURCE]   one step again: tools, python, chordpro, fonts, wrapper, check, service
#
# SOURCE is what caracole is installed from: a tarball of the repository (git archive), a folder of it, or a
# pip address ("caracole @ git+https://github.com/Danielhp95/caracole@main", the default). Everything goes under
# ~/.caracole; the log of every step, ~/caracole-setup.log, is what to send when one fails.
set -eu

D="$HOME/.caracole"
LOG="$HOME/caracole-setup.log"
WORK="${TMPDIR:-$PREFIX/tmp}/caracole-setup"
STEPS="tools python chordpro fonts wrapper check service"

# The Nix package's versions, as docs/deploy.md's constraints.txt holds them (tests/test_android_termux.py checks
# the two agree). rapidfuzz, selectolax and opencc have no Android wheels: pip builds them here, for minutes.
CONSTRAINTS='httpx==0.28.1
selectolax==1.0.0
rapidfuzz==3.14.5
typer==0.25.1
click==8.3.3
mutagen==1.48.1
tomlkit==0.15.0
pypinyin==0.55.0
opencc==1.4.1'

# ChordPro 6.050.7 and the Text::Layout it needs, as docs/deploy.md's step 3 fetches them.
CHORDPRO_SHA256='58279341247c48187404876400f06ad7daa6fe71629558185df3673df09b9cea  Text-Layout-0.037.tar.gz
b6936caa1a1638f230a6b2b7a2ee6d6fda172a28771c44239bfd9ce45f6b3a84  App-Music-ChordPro-6.050.7.tar.gz'
CPAN=https://cpan.metacpan.org/authors/id/J/JV/JV

# The fonts and alphaTab, as docs/deploy.md's step 4 fetches them.
FONTS_SHA256='fd4eb05a8ae1480957bfe0372728bfde1171015c74b1ac349c889ae740751018  FusionKaiJ-Regular.ttf
4c927fbfeec1c503801ba510c2c94e0054c82c522cf7ba0d3be5d4d41fcf5c86  adwaita-fonts-50.0.tar.xz
70b2c77abc9698a055d90a11d77308b6b41247936476e969d85770e3d4db4602  alphatab-1.8.4.tgz'
PDF_FONTS_SHA256='aaacd46260916dfa4a15954c61f253b58e2b86d24a0e63de120103b5d9091561  pdf-fonts/regular.ttf
e4360458b36345158029a81888b765344b73a1767ce63c3ad4d777bb2f069a9f  pdf-fonts/bold.ttf
afc8acbb3d1f066abfaee99c130ac92df9aa21cb5e5f129f7a86c6f21cb0d9c9  pdf-fonts/italic.ttf'

say() { printf '\n== %s\n' "$*" | tee -a "$LOG"; }
run() { printf '$ %s\n' "$*" >>"$LOG"; "$@" >>"$LOG" 2>&1; }
fresh() { rm -rf "$WORK/$1" && mkdir -p "$WORK/$1" && cd "$WORK/$1"; }

step_tools() {
  say "tools: Termux's packages (Python, Perl, a compiler, SQLite, the service manager)"
  run pkg upgrade -y
  run pkg install -y python python-pip perl clang make cmake ninja binutils pkg-config sqlite git curl xz-utils \
    termux-services termux-api
  # caracole's search needs SQLite's FTS5 with its trigram tokenizer.
  run python -c 'import sqlite3, sys; sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize=trigram)"); print(sys.version)'
  echo "Python $(python -c 'import sys; print(sys.version.split()[0])'), SQLite with FTS5: ok" | tee -a "$LOG"
}

step_python() {
  say "python: a virtual environment, caracole and its dependencies (the native ones build here: be patient)"
  source=${SOURCE:-"caracole @ git+https://github.com/Danielhp95/caracole@main"}
  case $source in
    *.tar.gz|*.tgz)
      fresh src
      run tar -xzf "$source"
      source=$(dirname "$(find "$WORK/src" -maxdepth 2 -name pyproject.toml | head -n 1)")
      ;;
  esac
  [ -d "$source" ] && cp "$source/nix/pdf-fonts.py" "$D/pdf-fonts.py" 2>/dev/null || true
  mkdir -p "$D"
  printf '%s\n' "$CONSTRAINTS" >"$D/constraints.txt"
  [ -x "$D/venv/bin/python" ] || run python -m venv "$D/venv"
  # Builds use Termux's own compiler, cmake and ninja; MAKEFLAGS keeps a phone from running out of memory.
  run env MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 "$D/venv/bin/pip" install -c "$D/constraints.txt" "$source"
  run "$D/venv/bin/python" -c 'import rapidfuzz, selectolax.lexbor, opencc, pypinyin, httpx, caracole'
  echo "$("$D/venv/bin/caracole" --version), its native modules import: ok" | tee -a "$LOG"
}

step_chordpro() {
  say "chordpro: ChordPro 6.050.7 and its Perl modules from CPAN (Object::Pad compiles here)"
  fresh chordpro
  run curl -fsSLO "$CPAN/Text-Layout-0.037.tar.gz"
  run curl -fsSLO "$CPAN/App-Music-ChordPro-6.050.7.tar.gz"
  printf '%s\n' "$CHORDPRO_SHA256" | sha256sum -c - >>"$LOG" 2>&1
  command -v cpanm >/dev/null || run env PERL_MM_USE_DEFAULT=1 cpan -T App::cpanminus
  run env MAKEFLAGS=-j2 cpanm --notest -l "$D/perl" ./Text-Layout-0.037.tar.gz ./App-Music-ChordPro-6.050.7.tar.gz
  run env PERL5LIB="$D/perl/lib/perl5" "$D/perl/bin/chordpro" --version
  echo "chordpro: ok" | tee -a "$LOG"
}

step_fonts() {
  say "fonts: Adwaita for the PDFs, FusionKai for Chinese words, alphaTab for Guitar Pro files"
  fresh fonts
  run curl -fsSLO https://raw.githubusercontent.com/lxgw/FusionKai/v24.134/FusionKaiJ-Regular.ttf
  run curl -fsSLO https://download.gnome.org/sources/adwaita-fonts/50/adwaita-fonts-50.0.tar.xz
  run curl -fsSLO https://registry.npmjs.org/@coderline/alphatab/-/alphatab-1.8.4.tgz
  printf '%s\n' "$FONTS_SHA256" | sha256sum -c - >>"$LOG" 2>&1
  run tar -xJf adwaita-fonts-50.0.tar.xz
  run tar -xzf alphatab-1.8.4.tgz
  if [ ! -f "$D/pdf-fonts.py" ]; then
    run curl -fsSL -o "$D/pdf-fonts.py" https://raw.githubusercontent.com/Danielhp95/caracole/main/nix/pdf-fonts.py
  fi
  [ -x "$D/fonttools/bin/python" ] || run python -m venv "$D/fonttools"
  run "$D/fonttools/bin/pip" install fonttools==4.63.0
  run "$D/fonttools/bin/python" -I "$D/pdf-fonts.py" adwaita-fonts-50.0/sans pdf-fonts
  printf '%s\n' "$PDF_FONTS_SHA256" | sha256sum -c - >>"$LOG" 2>&1
  mkdir -p "$D/fonts" "$D/pdf-fonts" "$D/alphatab"
  cp FusionKaiJ-Regular.ttf "$D/fonts/"
  cp pdf-fonts/regular.ttf pdf-fonts/bold.ttf pdf-fonts/italic.ttf "$D/pdf-fonts/"
  cp adwaita-fonts-50.0/mono/AdwaitaMono-Regular.ttf "$D/pdf-fonts/mono.ttf"
  cp package/dist/alphaTab.min.js package/dist/font/Bravura.woff2 package/dist/soundfont/sonivox.sf3 "$D/alphatab/"
  echo "fonts and alphaTab: ok" | tee -a "$LOG"
}

step_wrapper() {
  say "wrapper: ~/.caracole/bin/caracole, as the Nix package's (ChordPro on PATH, the fonts' and alphaTab's paths)"
  mkdir -p "$D/bin"
  cat >"$D/bin/caracole" <<EOF
#!$PREFIX/bin/sh
# caracole as the Nix package's wrapper runs it, in Termux (android/termux/setup.sh). No model files: no auto-chords.
PATH=$D/bin:$D/perl/bin:\$PATH
PERL5LIB=$D/perl/lib/perl5\${PERL5LIB:+:\$PERL5LIB}
: "\${CARACOLE_CJK_FONT=$D/fonts/FusionKaiJ-Regular.ttf}"
: "\${CARACOLE_PDF_FONTS=$D/pdf-fonts}"
: "\${CARACOLE_ALPHATAB_DIR=$D/alphatab}"
export PATH PERL5LIB CARACOLE_CJK_FONT CARACOLE_PDF_FONTS CARACOLE_ALPHATAB_DIR
exec $D/venv/bin/caracole "\$@"
EOF
  chmod 0755 "$D/bin/caracole"
  grep -q '.caracole/bin' "$HOME/.profile" 2>/dev/null || printf 'PATH=$HOME/.caracole/bin:$PATH\n' >>"$HOME/.profile"
  run "$D/bin/caracole" --version
  echo "wrapper: ok" | tee -a "$LOG"
}

step_check() {
  say "check: a PDF from ChordPro, then caracole serve answering on 127.0.0.1:8737"
  fresh check
  printf '{title: Check}\n[C]Hello [G]phone\n' >check.cho
  run env PATH="$D/perl/bin:$PATH" PERL5LIB="$D/perl/lib/perl5" chordpro -o check.pdf check.cho
  test -s check.pdf
  echo "chordpro made a PDF: ok" | tee -a "$LOG"
  "$D/bin/caracole" serve --address 127.0.0.1 >>"$LOG" 2>&1 &
  pid=$!
  ok=no
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    sleep 2
    if curl -fsS http://127.0.0.1:8737/ -o page.html 2>>"$LOG"; then ok=yes; break; fi  # any caracole's page
  done
  kill "$pid" 2>/dev/null || true
  [ $ok = yes ] || { echo "caracole serve didn't answer: see $LOG" | tee -a "$LOG"; return 1; }
  echo "caracole serve answered with its library page ($(wc -c <page.html) bytes): ok" | tee -a "$LOG"
}

step_service() {
  say "service: caracole serve kept running by termux-services, and started at boot by Termux:Boot"
  mkdir -p "$PREFIX/var/service/caracole/log"
  cat >"$PREFIX/var/service/caracole/run" <<EOF
#!$PREFIX/bin/sh
# The address it listens on: ~/.caracole/address when there is one (0.0.0.0, or the tailnet's), else this phone alone.
address=\$(cat $D/address 2>/dev/null || echo 127.0.0.1)
exec $D/bin/caracole serve --address "\$address" 2>&1
EOF
  chmod 0755 "$PREFIX/var/service/caracole/run"
  ln -sf "$PREFIX/share/termux-services/svlogger" "$PREFIX/var/service/caracole/log/run"
  mkdir -p "$HOME/.termux/boot"
  cat >"$HOME/.termux/boot/start-caracole" <<EOF
#!$PREFIX/bin/sh
termux-wake-lock
. $PREFIX/etc/profile
EOF
  chmod 0755 "$HOME/.termux/boot/start-caracole"
  echo "Close Termux and open it again, then: sv-enable caracole (it starts at once, and after every boot)" \
    | tee -a "$LOG"
}

if [ "${1:-}" = --step ]; then
  name=${2:?--step needs a step: $STEPS}
  SOURCE=${3:-}
  case " $STEPS " in *" $name "*) ;; *) echo "No step $name: $STEPS" >&2; exit 2 ;; esac
  steps=$name
else
  SOURCE=${1:-}
  steps=$STEPS
fi
case $SOURCE in /*|"") ;; *) [ -e "$SOURCE" ] && SOURCE=$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE") ;; esac

printf '\ncaracole setup %s, on %s\n' "$(date -u +%FT%TZ)" "$(uname -m) Android $(getprop ro.build.version.release 2>/dev/null || echo ?)" >>"$LOG"
for step in $steps; do
  # In a subshell of its own, outside any condition, so that set -e stops the step at its first failure.
  set +e
  ( set -e; "step_$step" )
  status=$?
  set -e
  if [ $status -ne 0 ]; then
    echo "The step $step failed. Its output is at the end of $LOG: send that file. Then: sh $0 --step $step $SOURCE" >&2
    exit 1
  fi
done
echo "Done: $steps" | tee -a "$LOG"
