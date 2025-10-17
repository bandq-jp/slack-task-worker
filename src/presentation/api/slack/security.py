import hmac
import hashlib
import time
from typing import Optional

from fastapi import HTTPException, Request


SLACK_SIGNATURE_HEADER = "X-Slack-Signature"
SLACK_TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"
SLACK_VERSION = "v0"
SLACK_TIMESTAMP_TOLERANCE_SECONDS = 60 * 5


async def verify_slack_signature(request: Request, signing_secret: Optional[str]) -> bytes:
    """
    Verify Slack signing secret for the incoming request and return the raw body.

    Slack expects the verification to be performed on the raw body using the base string:
        v0:{timestamp}:{body}
    The request must be within the tolerance window (default 5 minutes).
    """
    if not signing_secret:
        # When the secret is not configured we skip validation but still need the body later.
        return await request.body()

    signature = request.headers.get(SLACK_SIGNATURE_HEADER)
    timestamp = request.headers.get(SLACK_TIMESTAMP_HEADER)

    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc

    current_ts = int(time.time())
    if abs(current_ts - timestamp_value) > SLACK_TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="Slack request timestamp out of range")

    raw_body = await request.body()
    base_string = f"{SLACK_VERSION}:{timestamp}:{raw_body.decode('utf-8')}"

    computed = hmac.new(
        signing_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"{SLACK_VERSION}={computed}"

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return raw_body

