#!/usr/bin/env python3
"""AdvPrint Pro - CRX3 pack/reader library (shipped in the tree).

The release build packs the extension into a signed .crx with the
STABLE release key (extension-signing/advprint-printer.pem), so the
extension ID never changes and Chrome's force-install policy can
silently update the extension on every release.

Format (verified byte-for-byte against Chrome's own --pack-extension
output for the same key - see scripts/verify_crx3.py):

  file   = "Cr24" + LE32(3) + LE32(header_len) + header + zip
  header = CrxFileHeader{
             sha256_with_rsa[0] = AsymmetricKeyProof{        # field 2
               public_key = <SPKI DER>,                      # field 1
               signature  = RSA-PKCS1v15-SHA256(             # field 2
                 b"CRX3 SignedData\\0" + LE32(len(shd)) + shd + zip) },
             signed_header_data = SignedData{crx_id=<raw16>} }  # 10000
  ID     = sha256(SPKI)[0:16] -> every hex NIBBLE mapped to a..p

Reading (crx_info / crx_id_from_raw) is pure stdlib; packing needs
`cryptography` (pip install cryptography) for the RSA signature.

CLI:
  python3 tool/crx3.py --gen-key <pem>
  python3 tool/crx3.py pack <src dir> <key pem> <out crx>
  python3 tool/crx3.py info <crx>
"""
import hashlib
import io
import json
import os
import struct
import zipfile

CRX_MAGIC = b"Cr24"
CRX_VERSION = 3
SIGNATURE_CONTEXT = b"CRX3 SignedData\x00"


# ------------------------------------------------------------- protobuf
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field, wire):
    return _varint((field << 3) | wire)


def _pb_bytes(field, data):
    return _tag(field, 2) + _varint(len(data)) + data


def _read_varint(buf, i):
    shift = val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7


def _pb_fields(buf):
    out = {}
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        fn, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, i = _read_varint(buf, i)
            out.setdefault(fn, []).append(buf[i:i + ln])
            i += ln
        elif wt == 0:
            v, i = _read_varint(buf, i)
            out.setdefault(fn, []).append(v)
        else:
            raise ValueError("unexpected wire type %d" % wt)
    return out


# ------------------------------------------------------------- id utils
def crx_id_from_raw(raw16):
    """16 raw bytes -> 32-letter extension ID (a..p per hex nibble)."""
    return "".join(chr(n + ord("a")) for b in raw16
                   for n in (b >> 4, b & 0x0F))


def crx_id_from_spki(spki_der):
    """sha256(SPKI)[0:16] -> extension ID."""
    return crx_id_from_raw(hashlib.sha256(spki_der).digest()[:16])


def spki_from_private_pem(pem_bytes):
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)


def generate_key_pair(pem_path):
    """Create the signing key. Call ONCE, keep the file forever."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    d = os.path.dirname(os.path.abspath(pem_path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(pem_path, "wb") as f:
        f.write(pem)
    os.chmod(pem_path, 0o600)
    return pem


# ------------------------------------------------------------- packing
def deterministic_zip(src_dir):
    """Zip the extension dir - sorted entries, fixed timestamp."""
    files = []
    for root, _dirs, names in os.walk(src_dir):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            files.append(rel)
    files.sort()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(src_dir, rel), "rb") as f:
                zf.writestr(info, f.read())
    return buf.getvalue()


def pack_crx(src_dir, key_pem_path, out_path):
    """Pack src_dir into a CRX3 file with the stable key. Returns the ID."""
    zip_bytes = deterministic_zip(src_dir)
    pem = open(key_pem_path, "rb").read()
    spki = spki_from_private_pem(pem)
    ext_id = crx_id_from_spki(spki)

    signed_header_data = _pb_bytes(
        1, hashlib.sha256(spki).digest()[:16])

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(pem, password=None)
    blob = (SIGNATURE_CONTEXT + struct.pack("<I", len(signed_header_data))
            + signed_header_data + zip_bytes)
    signature = key.sign(blob, padding.PKCS1v15(), hashes.SHA256())

    proof = (_pb_bytes(1, spki) + _pb_bytes(2, signature))
    header = (_tag(2, 2) + _varint(len(proof)) + proof
              + _pb_bytes(10000, signed_header_data))

    d = os.path.dirname(os.path.abspath(out_path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(CRX_MAGIC + struct.pack("<II", CRX_VERSION, len(header))
                + header + zip_bytes)
    return ext_id


# ------------------------------------------------------------- reading
def crx_info(crx_path):
    """Parse a .crx -> {'extension_id','version','spki','zip_bytes'}.
    Pure stdlib - no signature verification (Chrome verifies)."""
    data = open(crx_path, "rb").read()
    if data[:4] != CRX_MAGIC:
        raise ValueError("not a CRX file: %s" % crx_path)
    _ver, hlen = struct.unpack("<II", data[4:12])
    header = data[12:12 + hlen]
    zip_bytes = data[12 + hlen:]
    fields = _pb_fields(header)
    raw_id = _pb_fields(fields[10000][0])[1][0]
    proof = _pb_fields(fields[2][0])
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        version = json.loads(
            zf.read("manifest.json").decode("utf-8")).get("version", "?")
    return {"extension_id": crx_id_from_raw(raw_id),
            "version": version,
            "spki": proof[1][0],
            "zip_bytes": zip_bytes}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AdvPrint Pro CRX3 tool")
    ap.add_argument("--gen-key", metavar="PEM")
    ap.add_argument("cmd", nargs="?", choices=("pack", "info"))
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.gen_key:
        generate_key_pair(a.gen_key)
        print("key written:", a.gen_key)
        print("EXTENSION ID:", crx_id_from_spki(
            spki_from_private_pem(open(a.gen_key, "rb").read())))
        print("NEVER regenerate - the ID is derived from this file.")
    elif a.cmd == "pack":
        if len(a.args) != 3:
            ap.error("pack <src dir> <key pem> <out crx>")
        eid = pack_crx(a.args[0], a.args[1], a.args[2])
        print("packed:", a.args[2])
        print("extension_id:", eid)
    elif a.cmd == "info":
        if len(a.args) != 1:
            ap.error("info <crx>")
        info = crx_info(a.args[0])
        print("extension_id:", info["extension_id"])
        print("version:", info["version"])
    else:
        ap.error("use --gen-key, or pack/info")
