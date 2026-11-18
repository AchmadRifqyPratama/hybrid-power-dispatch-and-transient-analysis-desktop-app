"""Keamanan aplikasi — gerbang kata sandi (password gate).

Saat dibuka, HPP Studio meminta SATU kata sandi (tanpa username). Kata sandi
TIDAK pernah disimpan sebagai teks; yang disimpan hanyalah **hash SHA-256**-nya.
Perbandingan saat login memakai `hmac.compare_digest` (constant-time).

Hash TIDAK disimpan di repositori. Hash dibaca dari berkas lokal
`app/config/password_local.py` yang di-ignore oleh git. Bila berkas itu tidak
ada (mis. kode hasil clone/download), SEMUA kata sandi ditolak sehingga
aplikasi tidak dapat dibuka.

Untuk mengatur kata sandi di komputer Anda sendiri, jalankan:
    python set_password.py
Skrip itu membuat/menimpa `app/config/password_local.py`. Saat build .exe,
berkas tersebut ikut dibundel oleh PyInstaller.
"""
from __future__ import annotations
import hashlib
import hmac
import re

try:
    from .password_local import PASSWORD_SHA256
except ImportError:
    PASSWORD_SHA256 = ''


def hash_password(password: str) -> str:
    """Kembalikan hash SHA-256 (hex, huruf kecil) dari `password`."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def is_configured() -> bool:
    """True bila hash kata sandi lokal tersedia dan valid (64 karakter hex)."""
    return bool(re.fullmatch(r'[0-9a-f]{64}', PASSWORD_SHA256.strip().lower()))


def verify_password(password: str) -> bool:
    """True bila `password` cocok dengan hash lokal.

    Bila hash lokal tidak tersedia, selalu False (aplikasi terkunci).
    """
    if not is_configured():
        return False
    try:
        return hmac.compare_digest(hash_password(password),
                                   PASSWORD_SHA256.strip().lower())
    except Exception:
        return False
