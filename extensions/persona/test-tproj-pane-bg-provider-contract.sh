#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT="$SCRIPT_DIR/tproj-pane-bg"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-pane-bg-provider.XXXXXX")"
HOME_TEST="$WORK/home"
BIN="$WORK/bin"
PYTHONPATH_ROOT="$WORK/python"
PROJECT="$WORK/project"
SUCCESS_PROJECT="$WORK/success-project"
MODEL_FALLBACK_PROJECT="$WORK/model-fallback-project"
MODEL_UNAVAILABLE_PROJECT="$WORK/model-unavailable-project"
LIVE_SHAPE_PROJECT="$WORK/live-shape-project"
PROVIDER_LOG="$WORK/providers.log"
SLEEP_LOG="$WORK/sleep.log"
mkdir -p "$HOME_TEST/bin" "$BIN" "$PYTHONPATH_ROOT/google" "$PROJECT" "$SUCCESS_PROJECT" \
  "$MODEL_FALLBACK_PROJECT" "$MODEL_UNAVAILABLE_PROJECT" "$LIVE_SHAPE_PROJECT"
trap 'rm -rf "$WORK"' EXIT

cat > "$HOME_TEST/bin/project-bootstrap" <<'BOOTSTRAP'
#!/usr/bin/env bash
printf '%s\n' 'CC  Persona: INFP/男/20代/大航海時代/詩的/chi-rel:同僚 / master-rel:騎士的 / callname:航海士 / chara:天然系 / prof:航海士'
printf '%s\n' 'Cdx Persona: INTP/男/20代/大航海時代/論理的/chi-rel:同僚 / master-rel:参謀的 / callname:測量士 / chara:天然系 / prof:航海士'
BOOTSTRAP
chmod +x "$HOME_TEST/bin/project-bootstrap"

cat > "$PYTHONPATH_ROOT/google/__init__.py" <<'PYINIT'
from . import genai
PYINIT

cat > "$PYTHONPATH_ROOT/google/genai.py" <<'PYGENAI'
import base64
import os

LOG = os.environ["TPROJ_FAKE_PROVIDER_LOG"]
MODE = os.environ.get("TPROJ_FAKE_MODE", "permanent")
SECRET = os.environ.get("GEMINI_API_KEY", "")


class FakeError(Exception):
    def __init__(self, message, code, status, live_shape=False):
        super().__init__(message)
        if live_shape:
            self.code = code
            self.status = status
        else:
            self.status_code = code
            self.response_json = {"error": {"code": code, "status": status}}


class InlineData:
    mime_type = "image/png"
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


class Part:
    inline_data = InlineData()


class Content:
    parts = [Part()]


class Candidate:
    content = Content()


class Response:
    candidates = [Candidate()]


class Client:
    def __init__(self, **kwargs):
        self.provider = "vertex" if kwargs.get("vertexai") else "api_key"
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(self.provider + "\n")
        self.models = self

    def generate_content(self, **kwargs):
        model = kwargs.get("model", "")
        if MODE == "vertex_success" and self.provider == "vertex":
            return Response()
        if MODE == "model_fallback" and self.provider == "vertex":
            if model == "gemini-3-pro-image-preview":
                raise FakeError("Publisher model gemini-3-pro-image-preview not found", 404, "NOT_FOUND", True)
            return Response()
        if MODE == "model_unavailable" and self.provider == "vertex":
            raise FakeError("Publisher model gemini image model unavailable", 404, "NOT_FOUND", True)
        if MODE == "transient":
            raise FakeError("RESOURCE_EXHAUSTED transient transport", 429, "RESOURCE_EXHAUSTED")
        if self.provider == "vertex":
            raise FakeError("vertex ADC denied", 401, "UNAUTHENTICATED", MODE == "live_shape")
        raise FakeError(f"API key {SECRET} invalid TEST_SECRET_VALUE", 400, "API_KEY_INVALID")
PYGENAI

cat > "$BIN/tmux" <<'TMUX'
#!/usr/bin/env bash
case "${1:-}" in
  has-session) exit 0 ;;
  show-environment) exit 0 ;;
  *) exit 0 ;;
esac
TMUX
chmod +x "$BIN/tmux"

cat > "$BIN/sleep" <<'SLEEP'
#!/usr/bin/env bash
printf '%s\n' "${1:-}" >> "$TPROJ_FAKE_SLEEP_LOG"
exit 0
SLEEP
chmod +x "$BIN/sleep"

export HOME="$HOME_TEST"
export PATH="$BIN:$PATH"
export PYTHONPATH="$PYTHONPATH_ROOT"
export TPROJ_FAKE_PROVIDER_LOG="$PROVIDER_LOG"
export TPROJ_FAKE_SLEEP_LOG="$SLEEP_LOG"
export GOOGLE_CLOUD_PROJECT="test-project"
export GOOGLE_CLOUD_LOCATION="global"
export GEMINI_API_KEY="TEST_SECRET_VALUE"
export TPROJ_PANE_BG_REQUEST_TIMEOUT_SECONDS=1

assert_json() {
  local file="$1"
  local filter="$2"
  jq -e "$filter" "$file" >/dev/null
}

