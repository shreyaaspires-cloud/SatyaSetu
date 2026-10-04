#!/usr/bin/env bash
# scripts/gitingest_safe.sh
# Safely bundle repository files for analysis while excluding sensitive files and binary weights.

set -euo pipefail

OUTPUT_FILE="${1:-repo_digest.txt}"

echo "Generating safe repository digest to: ${OUTPUT_FILE}"

if command -v gitingest >/dev/null 2>&1; then
    gitingest . \
        -o "${OUTPUT_FILE}" \
        --exclude-patterns "*.env,*.bin,*.pt,*.onnx,claims.db,*.log,eval/results/*,node_modules/*,.venv/*,__pycache__/*,.git/*"
else
    echo "gitingest CLI not found; using fallback find and cat script"
    > "${OUTPUT_FILE}"
    find . -type f \
        -not -path "*/.*" \
        -not -path "*/.venv/*" \
        -not -path "*/__pycache__/*" \
        -not -path "*/eval/results/*" \
        -not -name "*.env*" \
        -not -name "*.bin" \
        -not -name "*.pt" \
        -not -name "*.onnx" \
        -not -name "*.db" \
        -not -name "*.log" | sort | while read -r filepath; do
            echo "================================================" >> "${OUTPUT_FILE}"
            echo "FILE: ${filepath}" >> "${OUTPUT_FILE}"
            echo "================================================" >> "${OUTPUT_FILE}"
            cat "${filepath}" >> "${OUTPUT_FILE}"
            echo -e "\n" >> "${OUTPUT_FILE}"
        done
fi

echo "Repository digest generated successfully."
