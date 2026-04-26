"""Burial mode: seal raw agent remains in an encrypted, secret-scrubbed archive.

Pipeline:
    1. Scanner declares which files to include (`gather_burial_files`).
    2. This module enforces a defensive denylist (HARD_DENY_BASENAMES) — even
       a buggy scanner can't leak `.env` or `auth.json` past it.
    3. Text-format configs are scrubbed for embedded secret patterns.
    4. Files are tar+gzip'd in memory.
    5. Compressed bytes are encrypted with AES-256-GCM, key derived from the
       passphrase via scrypt.

The encrypted blob and its KDF metadata both live inside the .tomb (zip).
Without the passphrase, the burial cannot be exhumed.
"""
from __future__ import annotations

import io
import os
import re
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Files that must NEVER end up in a burial archive, regardless of what the
# scanner declares. Defense in depth.
HARD_DENY_BASENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "auth.json",
        "auth.lock",
        "credentials.json",
        ".credentials",
        "id_rsa",
        "id_ed25519",
        ".pgpass",
        ".netrc",
    }
)

# Redact `key: <long string>` style lines inside text configs before sealing.
SECRET_LINE_PATTERN = re.compile(
    rb"(?im)^(\s*[\w.-]*?(api[_-]?key|secret|token|password|bearer|access[_-]?key)[\w.-]*?\s*[:=]\s*)"
    rb"['\"]?[A-Za-z0-9+/=_\-]{16,}['\"]?",
)

TEXT_CONFIG_SUFFIXES = (".yaml", ".yml", ".json", ".toml", ".ini", ".conf", ".env")

KDF_N = 2 ** 15
KDF_R = 8
KDF_P = 1
KDF_KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16


@dataclass
class BurialMeta:
    kdf: str
    salt_hex: str
    n: int
    r: int
    p: int
    nonce_hex: str
    file_count: int
    bytes_uncompressed: int
    bytes_compressed: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_burial(
    files: Iterable[tuple[str, Path]],
    passphrase: str,
) -> tuple[bytes, BurialMeta]:
    """Tar+gzip the given files, scrub secrets, encrypt with AES-GCM.

    Returns (ciphertext, meta). Caller writes both into the .tomb.
    """
    if not passphrase:
        raise ValueError("passphrase is required for burial")

    tar_bytes, file_count, raw_size = _build_tar_gz(files)
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(passphrase.encode("utf-8"), salt)
    ciphertext = AESGCM(key).encrypt(nonce, tar_bytes, associated_data=None)

    meta = BurialMeta(
        kdf="scrypt",
        salt_hex=salt.hex(),
        n=KDF_N,
        r=KDF_R,
        p=KDF_P,
        nonce_hex=nonce.hex(),
        file_count=file_count,
        bytes_uncompressed=raw_size,
        bytes_compressed=len(tar_bytes),
    )
    return ciphertext, meta


def open_burial(
    ciphertext: bytes,
    meta: dict,
    passphrase: str,
    output_dir: Path,
) -> int:
    """Decrypt the burial archive and extract its contents into output_dir.

    Returns the number of files extracted. Raises cryptography's InvalidTag
    on wrong passphrase or tampering.
    """
    salt = bytes.fromhex(meta["salt_hex"])
    nonce = bytes.fromhex(meta["nonce_hex"])
    key = Scrypt(
        salt=salt,
        length=KDF_KEY_LEN,
        n=int(meta["n"]),
        r=int(meta["r"]),
        p=int(meta["p"]),
    ).derive(passphrase.encode("utf-8"))
    tar_bytes = AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
    return _safe_extract_tar_gz(tar_bytes, output_dir)


def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    return Scrypt(
        salt=salt, length=KDF_KEY_LEN, n=KDF_N, r=KDF_R, p=KDF_P
    ).derive(passphrase)


def _build_tar_gz(files: Iterable[tuple[str, Path]]) -> tuple[bytes, int, int]:
    out = io.BytesIO()
    n = 0
    raw_total = 0
    with tarfile.open(fileobj=out, mode="w:gz", compresslevel=6) as tar:
        for arc_path, fs_path in files:
            base = Path(arc_path).name
            if base in HARD_DENY_BASENAMES:
                continue
            if not fs_path.is_file():
                continue
            data = fs_path.read_bytes()
            raw_total += len(data)
            if _is_text_config(base):
                data = SECRET_LINE_PATTERN.sub(rb"\1<REDACTED>", data)
            info = tarfile.TarInfo(name=arc_path)
            info.size = len(data)
            try:
                info.mtime = int(fs_path.stat().st_mtime)
            except OSError:
                pass
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
            n += 1
    return out.getvalue(), n, raw_total


def _is_text_config(basename: str) -> bool:
    lower = basename.lower()
    return any(lower.endswith(suffix) for suffix in TEXT_CONFIG_SUFFIXES)


def _safe_extract_tar_gz(tar_bytes: bytes, output_dir: Path) -> int:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                continue
            target = (output_dir / member.name).resolve()
            try:
                target.relative_to(output_dir)
            except ValueError:
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            target.write_bytes(extracted.read())
            n += 1
    return n
