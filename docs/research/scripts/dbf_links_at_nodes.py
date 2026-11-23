"""R-09 보조: 지정 노드에 접한 모든 링크를 MOCT_LINK.dbf에서 직접 찾아 출력한다(탐색용).

사용: python -I dbf_links_at_nodes.py <NODELINKDATA 디렉터리> <출력 텍스트> <NODE_ID,...>
표준 라이브러리만 사용한다. 원본 파일은 읽기만 한다. 전국 DBF 1회 순회(수 분).
"""
import struct
import sys

ENC = "cp949"


def main() -> None:
    base, out_path, ids_arg = sys.argv[1], sys.argv[2], sys.argv[3]
    targets = set(ids_arg.split(","))
    path = f"{base}/MOCT_LINK.dbf"
    hits = []
    with open(path, "rb") as f:
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
        for i in range(nrec):
            rec = f.read(rlen)
            fn = rec[pos["F_NODE"][0]:pos["F_NODE"][1]].decode("ascii").strip()
            tn = rec[pos["T_NODE"][0]:pos["T_NODE"][1]].decode("ascii").strip()
            if fn in targets or tn in targets:
                hits.append({
                    "LINK_ID": rec[pos["LINK_ID"][0]:pos["LINK_ID"][1]].decode("ascii").strip(),
                    "F_NODE": fn, "T_NODE": tn,
                    "ROAD_NAME": rec[pos["ROAD_NAME"][0]:pos["ROAD_NAME"][1]].decode(ENC, "replace").strip(),
                    "ROAD_TYPE": rec[pos["ROAD_TYPE"][0]:pos["ROAD_TYPE"][1]].decode("ascii").strip(),
                    "LANES": rec[pos["LANES"][0]:pos["LANES"][1]].decode("ascii").strip(),
                    "MAX_SPD": rec[pos["MAX_SPD"][0]:pos["MAX_SPD"][1]].decode("ascii").strip(),
                    "LENGTH": rec[pos["LENGTH"][0]:pos["LENGTH"][1]].decode("ascii").strip(),
                    "ROAD_USE": rec[pos["ROAD_USE"][0]:pos["ROAD_USE"][1]].decode("ascii").strip(),
                })
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"레코드 {nrec}개 중 대상 노드 접속 링크 {len(hits)}개\n")
        for h in sorted(hits, key=lambda x: (x["F_NODE"], x["LINK_ID"])):
            out.write(f"{h['LINK_ID']} {h['F_NODE']} -> {h['T_NODE']} {h['ROAD_NAME']} "
                      f"len={h['LENGTH']} rt={h['ROAD_TYPE']} lanes={h['LANES']} "
                      f"spd={h['MAX_SPD']} use={h['ROAD_USE']}\n")
    print("written", out_path, len(hits))


if __name__ == "__main__":
    main()
