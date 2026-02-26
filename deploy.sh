#!/bin/bash
# Cloud Run デプロイ用スクリプト
# 使い方: ./deploy.sh
# 環境変数ファイルを使う場合: ./deploy.sh env.yaml

set -e

REGION=us-central1

# 1つの --set-env-vars にまとめる（複数指定すると上書きされる）
# API キーに + や = が含まれるため、全体を単一引用符で囲む
# FIREBASE_PROJECT_ID: App Check トークンを発行している Firebase のプロジェクト（バックエンドと別のとき必須。例: picsche-23e36）
ENV_VARS='GOOGLE_CLOUD_PROJECT=picsche-vertex,FIREBASE_PROJECT_ID=picsche-23e36,VERTEX_LOCATION=us-central1,VERTEX_MODEL=gemini-2.5-pro,PICSCHE_BACKEND_API_KEY=ntXMDOyzWQ3cXksFEoxy+oRN6zuz0dXXfJL5v+jI9Ds='

if [[ -n "$1" && -f "$1" ]]; then
  # 引数で env ファイルを指定した場合
  gcloud run deploy picsche-extract \
    --source . \
    --region "$REGION" \
    --allow-unauthenticated \
    --env-vars-file "$1"
else
  gcloud run deploy picsche-extract \
    --source . \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "$ENV_VARS"
fi
