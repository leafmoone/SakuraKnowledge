"""Throwaway probe: derive Python reference behavior for the expanded case set.

Produces tools/_probe.json with per-case python outcome (value or error).
Not committed: the final expectations are reviewed and locked into
tools/check_parity.py by hand.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sakura_knowledge.api import Knowledge

DB = ROOT / "build" / "snapshot-full-20bf5b3" / "knowledge.sqlite"

# (cid, op, args, expect-note). expect is derived here, locked by review.
CASES = [
    # ---------------- lookup by value (30)
    ("L01", "lookup", {"query": "975"}, None),
    ("L02", "lookup", {"query": "975", "kind": "character", "namespace": "bangumi.character"}, None),
    ("L03", "lookup", {"query": "975", "kind": "episode", "namespace": "bangumi.episode"}, None),
    ("L04", "lookup", {"query": "47"}, None),
    ("L05", "lookup", {"query": "10"}, None),
    ("L06", "lookup", {"query": "100"}, None),
    ("L07", "lookup", {"query": "11"}, None),
    ("L08", "lookup", {"query": "12377"}, None),
    ("L09", "lookup", {"query": "12377", "kind": "page", "namespace": "danbooru.wiki"}, None),
    ("L10", "lookup", {"query": "06娘"}, None),
    ("L11", "lookup", {"query": "10086娘"}, None),
    ("L12", "lookup", {"query": '"加特"'}, None),
    ("L13", "lookup", {"query": '"加特"', "kind": "character", "namespace": "moegirl.character"}, None),
    ("L14", "lookup", {"query": '"白"'}, None),
    ("L15", "lookup", {"query": "碧蓝航线:埃塞克斯"}, None),
    ("L16", "lookup", {"query": "小早川美幸"}, None),
    ("L17", "lookup", {"query": "拉碧丝拉斯莉"}, None),
    ("L18", "lookup", {"query": "杰姆"}, None),
    ("L19", "lookup", {"query": "斯科特·朗"}, None),
    ("L20", "lookup", {"query": "楚晚宁"}, None),
    ("L21", "lookup", {"query": "Wheel of fortune娘"}, None),
    ("L22", "lookup", {"query": "主人公(真·女神转生III)"}, None),
    ("L23", "lookup", {"query": "SCP-3812"}, None),
    ("L24", "lookup", {"query": "可儿江西也"}, None),
    ("L25", "lookup", {"query": "岚山步鸟"}, None),
    ("L26", "lookup", {"query": "definitely_missing_xyz_9271"}, None),
    ("L27", "lookup", {"query": "不存在的实体九二七幺"}, None),
    ("L28", "lookup", {"query": "74965"}, None),
    ("L29", "lookup", {"query": "285079"}, None),
    ("L30", "lookup", {"query": "172854"}, None),
    # ---------------- lookup by key (12)
    ("K01", "lookup_key", {"kind": "character", "namespace": "bangumi.character", "value": "975"}, None),
    ("K02", "lookup_key", {"kind": "episode", "namespace": "bangumi.episode", "value": "1128648"}, None),
    ("K03", "lookup_key", {"kind": "subject", "namespace": "bangumi.subject", "value": "1"}, None),
    ("K04", "lookup_key", {"kind": "tag", "namespace": "local.tag_aggregate", "value": "!"}, None),
    ("K05", "lookup_key", {"kind": "tag", "namespace": "local.tag_aggregate", "value": "!!"}, None),
    ("K06", "lookup_key", {"kind": "tag", "namespace": "local.tag_aggregate", "value": "a-cat"}, None),
    ("K07", "lookup_key", {"kind": "page", "namespace": "danbooru.wiki", "value": "85717"}, None),
    ("K08", "lookup_key", {"kind": "character", "namespace": "moegirl.character", "value": '"锁芯"'}, None),
    ("K09", "lookup_key", {"kind": "person", "namespace": "bangumi.person", "value": "74965"}, None),
    ("K10", "lookup_key", {"kind": "character", "namespace": "bangumi.character", "value": "92244"}, None),
    ("K11", "lookup_key", {"kind": "character", "namespace": "bangumi.character", "value": "nope_missing_9271"}, None),
    ("K12", "lookup_key", {"kind": "subject", "namespace": "moegirl.category", "value": "nope_missing_9271"}, None),
    # ---------------- alias resolution (12)
    ("A01", "lookup", {"query": " 轮初音"}, None),
    ("A02", "lookup", {"query": "!初始"}, None),
    ("A03", "lookup", {"query": '"Fightin\'est Ship in The Fleet"舰队中最能打的船'}, None),
    ("A04", "lookup", {"query": '"Mecha Freak"机械妖怪'}, None),
    ("A05", "lookup", {"query": '"不死鸟"'}, None),
    ("A06", "lookup", {"query": '"制裁女巫之锤黄昏型号“'}, None),
    ("A07", "lookup", {"query": '"国境"杰姆'}, None),
    ("A08", "lookup", {"query": '"好斗的玛丽"'}, None),
    ("A09", "lookup", {"query": '"巨"蚁人GiantMan'}, None),
    ("A10", "lookup", {"query": '"心锁"'}, None),
    ("A11", "lookup", {"query": "A Reyvateil's Melody"}, None),
    ("A12", "lookup", {"query": "A THIRD DIMENSION"}, None),
    # ---------------- search (20)
    ("S01", "search", {"query": "ONE PIECE", "topk": 20}, None),
    ("S02", "search", {"query": "ONE PIECE", "topk": 20, "kind": "episode"}, None),
    ("S03", "search", {"query": "ONE PIECE", "topk": 1}, None),
    ("S04", "search", {"query": "ONE PIECE", "topk": 100}, None),
    ("S05", "search", {"query": "!!", "topk": 20}, None),
    ("S06", "search", {"query": "独", "topk": 20}, None),
    ("S07", "search", {"query": "孤独摇滚", "topk": 5}, None),
    ("S08", "search", {"query": "美坂栞", "topk": 10}, None),
    ("S09", "search", {"query": "山田一郎", "topk": 10}, None),
    ("S10", "search", {"query": "重装兵", "topk": 10}, None),
    ("S11", "search", {"query": "鲁路修", "topk": 10}, None),
    ("S12", "search", {"query": "heavy", "topk": 10}, None),
    ("S13", "search", {"query": "macross galaxy", "topk": 10}, None),
    ("S14", "search", {"query": "碧蓝航线", "topk": 10, "kind": "character"}, None),
    ("S15", "search", {"query": "碧蓝航线", "topk": 10, "kind": "page", "namespace": "danbooru.wiki"}, None),
    ("S16", "search", {"query": "zzzqqxwvu 9271", "topk": 10}, None),
    ("S17", "search", {"query": "不存在的检索词九二七幺", "topk": 10}, None),
    ("S18", "search", {"query": "a's_wonderland", "topk": 10}, None),
    ("S19", "search", {"query": "heavy", "topk": 20, "kind": "character"}, None),
    ("S20", "search", {"query": "06娘", "topk": 10}, None),
    # ---------------- related (14)
    ("R01", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "1", "limit": 20}, None),
    ("R02", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "4", "limit": 20}, None),
    ("R03", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "7", "limit": 1}, None),
    ("R04", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "7", "limit": 100}, None),
    ("R05", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "975", "limit": 20}, None),
    ("R06", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "8", "limit": 20, "relation": "credit_person"}, None),
    ("R07", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "8", "limit": 20, "relation": "entity_tag"}, None),
    ("R08", "related", {"kind": "character", "namespace": "bangumi.character", "value": "172854", "limit": 20}, None),
    ("R09", "related", {"kind": "character", "namespace": "bangumi.character", "value": "92244", "limit": 20}, None),
    ("R10", "related", {"kind": "person", "namespace": "bangumi.person", "value": "32561", "limit": 20}, None),
    ("R11", "related", {"kind": "character", "namespace": "moegirl.character", "value": '"加特"', "limit": 20}, None),
    ("R12", "related", {"kind": "tag", "namespace": "local.tag_aggregate", "value": "a-cat", "limit": 20}, None),
    ("R13", "related", {"kind": "character", "namespace": "bangumi.character", "value": "nope_missing_9271", "limit": 20}, None),
    ("R14", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "6", "limit": 20, "kind_filter": "person"}, None),
    # ---------------- ask (30)
    ("Q01", "ask", {"query": "975"}, None),
    ("Q02", "ask", {"query": "975", "kind": "character", "namespace": "bangumi.character"}, None),
    ("Q03", "ask", {"query": "10", "kind": "page", "namespace": "danbooru.wiki"}, None),
    ("Q04", "ask", {"query": "!", "kind": "tag", "namespace": "local.tag_aggregate"}, None),
    ("Q05", "ask", {"query": "a-cat", "kind": "tag", "namespace": "local.tag_aggregate"}, None),
    ("Q06", "ask", {"query": "a-cat", "kind": "tag", "namespace": "local.tag_aggregate", "target_tag_namespace": "danbooru.tag"}, None),
    ("Q07", "ask", {"query": "加特 的标签是什么"}, None),
    ("Q08", "ask", {"query": "碧蓝航线:埃塞克斯 的标签是什么"}, None),
    ("Q09", "ask", {"query": "小早川美幸 的标签是什么"}, None),
    ("Q10", "ask", {"query": "杰姆 的标签是什么"}, None),
    ("Q11", "ask", {"query": "楚晚宁 的标签是什么"}, None),
    ("Q12", "ask", {"query": "SCP-3812 的标签是什么"}, None),
    ("Q13", "ask", {"query": "不存在的实体九二七幺 的标签是什么"}, None),
    ("Q14", "ask", {"query": "975 的标签是什么"}, None),
    ("Q15", "ask", {"query": "10 的标签是什么"}, None),
    ("Q16", "ask", {"query": "孤独摇滚 的 Danbooru tag 是什么"}, None),
    ("Q17", "ask", {"query": "加特 的 Danbooru tag 是什么"}, None),
    ("Q18", "ask", {"query": "碧蓝航线:响 的 Danbooru tag 是什么"}, None),
    ("Q19", "ask", {"query": "975 的 Danbooru tag 是什么"}, None),
    ("Q20", "ask", {"query": "975 的 Danbooru tag 是什么", "kind": "character", "namespace": "bangumi.character"}, None),
    ("Q21", "ask", {"query": "介绍一下 975"}, None),
    ("Q22", "ask", {"query": "介绍 975"}, None),
    ("Q23", "ask", {"query": "介绍一下 碧蓝航线:埃塞克斯"}, None),
    ("Q24", "ask", {"query": "介绍一下 加特"}, None),
    ("Q25", "ask", {"query": "介绍一下 不存在的实体九二七幺"}, None),
    ("Q26", "ask", {"query": "介绍一下 10"}, None),
    ("Q27", "ask", {"query": "介绍一下 975", "kind": "character", "namespace": "bangumi.character"}, None),
    ("Q28", "ask", {"query": "solo 的 Danbooru tag 是什么"}, None),
    ("Q29", "ask", {"query": "xyzzy 不支持的自由文本 9271"}, None),
    ("Q30", "ask", {"query": "what is the tag of hero"}, None),
    # ---------------- unsupported/edge ask (12)
    ("U01", "ask", {"query": " 的标签是什么"}, None),
    ("U02", "ask", {"query": " 的 Danbooru tag 是什么"}, None),
    ("U03", "ask", {"query": "  的标签是什么"}, None),
    ("U04", "ask", {"query": "加特  的标签是什么"}, None),
    ("U05", "ask", {"query": "加特 的标签是什么？"}, None),
    ("U06", "ask", {"query": "介绍一下 975 的标签是什么"}, None),
    ("U07", "ask", {"query": "介绍一下"}, None),
    ("U08", "ask", {"query": "介绍一下 975。"}, None),
    ("U09", "ask", {"query": "975 的"}, None),
    ("U10", "ask", {"query": "975的标签是什么"}, None),
    ("U11", "ask", {"query": "介绍一下 介绍一下"}, None),
    ("U12", "ask", {"query": "丹 的标签是什么"}, None),
    # ---------------- validation/CLI errors (18)
    ("E01", "lookup", {"query": ""}, "both-error"),
    ("E02", "lookup", {"query": "x" * 4097}, "both-error"),
    ("E03", "lookup", {"query": "x" * 4096}, "long-but-valid-or-both-error"),
    ("E04", "search", {"query": "one piece", "topk": 0}, "both-error"),
    ("E05", "search", {"query": "one piece", "topk": 101}, "both-error"),
    ("E06", "search", {"query": "x" * 4097, "topk": 20}, "both-error"),
    ("E07", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "1", "limit": 0}, "both-error"),
    ("E08", "related", {"kind": "subject", "namespace": "bangumi.subject", "value": "1", "limit": 101}, "both-error"),
    ("E09", "ask", {"query": "975", "target_tag_namespace": ""}, "both-error"),
    ("E10", "ask", {"query": "975", "target_tag_namespace": "x" * 257}, "both-error"),
    ("E11", "ask", {"query": "介绍一下 975", "target_tag_namespace": "danbooru.tag"}, "both-error"),
    ("E12", "ask", {"query": "975 的 Danbooru tag 是什么", "target_tag_namespace": "local.tag_aggregate"}, "both-error"),
    ("E13", "lookup_key", {"kind": "character", "namespace": "bangumi.character", "value": ""}, "both-error-or-notfound"),
    ("E14", "cli_key_missing", {"key_only": "value"}, "both-error"),
    ("E15", "cli_unknown_op", {"op": "frobnicate"}, "both-error"),
    ("E16", "cli_missing_db", {"op": "lookup"}, "both-error"),
    ("E17", "open_missing_db", {}, "both-error-runtime"),
    ("E18", "inspect", {}, None),
]


def main() -> int:
    out = {}
    for cid, op, args, note in CASES:
        entry = {"op": op, "args": args, "note": note}
        if op == "inspect":
            with Knowledge(DB) as api:
                entry["python"] = {"value": api.inspect()}
            out[cid] = entry
            continue
        if op.startswith("cli_") or op == "open_missing_db":
            out[cid] = entry
            continue
        with Knowledge(DB) as api:
            t0 = time.monotonic()
            try:
                if op == "lookup":
                    v = api.lookup(args["query"], kind=args.get("kind"),
                                   namespace=args.get("namespace"))
                elif op == "lookup_key":
                    v = api.lookup(key={"kind": args["kind"], "namespace": args["namespace"],
                                        "value": args["value"]})
                elif op == "search":
                    v = api.search(args["query"], topk=args.get("topk", 20),
                                   kind=args.get("kind"), namespace=args.get("namespace"))
                elif op == "related":
                    v = api.related({"kind": args["kind"], "namespace": args["namespace"],
                                     "value": args["value"]},
                                    relation=args.get("relation"),
                                    kind=args.get("kind_filter"), limit=args.get("limit", 20))
                elif op == "ask":
                    v = api.ask(args["query"], kind=args.get("kind"),
                                namespace=args.get("namespace"),
                                target_tag_namespace=args.get("target_tag_namespace"))
                else:
                    raise ValueError(op)
                entry["python"] = {"value": v,
                                   "elapsed_s": round(time.monotonic() - t0, 3)}
            except ValueError as e:
                entry["python"] = {"error": str(e),
                                   "elapsed_s": round(time.monotonic() - t0, 3)}
        out[cid] = entry
        print(cid, op,
              (out[cid]["python"].get("value") or {}).get("status")
              if isinstance(out[cid]["python"], dict) and "value" in out[cid]["python"]
              else out[cid]["python"].get("error"), flush=True)
    with open(Path(__file__).with_name("_probe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
