"""WeChat mini program login: exchange wx.login's code for a signed session token.

The token is "<openid>.<expiry>.<signature>" signed with BOOKTRANS_SECRET, so the
server keeps no session table. Jobs created with a token belong to that openid.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

TOKEN_DAYS = 30
SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class LoginError(Exception):
    pass


def _sign(secret, payload):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(secret, openid, now=None):
    exp = int((now or time.time()) + TOKEN_DAYS * 86400)
    payload = base64.urlsafe_b64encode(openid.encode()).decode().rstrip("=") + f".{exp}"
    return f"{payload}.{_sign(secret, payload)}"


def read_token(secret, token, now=None):
    """The openid in a valid, unexpired token, else None."""
    try:
        enc, exp, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(secret, f"{enc}.{exp}")):
            return None
        if int(exp) < (now or time.time()):
            return None
        return base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode()
    except (ValueError, AttributeError, TypeError):  # TypeError: a non-ASCII signature
        return None


def wechat_openid(code):
    """Ask WeChat which user this login code belongs to (needs WX_APPID and WX_SECRET)."""
    appid, secret = os.environ.get("WX_APPID"), os.environ.get("WX_SECRET")
    if not appid or not secret:
        if os.environ.get("BOOKTRANS_DEV_LOGIN") == "1":  # local testing without an AppSecret
            return "dev-" + hashlib.sha256(code.encode()).hexdigest()[:16]
        raise LoginError("WeChat login is not configured on the server.")
    query = urllib.parse.urlencode({"appid": appid, "secret": secret, "js_code": code,
                                    "grant_type": "authorization_code"})
    try:
        with urllib.request.urlopen(f"{SESSION_URL}?{query}", timeout=10) as r:
            data = json.loads(r.read())
    except (OSError, ValueError):
        raise LoginError("Could not reach WeChat to verify the login.")
    if not data.get("openid"):
        raise LoginError("WeChat rejected the login code.")
    return data["openid"]
