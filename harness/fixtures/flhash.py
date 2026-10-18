"""Freelancer nickname hashes (our own implementation, stdlib only).

- create_id(s)            -> u32  Common.dll CreateID: nickname / object / system / base / save-name hash.
- make_id(s)              -> u16  Common.dll MakeId: reputation-group (faction) id.
- make_location_id(b, r)  -> u32  Common.dll MakeLocationID: CreateID("%X_%s" % (base_id, room)).

Algorithms as documented in R3 §10 (Librelancer FLHash / FLHookSDK CommonMethods). CreateID lower-cases ASCII
before hashing; MakeId is a CRC-16/CCITT table 0x0000, 0x1021, 0x2042 ... applied LSB-first from 0xFFFF;
MakeLocationID formats the base id with "%X". Further reference sources: see harness/NOTES.md N12.

Run directly to print the hashes of the arguments:  flhash.py Li01_to_Li02 Br05
"""
import sys

_CREATE_ID_POLY = 0xA001 << 14  # the reflected polynomial the reference implementation uses


def _build_create_id_table():
    table = []
    for i in range(256):
        x = i
        for _ in range(8):
            x = (x >> 1) ^ _CREATE_ID_POLY if x & 1 else x >> 1
        table.append(x & 0xFFFFFFFF)
    return table


def _build_make_id_table():
    table = []
    for i in range(256):
        w = i << 8
        for _ in range(8):
            w = ((w << 1) ^ 0x1021) if (w & 0x8000) else (w << 1)
            w &= 0xFFFF
        table.append(w)
    return table


_CREATE_ID_TABLE = _build_create_id_table()
_MAKE_ID_TABLE = _build_make_id_table()


def _ascii_lower_bytes(s):
    """Bytes of s, ASCII-lower-cased (the game lower-cases a char buffer with _strlwr / its own loop)."""
    if isinstance(s, (bytes, bytearray)):
        b = bytes(s)
    else:
        b = s.encode("latin-1")
    return bytes((c + 32) if 65 <= c <= 90 else c for c in b)


def create_id(s):
    """CreateID(const char*) -> u32."""
    h = 0
    for c in _ascii_lower_bytes(s):
        h = (h >> 8) ^ _CREATE_ID_TABLE[(h & 0xFF) ^ c]
    h &= 0xFFFFFFFF
    h = int.from_bytes(h.to_bytes(4, "little"), "big")  # byte swap
    return ((h >> 2) | 0x80000000) & 0xFFFFFFFF


def make_id(s):
    """MakeId(const char*) -> u16 (faction / reputation group id). Not the same as create_id."""
    crc = 0xFFFF
    for c in _ascii_lower_bytes(s):
        crc = (_MAKE_ID_TABLE[(crc & 0xFF) ^ c] ^ (crc >> 8)) & 0xFFFF
    return crc


# Alias with the name used in the research notes.
fac_hash = make_id


def make_location_id(base, room):
    """MakeLocationID(base_id, room) = CreateID("%X_%s"). `base` may be a nickname or an already-hashed id."""
    base_id = create_id(base) if isinstance(base, str) else int(base)
    return create_id("%X_%s" % (base_id, room))


def main(argv):
    for a in argv:
        print("%s create_id=%u make_id=%u" % (a, create_id(a), make_id(a)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
