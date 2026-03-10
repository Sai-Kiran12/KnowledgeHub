from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib

import bcrypt
import jwt
from app.config import get_settings

settings = get_settings()
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def hash_password(password: str) -> str:
    # Pre-hash to avoid bcrypt's 72-byte password limit while keeping bcrypt storage.
    prehashed = hashlib.sha256(password.encode('utf-8')).digest()
    hashed = bcrypt.hashpw(prehashed, bcrypt.gensalt()).decode('utf-8')
    return f'bcrypt_sha256${hashed}'


def verify_password(plain: str, hashed: str) -> bool:
    # New format: bcrypt over sha256(password).
    if hashed.startswith('bcrypt_sha256$'):
        target = hashed.split('$', 1)[1].encode('utf-8')
        prehashed = hashlib.sha256(plain.encode('utf-8')).digest()
        return bcrypt.checkpw(prehashed, target)

    # Backward compatibility for old bcrypt hashes.
    if hashed.startswith('$2'):
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

    return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({'exp': expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
