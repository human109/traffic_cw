"""DBF 헤더(필드 목록)와 앞 몇 개 레코드를 출력한다. 표준 라이브러리만 사용.

사용: python -I dbf_header.py <dbf경로> [레코드수] [인코딩]
"""
from __future__ import annotations

import struct
import sys


def read_header(f):
    head = f.read(32)
    nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
    fields = []
    while True:
        d = f.read(32)
        if d[0] == 0x0D:
            break
        name = d[:11].split(b"\x00")[0].decode("ascii")
        ftype = chr(d[11])
        flen = d[16]
        fdec = d[17]
        fields.append((name, ftype, flen, fdec))
    return nrec, hlen, rlen, fields, head[29]


def main() -> None:
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    enc = sys.argv[3] if len(sys.argv) > 3 else "cp949"
    with open(path, "rb") as f:
        nrec, hlen, rlen, fields, ldid = read_header(f)
        print(f"records={nrec} header_len={hlen} record_len={rlen} language_driver=0x{ldid:02x}")
        for fd in fields:
            print("  ", fd)
        f.seek(hlen)
        for _ in range(n):
            rec = f.read(rlen)
            pos = 1
            out = {}
            for name, _t, flen, _d in fields:
                out[name] = rec[pos:pos + flen].decode(enc, errors="replace").strip()
                pos += flen
            print(out)


if __name__ == "__main__":
    main()
