#!/usr/bin/env bash
# Contact sheet of one take: 1.2 frames per second, 4 x 3 tiles per sheet (a 10 s take fits on one sheet).
# Tile k (row by row, from 0) is the frame at about k / 1.2 s.
#   tools/contact_sheet.sh take.mp4 [out_prefix]   ->  out_prefix_1.jpg, out_prefix_2.jpg, ...
# FFMPEG=/path/to/ffmpeg picks another ffmpeg.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 take.mp4 [out_prefix]" >&2; exit 2; }
in=$1
prefix=${2:-${in%.*}_sheet}
rm -f "${prefix}"_*.jpg
"${FFMPEG:-ffmpeg}" -v error -y -i "$in" \
  -vf "fps=1.2,scale='if(gt(iw,ih),448,256)':'if(gt(iw,ih),256,448)',setsar=1,tile=4x3" "${prefix}_%d.jpg"
ls -1 "${prefix}"_*.jpg
