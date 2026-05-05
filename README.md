# Hugging Face → Cloudflare R2 model transfer

Cloudflare R2 uses an S3-compatible API, so the AWS CLI can upload to R2 when you pass the R2 endpoint. This does **not** upload to AWS.

## Usage

Fill in `env.modeltransfer`, then run:

```bash
source env.modeltransfer
pip install -U huggingface_hub hf_transfer awscli

if [ -n "$HF_FILENAME" ]; then
  hf download "$HF_REPO_ID" "$HF_FILENAME" \
    --local-dir ./model \
    ${HF_TOKEN:+--token "$HF_TOKEN"}
else
  hf download "$HF_REPO_ID" \
    --local-dir ./model \
    ${HF_TOKEN:+--token "$HF_TOKEN"}
fi

aws s3 sync ./model "s3://$R2_BUCKET/$R2_PREFIX" \
  --endpoint-url "$R2_ENDPOINT"
```

Example R2 endpoint:

```bash
https://<cloudflare-account-id>.r2.cloudflarestorage.com
```
