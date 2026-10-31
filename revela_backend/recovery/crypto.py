"""Versioned RSA-OAEP/SHA256 + streaming AES-256-GCM envelope.

Only the public RSA key is needed on the live server. The authenticated header
contains no records. The private key belongs in the municipality's separate vault.
"""
import base64
import hashlib
import json
import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"REVELA-BACKUP-1\n"
CHUNK = 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                        algorithm=hashes.SHA256(), label=None)


def encrypt(source, destination, public_key_file):
    key = serialization.load_pem_public_key(Path(public_key_file).read_bytes())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError("A 3072-bit or stronger RSA public key is required")
    secret, nonce = os.urandom(32), os.urandom(12)
    header = json.dumps({
        "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
        "wrapped_key": base64.b64encode(key.encrypt(secret, _oaep())).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "key_id": hashlib.sha256(key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),
    }, sort_keys=True).encode()
    prefix = MAGIC + struct.pack(">I", len(header)) + header
    cipher = Cipher(algorithms.AES(secret), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(prefix)
    with open(source, "rb") as src, open(destination, "xb") as dst:
        dst.write(prefix)
        for chunk in iter(lambda: src.read(CHUNK), b""):
            dst.write(cipher.update(chunk))
        dst.write(cipher.finalize())
        dst.write(cipher.tag)


def decrypt(source, destination, private_key_file, password=None):
    key = serialization.load_pem_private_key(Path(private_key_file).read_bytes(), password=password)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
        raise ValueError("Invalid recovery private key")
    created = False
    try:
        with open(source, "rb") as src:
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError("Unknown backup format")
            size_bytes = src.read(4)
            size = struct.unpack(">I", size_bytes)[0]
            if not 1 <= size <= 16384:
                raise ValueError("Invalid backup header")
            raw = src.read(size)
            header = json.loads(raw)
            if header["algorithm"] != "RSA-OAEP-SHA256+AES-256-GCM":
                raise ValueError("Unknown backup encryption")
            secret = key.decrypt(base64.b64decode(header["wrapped_key"], validate=True), _oaep())
            nonce = base64.b64decode(header["nonce"], validate=True)
            prefix = MAGIC + size_bytes + raw
            remaining = Path(source).stat().st_size - len(prefix) - 16
            if remaining < 0 or len(secret) != 32 or len(nonce) != 12:
                raise ValueError("Truncated backup")
            src.seek(-16, 2)
            tag = src.read(16)
            src.seek(len(prefix))
            cipher = Cipher(algorithms.AES(secret), modes.GCM(nonce, tag)).decryptor()
            cipher.authenticate_additional_data(prefix)
            with open(destination, "xb") as dst:
                created = True
                while remaining:
                    chunk = src.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ValueError("Truncated backup")
                    remaining -= len(chunk)
                    dst.write(cipher.update(chunk))
                dst.write(cipher.finalize())
    except Exception:
        # Never leave unauthenticated plaintext for an operator to restore.
        if created:
            Path(destination).unlink(missing_ok=True)
        raise
