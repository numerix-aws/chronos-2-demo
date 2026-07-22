#!/usr/bin/env bash
set -euo pipefail

repo_root="$1"
output_dir="$2"
handler_dir="$repo_root/tools/lambda/lookup_use_case"
knowledge_dir="$repo_root/agent/knowledge"

mkdir -p "$output_dir/knowledge"
cp "$handler_dir/handler.py" "$output_dir/handler.py"
cp "$handler_dir/__init__.py" "$output_dir/__init__.py"
cp -R "$knowledge_dir/." "$output_dir/knowledge/"
