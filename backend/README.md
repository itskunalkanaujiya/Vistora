# Vistora — backend

FastAPI service behind [Vistora](https://github.com/itskunalkanaujiya/Vistora):
upload a product photo and get matching listings from online stores in India,
ranked by visual similarity, with prices and stock.

Deployed on Vercel as the `vistora-api` project (root directory
`backend`), at https://vistora-api.vercel.app. See the
[main README](https://github.com/itskunalkanaujiya/Vistora#readme) for the
full project, API and local setup.

## Deployment files

| File | Used by | Purpose |
|---|---|---|
| `pyproject.toml` | Vercel (uv) | Dependencies; installs CPU-only PyTorch; sets the `main:app` entrypoint |
| `vercel.json` | Vercel | Function duration and files left out of the bundle |
| `.vercelignore` | Vercel | Keeps `.env` and tests out of uploads |
| `requirements.txt` | pip, Dockerfile | Same dependencies for local setup and containers |
| `Dockerfile` | Any Docker host | Container image with the CLIP model baked in |

## Environment variables

| Name | Purpose |
|---|---|
| `SERPAPI_API_KEY` | Required. SerpApi key for Google Lens (store as a secret) |
| `ALLOWED_ORIGINS` | Frontend addresses allowed to call the API, comma-separated |
| `ALLOWED_ORIGIN_REGEX` | Optional pattern for preview URLs, e.g. `https://(snapbuy-ai\|vistora)(-[a-z0-9-]+)?\.vercel\.app` |
| `TRUST_PROXY_HEADERS` | `true` behind a hosting proxy, so search limits are per visitor |
| `SEARCH_LIMIT` / `SEARCH_WINDOW_SECONDS` | Optional. Defaults: 10 searches per 600 s per visitor |
| `CLIP_MODEL_NAME` | Optional. Defaults to `kunalkanaujiya/clip-vit-base-patch32-vision` |
| `ENABLE_CLIP_RANKING` | Optional. Off by default; `true` loads CLIP (needs torch and transformers installed) |
| `VISUAL_RERANK` | Optional. With CLIP on, `true` also scores photo-search thumbnails (look-alikes, similarity labels) |

## CLIP model

The service uses only CLIP ViT-B/32's image encoder, published at
[kunalkanaujiya/clip-vit-base-patch32-vision](https://huggingface.co/kunalkanaujiya/clip-vit-base-patch32-vision)
in half precision (176 MB instead of 605 MB), so it fits a serverless
function's `/tmp`. Scores match the original model within ~0.0003.
