"""User preferences API — per-user key/value store backed by a JSON file."""
import base64
import io
import json
import os
import re
from typing import Optional
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image, ImageOps
from src.auth_helpers import get_current_user
from src.upload_limits import read_upload_limited

PREFS_FILE = os.path.join("data", "user_prefs.json")
_AVATAR_DATA_URL_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)
_MAX_AVATAR_LENGTH = 512_000
_MAX_AVATAR_UPLOAD_BYTES = 5 * 1024 * 1024


def _validate_pref(key: str, value):
    if key != "avatar" or value in (None, ""):
        return value
    if not isinstance(value, str) or len(value) > _MAX_AVATAR_LENGTH or not _AVATAR_DATA_URL_RE.fullmatch(value):
        raise HTTPException(400, "Avatar must be a supported image smaller than 512 KB")
    return value


def _load():
    """Load the raw prefs file (internal use only)."""
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(prefs):
    os.makedirs(os.path.dirname(PREFS_FILE) or ".", exist_ok=True)
    tmp = f"{PREFS_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PREFS_FILE)


def _load_for_user(user: Optional[str] = None) -> dict:
    """Load preferences for a specific user."""
    all_prefs = _load()
    if "_users" in all_prefs:
        if user is None:
            # Auth disabled — return first user's prefs for backward compat
            users = all_prefs["_users"]
            return dict(next(iter(users.values()), {}))
        return dict(all_prefs["_users"].get(user, {}))
    # Legacy flat format — return as-is
    return dict(all_prefs)


def _save_for_user(user: Optional[str], prefs: dict):
    """Save preferences for a specific user."""
    all_prefs = _load()
    if user is None:
        # Auth disabled. If the store is already multi-user (e.g. auth was
        # turned off on a deployment that previously ran multi-user), writing
        # `prefs` flat would overwrite the whole `_users` map and destroy every
        # other user's preferences. Instead write back into the same (first)
        # slot _load_for_user(None) reads from, preserving the others.
        if "_users" in all_prefs:
            users = all_prefs["_users"]
            first_key = next(iter(users), None)
            if first_key is not None:
                users[first_key] = prefs
                _save(all_prefs)
                return
        _save(prefs)
        return
    if "_users" not in all_prefs:
        all_prefs = {"_users": {}}
    all_prefs["_users"][user] = prefs
    _save(all_prefs)


def setup_prefs_routes():
    router = APIRouter(prefix="/api/prefs", tags=["preferences"])

    @router.get("")
    async def get_all_prefs(request: Request):
        user = get_current_user(request)
        return _load_for_user(user)

    @router.post("/avatar/upload")
    async def upload_avatar(request: Request, file: UploadFile = File(...)):
        """Normalize an avatar server-side using the same multipart path as other uploads."""
        content = await read_upload_limited(file, _MAX_AVATAR_UPLOAD_BYTES, "Avatar")
        try:
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source)
                image.seek(0)
                side = min(image.width, image.height)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                output = io.BytesIO()
                image.save(output, "WEBP", quality=86, method=4)
        except Exception as error:
            raise HTTPException(400, "Choose a valid PNG, JPEG, GIF, or WebP image") from error

        value = "data:image/webp;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        user = get_current_user(request)
        prefs = _load_for_user(user)
        prefs["avatar"] = _validate_pref("avatar", value)
        _save_for_user(user, prefs)
        return {"key": "avatar", "value": value}

    @router.get("/{key}")
    async def get_pref(request: Request, key: str):
        user = get_current_user(request)
        prefs = _load_for_user(user)
        return {"key": key, "value": prefs.get(key)}

    @router.put("/{key}")
    async def set_pref(request: Request, key: str, body: dict):
        user = get_current_user(request)
        prefs = _load_for_user(user)
        prefs[key] = _validate_pref(key, body.get("value"))
        _save_for_user(user, prefs)
        return {"key": key, "value": prefs[key]}

    return router
