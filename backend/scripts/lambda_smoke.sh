#!/usr/bin/env bash
# Smoke-test a built Lambda package inside AWS's official Python 3.13 Lambda image, with the
# network disabled (proves dependencies load on Lambda's Linux and nothing is downloaded at
# startup). Checks: bytecode import time, worker handler, API server answering /health.
#
#   python scripts/build_lambda.py --arch x86_64 && bash scripts/lambda_smoke.sh x86_64
set -euo pipefail

ARCH="${1:-x86_64}"
BUILD="$(cd "$(dirname "$0")/../dist/build/$ARCH" && (pwd -W 2>/dev/null || pwd))"
IMAGE="public.ecr.aws/lambda/python:3.13"
[ "$ARCH" = "arm64" ] && IMAGE="$IMAGE-arm64"
export MSYS_NO_PATHCONV=1  # Git Bash on Windows: don't rewrite the container paths below

docker run --rm --network none --entrypoint sh \
  -v "$BUILD/layer:/src/layer:ro" -v "$BUILD/function:/src/function:ro" \
  -e TIKTOKEN_CACHE_DIR=/opt/tiktoken_cache \
  -e DOCUMIND_LLM_PROVIDER=fake -e DOCUMIND_LOG_LEVEL=WARNING \
  "$IMAGE" -c '
set -e
# Copy into the container filesystem (bind mounts can be slow) where Lambda would put them.
cp -r /src/layer/. /opt/ && mkdir -p /var/task && cp -r /src/function/. /var/task/
export PYTHONPATH=/opt/python:/var/task
python - <<EOF
import time
t = time.time()
import documind.api.main  # noqa: F401
print("import API:      %.2fs" % (time.time() - t))
from documind.lambda_worker import handler
print("worker handler: ", handler({"Records": []}, None))
EOF
PORT=8080 sh /var/task/run.sh >/tmp/api.log 2>&1 &
python - <<EOF
import sys, time, urllib.request
for _ in range(60):
    try:
        body = urllib.request.urlopen("http://127.0.0.1:8080/health").read().decode()
        print("API /health:    ", body)
        sys.exit(0)
    except OSError:
        time.sleep(0.5)
print("API never answered /health; server log:")
print(open("/tmp/api.log").read())
sys.exit(1)
EOF
'
echo "Lambda package smoke test passed ($ARCH)."
