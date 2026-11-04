#!/usr/bin/env bash
# Turn Playwright takes into a captioned mp4 and a short GIF.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAKES="$ROOT/demo/takes"
DOCS="$ROOT/docs"
FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
mkdir -p "$DOCS" "$TAKES"
if [[ ! -f "$FONT" ]]; then
  FONT=$(fc-list : file | head -1 | cut -d: -f1)
fi

draw() {
  local text="$1" out="$2" seconds="$3"
  ffmpeg -y -f lavfi -i "color=c=0x1b2838:s=1280x720:d=${seconds}" \
    -vf "drawtext=fontfile=${FONT}:text='${text}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=16" \
    -c:v libx264 -pix_fmt yuv420p -r 30 "$out"
}

draw "Treasurer Desk\nFictional club data. No money moves.\nRules mode. Agent replies are live." "$TAKES/intro.mp4" 8
draw "Headless Switch 0.31.0\nMattermost room, three agents, one treasurer.\ngithub.com/nigelose10/treasurer-desk" "$TAKES/outro.mp4" 8

index=0
LIST="$TAKES/list.txt"
echo "file '$TAKES/intro.mp4'" > "$LIST"
CAPTIONS="$ROOT/demo/captions.srt"
python3 - <<'PY' "$TAKES/timing.json" "$CAPTIONS"
import json, sys
from pathlib import Path
timing = json.loads(Path(sys.argv[1]).read_text()) if Path(sys.argv[1]).exists() else {"steps": []}
cues = [(0, 8, "Fictional demo data. Rules mode: no LLM key. Replies are generated live.")]
cursor = 8.0
blocks = []
for step in timing.get("steps", []):
    if step.get("phase") == "login":
        continue
    duration = float(step.get("seconds") or 4)
    caption = step.get("caption") or step.get("wait") or ""
    blocks.append((cursor, cursor + duration, caption))
    cursor += duration
blocks.append((cursor, cursor + 8, "Ledger document updated in the Switch room. No money moved."))
def stamp(value: float) -> str:
    ms = int(round(value * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"
lines = []
for number, (start, end, text) in enumerate([(0, 8, cues[0][2]), *blocks], start=1):
    lines.append(str(number))
    lines.append(f"{stamp(start)} --> {stamp(end)}")
    lines.append(text)
    lines.append("")
Path(sys.argv[2]).write_text("\n".join(lines))
PY

for who in maya user; do
  if [[ -f "$TAKES/$who.webm" ]]; then
    ffmpeg -y -i "$TAKES/$who.webm" -an -c:v libx264 -pix_fmt yuv420p -r 30 "$TAKES/$who.mp4"
    echo "file '$TAKES/$who.mp4'" >> "$LIST"
  fi
done
echo "file '$TAKES/outro.mp4'" >> "$LIST"
ffmpeg -y -f concat -safe 0 -i "$LIST" -c copy "$TAKES/joined.mp4"
if ffmpeg -y -i "$TAKES/joined.mp4" -vf "subtitles=$CAPTIONS:force_style='FontSize=18,PrimaryColour=&HFFFFFF&'" -c:v libx264 -pix_fmt yuv420p "$DOCS/demo.mp4"; then
  echo "burned captions"
else
  cp "$TAKES/joined.mp4" "$DOCS/demo.mp4"
  echo "subtitle burn failed; copied the joined video without burned captions"
fi

# GIF of the treasurer take, which holds the approval.
if [[ -f "$TAKES/user.mp4" ]]; then
  ffmpeg -y -ss 1 -t 12 -i "$TAKES/user.mp4" -vf "fps=8,scale=800:-1:flags=lanczos,palettegen" "$TAKES/palette.png"
  ffmpeg -y -ss 1 -t 12 -i "$TAKES/user.mp4" -i "$TAKES/palette.png" \
    -lavfi "fps=8,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse" "$DOCS/approval.gif"
fi
ls -lh "$DOCS/demo.mp4" "$DOCS/approval.gif" 2>/dev/null || true
