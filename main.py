import os
import json
import logging
from fastapi import FastAPI, HTTPException, Header, Request

logger = logging.getLogger(__name__)

# 環境変数: Cloud Run で設定する
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
# 例: gemini-2.0-flash, gemini-2.5-pro など。リージョンで利用可能なモデルを指定
MODEL_ID = os.environ.get("VERTEX_MODEL", "gemini-2.0-flash")
BACKEND_API_KEY = os.environ.get("PICSCHE_BACKEND_API_KEY", "")

app = FastAPI()

# === 無料プラン利用回数（Firestore）===
from datetime import datetime
from google.cloud import firestore
db = firestore.Client()
USAGE_COLLECTION = "free_usage"
FREE_BASE_PER_MONTH = 1
FREE_REWARD_MAX_PER_MONTH = 2

def _current_month():
    return datetime.utcnow().strftime("%Y-%m")

def _get_usage_ref(user_id: str):
    return db.collection(USAGE_COLLECTION).document(user_id)

def _read_usage(user_id: str):
    ref = _get_usage_ref(user_id)
    doc = ref.get()
    month = _current_month()
    if not doc.exists:
        return {"usage_count": 0, "reward_grants": 0, "month": month}
    data = doc.to_dict()
    if data.get("month") != month:
        return {"usage_count": 0, "reward_grants": 0, "month": month}
    return {
        "usage_count": data.get("usage_count", 0),
        "reward_grants": data.get("reward_grants", 0),
        "month": month,
    }

def _effective_limit(reward_grants: int) -> int:
    return FREE_BASE_PER_MONTH + min(reward_grants, FREE_REWARD_MAX_PER_MONTH)

@app.get("/usage")
async def get_usage(user_id: str, x_api_key: str = Header(None)):
    if BACKEND_API_KEY and x_api_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id required")
    u = _read_usage(user_id.strip())
    limit = _effective_limit(u["reward_grants"])
    remaining = max(0, limit - u["usage_count"])
    reward_slots = max(0, FREE_REWARD_MAX_PER_MONTH - u["reward_grants"])
    return {
        "usage_count": u["usage_count"],
        "reward_grants": u["reward_grants"],
        "month": u["month"],
        "remaining": remaining,
        "can_use": remaining > 0,
        "reward_slots_remaining": reward_slots,
    }

@app.post("/usage/increment")
async def usage_increment(request: Request, x_api_key: str = Header(None)):
    if BACKEND_API_KEY and x_api_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    ref = _get_usage_ref(user_id)
    month = _current_month()
    doc = ref.get()
    if not doc.exists:
        ref.set({"usage_count": 1, "reward_grants": 0, "month": month})
        return {"usage_count": 1, "reward_grants": 0, "month": month, "remaining": 0}
    data = doc.to_dict()
    if data.get("month") != month:
        data = {"usage_count": 0, "reward_grants": 0, "month": month}
    data["usage_count"] = data.get("usage_count", 0) + 1
    ref.set(data)
    limit = _effective_limit(data.get("reward_grants", 0))
    remaining = max(0, limit - data["usage_count"])
    return {"usage_count": data["usage_count"], "reward_grants": data.get("reward_grants", 0), "month": month, "remaining": remaining}

@app.post("/usage/grant_reward")
async def usage_grant_reward(request: Request, x_api_key: str = Header(None)):
    if BACKEND_API_KEY and x_api_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    ref = _get_usage_ref(user_id)
    month = _current_month()
    doc = ref.get()
    if not doc.exists:
        data = {"usage_count": 0, "reward_grants": 1, "month": month}
    else:
        data = doc.to_dict()
        if data.get("month") != month:
            data = {"usage_count": 0, "reward_grants": 0, "month": month}
        data["reward_grants"] = min(data.get("reward_grants", 0) + 1, FREE_REWARD_MAX_PER_MONTH)
    ref.set(data)
    limit = _effective_limit(data.get("reward_grants", 0))
    remaining = max(0, limit - data.get("usage_count", 0))
    return {"usage_count": data.get("usage_count", 0), "reward_grants": data.get("reward_grants", 0), "month": month, "remaining": remaining}


def call_vertex(image_base64: str, prompt: str) -> str:
    """Vertex AI generateContent を REST で呼び出す（ADC 使用）。"""
    import urllib.request
    import google.auth
    import google.auth.transport.requests

    url = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{MODEL_ID}:generateContent"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inlineData": {"mimeType": "image/jpeg", "data": image_base64}},
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {"maxOutputTokens": 16384, "temperature": 0},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    req.add_header("Authorization", f"Bearer {credentials.token}")

    with urllib.request.urlopen(req, timeout=120) as res:
        result = json.loads(res.read().decode())

    usage = result.get("usageMetadata") or result.get("usage_metadata", {})
    input_tokens = usage.get("promptTokenCount") or usage.get("prompt_token_count") or 0
    output_tokens = usage.get("candidatesTokenCount") or usage.get("candidates_token_count") or 0
    thoughts_tokens = usage.get("thoughtsTokenCount") or usage.get("thoughts_token_count") or 0
    total_tokens = usage.get("totalTokenCount") or usage.get("total_token_count") or 0
    logger.info(
        "[Vertex AI] Token usage - Input: %s, Output: %s, Thoughts: %s, Total: %s",
        input_tokens, output_tokens, thoughts_tokens, total_tokens,
    )
    print(
        f"[Vertex AI] Token usage - Input: {input_tokens}, Output: {output_tokens}, "
        f"Thoughts: {thoughts_tokens}, Total: {total_tokens}"
    )

    candidates = result.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates in response")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise ValueError("No text in response")
    return parts[0]["text"]


@app.post("/extract")
async def extract(request: Request, x_api_key: str = Header(None)):
    if BACKEND_API_KEY and x_api_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        body = await request.json()
        image_base64 = body.get("image_base64")
        prompt = body.get("prompt", "")
        if not image_base64:
            raise HTTPException(status_code=400, detail="image_base64 required")
        text = call_vertex(image_base64, prompt)
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
