#!/usr/bin/env bash
# KARTA asset generator (S4-09): SVG-лого → PNG-набор (фавикон/иконки/OG).
# Требуется: thorium-browser (headless-рендер). Использование:
#   bash branding/generate_assets.sh branding/karta-chakra.svg [out-dir]
set -euo pipefail

SVG_PATH="${1:?usage: generate_assets.sh <logo.svg> [out-dir]}"
BRAND_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${2:-$BRAND_DIR/out}"
SVG_ABS="$(cd "$(dirname "$SVG_PATH")" && pwd)/$(basename "$SVG_PATH")"
[ -f "$SVG_ABS" ] || { echo "SVG не найден: $SVG_ABS"; exit 1; }

mkdir -p "$OUT_DIR"
TMP="$(mktemp -d /tmp/karta-brand-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
PROFILE="$TMP/profile"
SVG_INLINE="$(cat "$SVG_ABS")"

render() { # render <html-file> <out-png> <w> <h> [bg]
  local html="$1" out="$2" w="$3" h="$4" bg="${5:-00000000}"
  thorium-browser --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --force-device-scale-factor=1 --default-background-color="$bg" \
    --user-data-dir="$PROFILE" --window-size="${w},${h}" \
    --screenshot="$out" "file://$html" >/dev/null 2>&1 || true
}

# 1) Фавикон-набор (прозрачный фон)
for SIZE in 16 32 48 180 512; do
  PAGE="$TMP/icon-$SIZE.html"
  cat > "$PAGE" <<HTML
<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden}
.wrap{width:${SIZE}px;height:${SIZE}px;display:flex;align-items:center;justify-content:center}
.wrap svg{width:${SIZE}px;height:${SIZE}px}
</style></head><body><div class="wrap">$SVG_INLINE</div></body></html>
HTML
  render "$PAGE" "$OUT_DIR/icon-${SIZE}.png" "$SIZE" "$SIZE"
done

# 2) Apple touch / PWA (тёмный тайл)
PAGE="$TMP/tile.html"
cat > "$PAGE" <<HTML
<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#0A0E17;overflow:hidden}
.wrap{width:180px;height:180px;display:flex;align-items:center;justify-content:center}
.wrap svg{width:132px;height:132px}
</style></head><body><div class="wrap">$SVG_INLINE</div></body></html>
HTML
render "$PAGE" "$OUT_DIR/apple-touch-icon.png" 180 180 "FF0A0E17"

# 3) OG-изображение 1200×630 (тёмный фон, лого + wordmark + слоган)
PAGE="$TMP/og.html"
cat > "$PAGE" <<HTML
<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#0A0E17;overflow:hidden;font-family:Inter,DejaVu Sans,sans-serif}
.og{width:1200px;height:630px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px}
.logo svg{width:190px;height:190px}
.brand{font-size:74px;font-weight:700;letter-spacing:.06em;color:#E6EAF2}
.tag{font-size:26px;color:#8B93A7}
</style></head><body><div class="og">
  <div class="logo">$SVG_INLINE</div>
  <div class="brand">KARTA</div>
  <div class="tag">Доверенная автономия в ончейне · агент предлагает — политика разрешает</div>
</div></body></html>
HTML
render "$PAGE" "$OUT_DIR/og-image.png" 1200 630 "FF0A0E17"

echo "Ассеты созданы в: $OUT_DIR"
ls -la "$OUT_DIR"
