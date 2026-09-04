"""User authentication module.
JWT-based authentication with register, login, and token verification.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from db import create_user, get_user_by_username, get_user_by_id

logger = logging.getLogger("lifeops.auth")

# JWT Configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "lifeops-agent-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int, username: str) -> str:
    """Create a JWT access token."""
    expires = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expires,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning("Token decode failed: %s", e)
        return None


def register_user(username: str, password: str, display_name: str = "") -> Dict[str, Any]:
    """Register a new user. Returns user info and token."""
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2个字符")
    if not password or len(password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4个字符")

    password_hash = hash_password(password)
    user_id = create_user(username, password_hash, display_name)

    if user_id is None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    token = create_access_token(user_id, username)
    return {
        "ok": True,
        "user": {
            "id": user_id,
            "username": username,
            "display_name": display_name or username,
        },
        "token": token,
    }


def login_user(username: str, password: str) -> Dict[str, Any]:
    """Login a user. Returns user info and token."""
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user["id"], username)
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", username),
            "avatar": user.get("avatar", ""),
            "created_at": user.get("created_at", ""),
        },
        "token": token,
    }


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[Dict[str, Any]]:
    """Get current user from Bearer token. Returns None if not authenticated."""
    if credentials is None:
        return None

    payload = decode_token(credentials.credentials)
    if payload is None:
        return None

    user_id = int(payload.get("sub", 0))
    if user_id <= 0:
        return None

    user = get_user_by_id(user_id)
    return user


async def require_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """Require an authenticated user. Raises 401 if not authenticated."""
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
