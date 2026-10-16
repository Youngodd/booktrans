"""WeChat Cloud Hosting storage, called from inside the container.

The mini program uploads a book to cloud storage with wx.cloud.uploadFile; the container
fetches it here, and puts the finished PDF back for the mini program to download. Inside
Cloud Hosting these WeChat HTTP APIs need no access token. WX_API_BASE overrides the address.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

TIMEOUT = 60


class CloudError(Exception):
    pass


def _base():
    return os.environ.get("WX_API_BASE", "http://api.weixin.qq.com")


def _post_json(path, body):
    req = urllib.request.Request(_base() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise CloudError(f"cloud storage request failed: HTTP {e.code} {e.read()[:300]!r} "
                         f"(POST {_base()}{path})")
    except (OSError, ValueError) as e:
        raise CloudError(f"cloud storage request failed: {e} (POST {_base()}{path})")
    if data.get("errcode"):
        raise CloudError(f"cloud storage error {data.get('errcode')}: {data.get('errmsg')}")
    return data


def download(env, file_id, dest, max_bytes):
    """Save the stored file to `dest`; raises CloudError if missing or over max_bytes."""
    data = _post_json("/tcb/batchdownloadfile",
                      {"env": env, "file_list": [{"fileid": file_id, "max_age": 600}]})
    item = (data.get("file_list") or [{}])[0]
    if item.get("status") != 0 or not item.get("download_url"):
        raise CloudError(f"file not available: {item.get('errmsg') or 'unknown'}")
    size = 0
    try:
        with urllib.request.urlopen(item["download_url"], timeout=TIMEOUT) as r, open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise CloudError("file too large")
                f.write(chunk)
    except OSError as e:
        raise CloudError(f"download failed: {e}")


def upload(env, local_path, cloud_path):
    """Store a local file under cloud_path and return its file id."""
    info = _post_json("/tcb/uploadfile", {"env": env, "path": cloud_path})
    boundary = uuid.uuid4().hex
    fields = {"key": cloud_path, "Signature": info["authorization"],
              "x-cos-security-token": info["token"], "x-cos-meta-fileid": info["cos_file_id"]}
    head = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    head += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
             f'filename="{os.path.basename(cloud_path)}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    with open(local_path, "rb") as f:
        body = head + f.read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(info["url"], data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=300).close()
    except OSError as e:
        raise CloudError(f"upload failed: {e}")
    return info["file_id"]


def delete(env, file_ids):
    """Remove stored files (best effort)."""
    try:
        _post_json("/tcb/batchdeletefile", {"env": env, "fileid_list": list(file_ids)})
    except CloudError:
        pass
