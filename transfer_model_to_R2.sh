#!/usr/bin/env bash

source env.modeltransfer
pip install -U huggingface_hub hf_transfer awscli

MODEL_DIR="./models/$HF_REPO_ID"
mkdir -p "$MODEL_DIR"

if [ -n "$HF_FILENAME" ]; then
  hf download "$HF_REPO_ID" "$HF_FILENAME" \
    --local-dir "$MODEL_DIR" \
    ${HF_TOKEN:+--token "$HF_TOKEN"}
else
  hf download "$HF_REPO_ID" \
    --local-dir "$MODEL_DIR" \
    ${HF_TOKEN:+--token "$HF_TOKEN"}
fi

aws s3 sync "$MODEL_DIR" "s3://$R2_BUCKET/$R2_PREFIX" \
  --endpoint-url "$R2_ENDPOINT"