set +e
TPROJ_FAKE_MODE=permanent "$SCRIPT" generate --project "$PROJECT" --role cc --refresh >"$WORK/permanent.out" 2>&1
permanent_rc=$?
set -e
[[ "$permanent_rc" -ne 0 ]]
PERMANENT_STATUS="$PROJECT/.local/tproj-pane-bg/.generation-status.cc.json"
assert_json "$PERMANENT_STATUS" '.retry_class == "permanent_auth" and (.error.attempts | length) == 2 and ([.error.attempts[].provider] | join(",")) == "vertex,api_key" and ([.error.attempts[].status] | join(",")) == "UNAUTHENTICATED,API_KEY_INVALID"'
[[ "$(wc -l < "$PROVIDER_LOG" | tr -d ' ')" == 2 ]]
! grep -R -F 'TEST_SECRET_VALUE' "$PROJECT/.local/tproj-pane-bg"
: > "$SLEEP_LOG"
TPROJ_FAKE_MODE=permanent "$SCRIPT" retry-worker --session test-session --project "$PROJECT" --role cc >"$WORK/permanent-retry.out" 2>&1
[[ ! -s "$SLEEP_LOG" ]]

: > "$PROVIDER_LOG"
set +e
TPROJ_FAKE_MODE=live_shape "$SCRIPT" generate --project "$LIVE_SHAPE_PROJECT" --role cc --refresh >"$WORK/live-shape.out" 2>&1
live_shape_rc=$?
set -e
[[ "$live_shape_rc" -ne 0 ]]
LIVE_SHAPE_STATUS="$LIVE_SHAPE_PROJECT/.local/tproj-pane-bg/.generation-status.cc.json"
assert_json "$LIVE_SHAPE_STATUS" '.error.attempts[0].code == 401 and .error.attempts[0].status == "UNAUTHENTICATED" and .error.attempts[1].code == 400 and .error.attempts[1].status == "API_KEY_INVALID"'

: > "$PROVIDER_LOG"
set +e
TPROJ_FAKE_MODE=transient TPROJ_PANE_BG_MAX_ATTEMPTS=3 \
  "$SCRIPT" generate --project "$PROJECT" --role cdx --refresh >"$WORK/transient.out" 2>&1
transient_rc=$?
set -e
[[ "$transient_rc" -ne 0 ]]
TRANSIENT_STATUS="$PROJECT/.local/tproj-pane-bg/.generation-status.cdx.json"
assert_json "$TRANSIENT_STATUS" '.retry_class == "transient" and (.error.attempts | length) == 2'
[[ "$(wc -l < "$PROVIDER_LOG" | tr -d ' ')" -ge 6 ]]
: > "$SLEEP_LOG"
TPROJ_FAKE_MODE=transient "$SCRIPT" retry-worker --session test-session --project "$PROJECT" --role cdx >"$WORK/transient-retry.out" 2>&1
[[ "$(wc -l < "$SLEEP_LOG" | tr -d ' ')" == 3 ]]

: > "$PROVIDER_LOG"
TPROJ_FAKE_MODE=model_fallback "$SCRIPT" generate --project "$MODEL_FALLBACK_PROJECT" --role cc --refresh >"$WORK/model-fallback.out" 2>&1
[[ -s "$MODEL_FALLBACK_PROJECT/.local/tproj-pane-bg/cc.vertical.png" ]]
[[ "$(cat "$PROVIDER_LOG")" == $'vertex\napi_key\nvertex' ]]
[[ ! -e "$MODEL_FALLBACK_PROJECT/.local/tproj-pane-bg/.generation-status.cc.json" ]]
! grep -R -F 'TEST_SECRET_VALUE' "$MODEL_FALLBACK_PROJECT/.local/tproj-pane-bg"

: > "$PROVIDER_LOG"
set +e
TPROJ_FAKE_MODE=model_unavailable "$SCRIPT" generate --project "$MODEL_UNAVAILABLE_PROJECT" --role cc --refresh >"$WORK/model-unavailable.out" 2>&1
model_unavailable_rc=$?
set -e
[[ "$model_unavailable_rc" -ne 0 ]]
MODEL_UNAVAILABLE_STATUS="$MODEL_UNAVAILABLE_PROJECT/.local/tproj-pane-bg/.generation-status.cc.json"
assert_json "$MODEL_UNAVAILABLE_STATUS" '.retry_class == "model_unavailable" and (.error.attempts | length) == 2'
[[ "$(wc -l < "$PROVIDER_LOG" | tr -d ' ')" == 4 ]]
: > "$SLEEP_LOG"
TPROJ_FAKE_MODE=model_unavailable "$SCRIPT" retry-worker --session test-session --project "$MODEL_UNAVAILABLE_PROJECT" --role cc >"$WORK/model-unavailable-retry.out" 2>&1
[[ ! -s "$SLEEP_LOG" ]]

: > "$PROVIDER_LOG"
TPROJ_FAKE_MODE=vertex_success "$SCRIPT" generate --project "$SUCCESS_PROJECT" --role cc --refresh >"$WORK/success.out" 2>&1
[[ -s "$SUCCESS_PROJECT/.local/tproj-pane-bg/cc.vertical.png" ]]
[[ -s "$SUCCESS_PROJECT/.local/tproj-pane-bg/cc.vertical.json" ]]
[[ "$(cat "$PROVIDER_LOG")" == "vertex" ]]
[[ ! -e "$SUCCESS_PROJECT/.local/tproj-pane-bg/.generation-status.cc.json" ]]
! grep -R -F 'TEST_SECRET_VALUE' "$SUCCESS_PROJECT/.local/tproj-pane-bg"

printf '%s\n' 'PASS provider_errors_are_attributed_and_redacted'
printf '%s\n' 'PASS live_client_error_shape_preserves_code_status'
printf '%s\n' 'PASS permanent_auth_stops_internal_and_worker_retries'
printf '%s\n' 'PASS transient_errors_retry'
printf '%s\n' 'PASS model_unavailable_falls_back_once_and_stops_permanently'
printf '%s\n' 'PASS successful_vertex_skips_invalid_api_fallback'
printf '%s\n' 'TOTAL: 6 passed, 0 failed'
