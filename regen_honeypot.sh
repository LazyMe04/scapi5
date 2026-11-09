#!/usr/bin/env bash
# regen_honeypot.sh - rebuild the GonnCry victim home as a deterministic-random workload.
#
# Two requirements drive the design:
#
#   1. TOTAL encrypted bytes must be CONSTANT across runs, or trace duration drifts and
#      runs become incomparable.
#   2. File count, extension mix and per-file sizes must VARY across runs, or the trace is
#      deterministic and a classifier learns file count instead of encryption behaviour.
#
# Therefore: fix the total, randomise the distribution.

set -euo pipefail

TARGET_BYTES="${TARGET_BYTES:-67108864}"   # 64 MiB total plaintext
MIN_FILES="${MIN_FILES:-200}"
MAX_FILES="${MAX_FILES:-600}"
SEED="${SEED:-0}"

VICTIM_HOME=/home/victim
POOL=$(mktemp /tmp/emlab_pool.XXXXXX)
MANIFEST="$VICTIM_HOME/.honeypot_manifest.txt"

cleanup() { rm -f "$POOL"; }
trap cleanup EXIT

log() { printf '  %s\n' "$1"; }

printf '\n=== Honeypot regeneration ===\n'
log "target total bytes : $TARGET_BYTES"
log "file count range   : $MIN_FILES - $MAX_FILES"
log "rng seed           : $SEED"

# ---------------------------------------------------------------- clean
# Remove all prior ransomware residue AND all previously generated plaintext, otherwise bytes
# accumulate across regenerations and the target is never met.
rm -rf "$VICTIM_HOME/gonnacry" "$VICTIM_HOME/keys" 2>/dev/null || true
rm -rf "$VICTIM_HOME/documents" "$VICTIM_HOME/media" "$VICTIM_HOME/archive" "$VICTIM_HOME/data" 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 3 -name '*.GNNCRY' -delete 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 3 -name 'AES_encrypted_keys.txt' -delete 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 3 -name 'client_public_key.PEM' -delete 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 3 -name 'encrypted_client_private_key.key' -delete 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 3 -name 'img.png' -delete 2>/dev/null || true
find "$VICTIM_HOME" -maxdepth 1 -name '.*.GNNCRY' -delete 2>/dev/null || true

mkdir -p "$VICTIM_HOME/documents" "$VICTIM_HOME/media" "$VICTIM_HOME/archive" "$VICTIM_HOME/data"
# The sample writes its key material into this directory and will not create it itself.
mkdir -p "$VICTIM_HOME/gonnacry"

# ---------------------------------------------------------------- pool
# One random pool, sliced per file. Slicing is far faster than generating fresh randomness
# per file and produces the same entropy characteristics for this purpose.
log "building random pool"
dd if=/dev/urandom of="$POOL" bs=1M count=16 status=none

# ---------------------------------------------------------------- distribution
# Random count, then random weights scaled to hit TARGET_BYTES exactly.
# Weights are normalised so the last element absorbs only the rounding remainder, which keeps
# every file well under the random pool size.
COUNT=$(( MIN_FILES + (RANDOM % (MAX_FILES - MIN_FILES + 1)) ))

declare -a WEIGHTS=()
SUM_W=0
for (( i=0; i<COUNT; i++ )); do
    W=$(( 100 + (RANDOM % 900) ))
    WEIGHTS[$i]=$W
    SUM_W=$(( SUM_W + W ))
done

declare -a SIZES=()
ASSIGNED=0
for (( i=0; i<COUNT - 1; i++ )); do
    SIZE=$(( TARGET_BYTES * WEIGHTS[$i] / SUM_W ))
    (( SIZE < 1 )) && SIZE=1
    SIZES[$i]=$SIZE
    ASSIGNED=$(( ASSIGNED + SIZE ))
done
SIZES[$(( COUNT - 1 ))]=$(( TARGET_BYTES - ASSIGNED ))

# ---------------------------------------------------------------- write
EXTENSIONS=(txt pdf jpg png doc xls csv log json xml md sh py conf dat iso mp4 zip)

log "writing $COUNT files"
TOTAL=0
EXT_COUNTS=()

for (( i=0; i<COUNT; i++ )); do
    case $(( RANDOM % 4 )) in
        0) DIR="$VICTIM_HOME/documents" ;;
        1) DIR="$VICTIM_HOME/media" ;;
        2) DIR="$VICTIM_HOME/archive" ;;
        *) DIR="$VICTIM_HOME/data" ;;
    esac
    EXT=${EXTENSIONS[$(( RANDOM % ${#EXTENSIONS[@]} ))]}
    NAME=$(printf 'file_%04d_%s.%s' "$i" "$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')" "$EXT")
    SIZE=${SIZES[$i]}
    head -c "$SIZE" "$POOL" > "$DIR/$NAME" 2>/dev/null || true
    TOTAL=$(( TOTAL + SIZE ))
    EXT_COUNTS+=("$EXT")
done

# ---------------------------------------------------------------- verify
ACTUAL=$(find "$VICTIM_HOME" -type f ! -name '.*' ! -name '*.bin' ! -name '.honeypot_manifest.txt' -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')
ACTUAL_COUNT=$(find "$VICTIM_HOME" -type f ! -name '.*' ! -name '*.bin' ! -name '.honeypot_manifest.txt' 2>/dev/null | wc -l)

# ---------------------------------------------------------------- manifest
{
    printf 'generated_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'target_bytes=%s\n' "$TARGET_BYTES"
    printf 'actual_bytes=%s\n' "$ACTUAL"
    printf 'file_count=%s\n' "$ACTUAL_COUNT"
    printf 'seed=%s\n' "$SEED"
} > "$MANIFEST"

# Files must be owned and writable by victim: the ransomware shreds originals in place, and
# shred requires write permission. A bare a+rX leaves root ownership and read-only mode.
chown -R victim:victim "$VICTIM_HOME"
find "$VICTIM_HOME" -type d -exec chmod 755 {} +
find "$VICTIM_HOME" -type f ! -name 'gonnacry.bin' -exec chmod 644 {} +
# The binary must stay executable; a blanket 644 would strip its mode.
chmod 755 "$VICTIM_HOME/gonnacry.bin" 2>/dev/null || true

printf '\n=== Done ===\n'
printf '  files        : %s\n' "$ACTUAL_COUNT"
printf '  actual bytes : %s\n' "$ACTUAL"
printf '  target bytes : %s\n' "$TARGET_BYTES"
printf '  delta        : %s bytes (%.4f%%)\n' "$(( ACTUAL - TARGET_BYTES ))" \
    "$(awk "BEGIN{ if ($TARGET_BYTES > 0) printf \"%.4f\", (($ACTUAL - $TARGET_BYTES) * 100.0) / $TARGET_BYTES; else print 0 }")"
printf '  manifest     : %s\n' "$MANIFEST"

printf '\n'
if (( ACTUAL == TARGET_BYTES )); then
    printf '  [ OK ] byte count exact\n\n'
else
    printf '  [WARN] byte count differs from target - record the delta\n\n'
    printf '         run-to-run drift in this number means traces are not comparable\n\n'
fi

printf 'Next: sudo -u victim bash -c "cd /tmp && /home/victim/gonnacry.bin"\n'
printf 'Then: sudo bash ~/preflight.sh\n\n'