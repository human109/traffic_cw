"""R-09 보조: MOCT_NODE.dbf에서 지정 노드 ID의 이름·좌표를 찾아 출력한다(탐색용).

사용: python -I dbf_nodes_by_id.py <NODELINKDATA 디렉터리> <출력 텍스트> <NODE_ID,...>
표준 라이브러리만 사용한다. 원본 파일은 읽기만 한다.
"""
import struct
import sys

ENC = "cp949"


def main() -> None:
    base, out_path, ids_arg = sys.argv[1], sys.argv[2], sys.argv[3]
    targets = set(ids_arg.split(","))
    found = {}
    with open(f"{base}/MOCT_NODE.dbf", "rb") as f:
        head = f.read(32)
        nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b"\x00")[0].decode("ascii"), d[16]))
        offs = []
        acc = 1
        for _n, flen in fields:
            offs.append((_n, acc, acc + flen))
            acc += flen
        pos = {n: (a, b) for n, a, b in offs}
        f.seek(hlen)
        for _ in range(nrec):
            rec = f.read(rlen)
            nid = rec[1:11].decode("ascii").strip()
            if nid in targets:
                found[nid] = {
                    "NODE_TYPE": rec[pos["NODE_TYPE"][0]:pos["NODE_TYPE"][1]].decode("ascii").strip(),
                    "NODE_NAME": rec[pos["NODE_NAME"][0]:pos["NODE_NAME"][1]].decode(ENC, "replace").strip(),
                }
    with open(out_path, "w", encoding="utf-8") as out:
        for nid in sorted(targets):
            h = found.get(nid)
            out.write(f"{nid} {h['NODE_NAME'] if h else '(없음)'} type={h['NODE_TYPE'] if h else '?'}\n")
    print("written", out_path, len(found))


if __name__ == "__main__":
    main()
