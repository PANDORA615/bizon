#!/usr/bin/env sh
set -eu
TASK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
blender -b --factory-startup --python "$TASK_DIR/generate_rfc.py" -- --output "$TASK_DIR/RFC_BUILD" --mode full --export
