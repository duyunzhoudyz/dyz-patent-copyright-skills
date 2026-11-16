"""三个作者构造的合成开发案卷；用于机制和工件检查，不是独立作答成绩。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.core import canonical_bytes, digest, sha256_bytes
from tools import documents, fidelity


def doc(identity, role, text, version="1"):
    return {"id": identity, "role": role, "version": version, "text": text,
            "sha256": sha256_bytes(text.encode("utf-8"))}


def cite(document, text):
    start = document["text"].index(text)
    return {"document_id": document["id"], "start": start, "end": start + len(text), "quote": text}


GATE = {"implies": ["archive", {"all": ["a_valid", "b_valid", "permission"]}]}
RECOVERY = {"implies": ["resume", "manual"]}
BUFFER = {"implies": ["full", {"all": ["reject_new", "retain_old"]}]}
FACTS = [
    ("F1", "记录器读取探头A与B的本轮校验结果及运行许可状态。", "reading"),
    ("F2", "归档操作只有在本轮探头A与B均有效且运行许可成立时才被允许。", GATE),
    ("F3", "探头失效恢复后，只有完成人工确认才可恢复归档控制。", RECOVERY),
    ("F4", "缓存容量B为可配置正整数，6只是示例。", {"all": ["parameter_domain", "parameter_example"]}),
    ("F5", "缓存已满时拒绝新增记录，并保留已有记录。", BUFFER),
]


def make_case(kind):
    assert kind in {"normal", "partial", "revised"}
    selected = FACTS[:2] if kind == "partial" else FACTS
    raw = "# 合成原始设计O1\n\n" + "\n\n".join(text for _, text, _ in selected)
    raw += ("\n\n未提供恢复、容量和缓存处理材料。" if kind == "partial" else
            "\n\n恢复等待期间缓存如何动作未说明；未说明未满时是否必然接收；没有真实试验或运行结果。")
    original = doc("O1", "original", raw)
    prior = doc("GIVEN", "source", "合成节选D-A：单探头有效即归档。\n合成节选D-B：双探头有效即归档，节选未写运行许可或恢复。\n二者无真实标识、全文或公开日期，仅用于给定集合技术比较。")
    atoms = [{"id": identity, "meaning": meaning, "scope": scope} for identity, meaning, scope in [
        ("reading", "读取两探头校验及许可状态", "记录器设计"),
        ("archive", "本轮归档被允许", "本轮归档事件"),
        ("a_valid", "探头A本轮校验有效", "本轮归档事件"),
        ("b_valid", "探头B本轮校验有效", "本轮归档事件"),
        ("permission", "运行许可成立", "本轮归档事件"),
        ("resume", "失效恢复后恢复归档控制", "恢复接管事件"),
        ("manual", "已完成人工确认", "恢复接管事件"),
        ("parameter_domain", "容量B为可配置正整数", "原始参数描述"),
        ("parameter_example", "6仅为一个容量示例而非固定限定", "原始参数描述"),
        ("full", "缓存已满", "本次满缓存事件"),
        ("reject_new", "拒绝新增记录", "本次满缓存事件"),
        ("retain_old", "保留已有记录", "本次满缓存事件"),
        ("waiting_hold", "等待期冻结缓存动作", "恢复等待期")]]
    atoms.append({"id": "given_comparison", "meaning": "给定节选中单探头有效及双探头有效两种归档触发关系",
                  "scope": "两份合成给定材料，不是本案实际控制事件"})
    facts = [{"id": identity, "state": "explicit", "citation": cite(original, text), "formula": formula}
             for identity, text, formula in selected]
    facts.append({"id": "T1", "state": "explicit", "citation": cite(prior, prior["text"].split('\n二者')[0]),
                  "formula": "given_comparison"})
    if kind != "partial":
        facts.append({"id": "U1", "state": "unknown", "citation": cite(original, "恢复等待期间缓存如何动作未说明"),
                      "formula": "waiting_hold"})
    # 每项包含实际文字、有限模型和所需原始关系；不是从测试答卷抄入技能。
    paragraphs = [
        ("heading1", "多探头记录归档控制方法（合成内部工作稿）", None, []),
        ("heading2", "技术领域", None, []),
        ("paragraph", "本方案涉及读取两个探头校验结果和运行许可状态的记录器。", "reading", ["F1"]),
        ("heading2", "背景技术（给定节选）", None, []),
        ("paragraph", "给定技术材料中的单探头方案在探头有效时归档，双探头方案在双探头均有效时归档。", "given_comparison", ["T1"]),
        ("heading2", "技术方案", None, []),
        ("paragraph", "记录器读取探头A与B的本轮校验结果及运行许可状态。", "reading", ["F1"]),
        ("paragraph", "归档操作只有在本轮探头A与B均有效且运行许可成立时才被允许。", GATE, ["F2"]),
        ("heading2", "权利要求候选", None, []),
        ("paragraph", "1. 一种记录归档控制方法，包括读取探头A与B的本轮校验结果及运行许可状态，其中，只有在本轮探头A与B均有效且运行许可成立时才允许归档。",
         {"all": ["reading", GATE]}, ["F1", "F2"]),
    ]
    if kind != "partial":
        paragraphs += [
            ("paragraph", "2. 根据权利要求1所述的方法，其中，探头失效恢复后，只有完成人工确认才恢复归档控制。",
             {"all": ["reading", GATE, RECOVERY]}, ["F1", "F2", "F3"]),
            ("paragraph", "3. 根据权利要求2所述的方法，其中，缓存容量B为可配置正整数；缓存已满时拒绝新增记录，并保留已有记录。",
             {"all": ["reading", GATE, RECOVERY, "parameter_domain", BUFFER]}, ["F1", "F2", "F3", "F4", "F5"])]
    paragraphs += [("heading2", "具体实施方式", None, []),
        ("paragraph", "在每轮处理中，读取探头A与B的校验结果和运行许可状态。归档操作受到本轮两探头均有效及运行许可成立的必要条件约束。",
         {"all": ["reading", GATE]}, ["F1", "F2"])]
    if kind != "partial":
        paragraphs += [
            ("paragraph", "探头从失效恢复后，完成人工确认是恢复归档控制的必要条件。", RECOVERY, ["F3"]),
            ("paragraph", "容量B是可配置正整数，以B=6示意该参数的一种取值。缓存已满时拒绝新增记录，已有记录继续保留。",
             {"all": ["parameter_domain", "parameter_example", BUFFER]}, ["F4", "F5"])]
    paragraphs += [("heading2", "摘要候选", None, []),
        ("paragraph", "本方案读取两个探头的本轮校验结果和运行许可状态，只有本轮两探头均有效且运行许可成立时才允许归档。",
         {"all": ["reading", GATE]}, ["F1", "F2"]),
        ("heading2", "约束图源", None, []),
        ("code", "归档被允许 ⇒ A本轮有效 ∧ B本轮有效 ∧ 运行许可成立", GATE, ["F2"])]
    if kind != "partial":
        paragraphs += [("code", "恢复归档控制 ⇒ 完成人工确认", RECOVERY, ["F3"]),
                       ("code", "缓存已满 ⇒ 拒绝新增记录 ∧ 保留已有记录", BUFFER, ["F5"])]
    candidate_text = "\n\n".join(text for _, text, _, _ in paragraphs) + "\n"
    candidate = doc("DRAFT", "candidate", candidate_text, "2" if kind == "revised" else "1")
    internal = """# 合成内部分析与核稿

事实只来自O1及两份给定节选，未执行真实检索、软件运行、试验或专业审阅。原始技术事实、文献比较、修改依据与行动权限分别保存。

对D-A：节选仅给单探头有效即归档，未给本案完整的双探头及许可关系；对D-B：双探头有效已经给出，不能将双探头本身称为新点。节选未写许可和恢复不等于全文不存在；无标识、全文和公开日期，只能作给定集合逐篇及组合讨论，不能判断真实新颖性或创造性。

宽路线为权项1的双有效及许可必要门槛，不限定采样周期、调度实现或缓存容量。其观察负担是取得本轮两校验结果、许可状态及归档允许行为的关联证据；界面出现字段不证明内部确实使用。D-B全文或其他材料若已有许可门槛，会削弱该路线。技术效果仅讨论明示约束，不编造准确率或性能提升。

窄路线增加恢复确认及满缓存拒新保旧。除正常门槛外，需核异常、有效恢复、人工事件、重新接管、满状态、新记录拒绝及旧记录保留；只有正常日志不够。代码／设计／获准运行证据未取得时保留取证缺口。它覆盖的实现更少，也可能被不同恢复或缓存策略绕开；更多限定不自动等于更有价值或已获支持。

当前采用权项1及有依据的后备层，不从必要条件补出条件满足就必然归档，不从未给路径补出恢复等待期冻结缓存。图只表示约束箭头，不能反读为充分触发。等待期缓存动作、未满时接收行为和真实实现仍待技术原件；不因缺这些信息删除已明确门槛。

范围、原始组合支持、目标法域形式及正式申请条件待对应专业审阅。内部正文、原文映射与本说明分离；当前仅本地合成开发，无申请、外发或公开批准。后续接收者为技术事实负责人、专利专业审阅者及文件核对角色，真实身份与权限尚未核实。
"""
    if kind == "partial":
        internal = internal.replace("当前采用权项1及有依据的后备层", "当前仅采用有依据的权项1")
        internal = internal.replace("窄路线增加恢复确认及满缓存拒新保旧。", "若后续另行取得恢复确认及满缓存拒新保旧事实，可比较如下窄路线；当前材料不支持将其写入正文。")
        internal += "\n本案只收到O1的读取与许可门槛。未取得恢复、容量及缓存原件，因此不交这些分支的从属项，也不为凑数增加后备。已完成主项、方案、实施方式、摘要和约束图；恢复所需为对应设计原文、当前图及版本关系。上文窄路线仅是待取得事实后的比较方向，不是本案已支持方案。\n"
    request_docs, requests, assessments = [], [], []
    if kind == "revised":
        request = doc("REQUEST", "source", "请评估将B具体化为10，并讨论缓存满时清空旧记录的修改；产品负责人只确认新配置将采用10，未提供原始申请的新内容。")
        product = doc("PRODUCT", "product", "合成产品事实：新配置计划采用容量10。")
        notes = {
            "technical_feasibility": "技术可实现性：产品计划容量10不是运行或性能证据；需取得实际设计和适用数据后判断该配置可实现性。",
            "implementation_coverage": "实现覆盖：10在正整数数学域内，但采用10的实现还须满足本轮双有效、许可门槛及所选恢复／缓存处理限定；需代码或运行事实核对，不能仅据数值判断覆盖。",
            "parameter_domain": "原始参数域：O1只给可配置正整数和示例6。它允许讨论10作为正整数取值的数学可能，不能单凭这一点认证具体化修改。须核完整原文是否还有上限、选择关系或适用场景。",
            "function_and_effect": "作用与效果：须核具体容量是否与原机制和技术效果有特殊联系。当前没有不同容量的试验或选择依据，不能补造10的效果；若该联系必须依赖申请后新信息，就不能倒填旧申请。",
            "combination": "组合：即使具体容量路线待核，满缓存清空旧记录仍与O1保留已有记录冲突。数值确认不消除该冲突，也不支持10与清空动作的新组合；当前候选继续使用B并保留已有记录。",
            "individualization": "具体值依据：若完整原文的参数语境、作用及组合可使该具体化有原始依据，且适用修改规则允许，可提交具体值路线供专业审阅；若需从新产品确认补足选择依据，则该依据不能成为原始记载。现阶段保留B稿，取得完整原申请及法域审阅后再决定10路线，不能一概认可或仅因没逐字写10而一概否定。",
        }
        internal += "\n\n# 参数修改与版本变化\n\n" + "\n\n".join(notes.values())
        internal += "\n\n旧版稿与旧检查保留。新产品事实、参数评估和候选版本均新绑定；即便正文保留B而字节相同，也不把旧审阅改标签用于新任务。\n"
        request_docs = [request, product]
        requests = [{"id": "CHANGE_B", "symbol": "B", "citation": cite(request, request["text"])}]
    analysis = doc("ANALYSIS", "internal", internal, candidate["version"])
    if kind == "revised":
        def aspect(key):
            return {"status": "conditional", "reasoning": cite(analysis, notes[key]),
                    "conditions": ["取得完整原文、技术依据及对应专业复核"]}
        support = aspect("individualization")
        support["original_citations"] = [cite(original, FACTS[3][1])]
        support["considerations"] = {key: cite(analysis, notes[key]) for key in fidelity.SUPPORT_CONSIDERATIONS}
        assessments = [{"request_id": "CHANGE_B", "technical_feasibility": aspect("technical_feasibility"),
                        "implementation_coverage": aspect("implementation_coverage"), "original_amendment_support": support}]
    assertions, regions, blocks, bindings = [], [], [], {}
    line = 1
    for i, (kind_of_block, text, formula, basis) in enumerate(paragraphs, 1):
        identity = f"P{i:03}"
        span = cite(candidate, text)
        refs = []
        if formula is not None:
            refs = [f"A{i:03}"]
            assertions.append({"id": refs[0], "citation": span, "formula": formula, "basis_fact_ids": basis,
                               "proof_scope": "technical_consistency" if basis == ["T1"] else "original_support",
                               "mode": "asserted"})
        regions.append({"id": "R"+identity, "citation": span, "kind": "technical" if refs else "context",
                        "assertion_ids": refs, **({} if refs else {"reason": "章节标题或明确的工作范围状态；未声明新增技术机制"})})
        blocks.append({"id": identity, "kind": kind_of_block, "audience": "body", "source_id": "DRAFT",
                       "start_line": line, "end_line": line})
        bindings[identity] = span
        line += 2
    packet = {"documents": [original, prior, candidate, analysis, *request_docs], "atoms": atoms, "facts": facts,
              "assertions": assertions, "regions": regions, "parameter_requests": requests,
              "parameter_assessments": assessments}
    return {"kind": kind, "paragraphs": paragraphs, "packet": packet, "blocks": blocks, "bindings": bindings,
            "prompt": "从给定合成原件形成完整内部专利工作稿、原文回查、两路线取舍、图及修改分析；材料不足只限制受影响部分。"}


def write_cases(root: Path, destination: str):
    target = root / destination
    target.mkdir(parents=True, exist_ok=False)
    records = []
    for name in ("normal", "partial", "revised"):
        case = make_case(name)
        folder = target / name
        folder.mkdir()
        packet = case["packet"]
        paths = {}
        for item in packet["documents"]:
            path = folder / (item["id"] + ".md")
            path.write_bytes(item["text"].encode("utf-8"))
            paths[item["id"]] = path.relative_to(root).as_posix()
        spec = {"sensitivity": "synthetic", "document_id": "Fidelity" + name.title(),
            "business": "patent", "version": "2" if name == "revised" else "1",
            "sources": [{"id": item["id"], "path": paths[item["id"]], "sha256": item["sha256"]}
                        for item in packet["documents"] if item["id"] in {"DRAFT", "ANALYSIS"}],
            "dependencies": [{"path": paths[item["id"]], "sha256": item["sha256"]} for item in packet["documents"] if item["id"] not in {"DRAFT", "ANALYSIS"}],
            "blocks": case["blocks"], "fidelity": {"payload": packet, "blocks": case["bindings"]}}
        analysis = next(item for item in packet["documents"] if item["id"] == "ANALYSIS")
        for line, text in enumerate(analysis["text"].splitlines(), 1):
            if text.strip():
                spec["blocks"].append({"id": f"IN{line:03}", "kind": "heading1" if text.startswith('# ') else "paragraph",
                    "audience": "internal", "source_id": "ANALYSIS", "start_line": line, "end_line": line})
        for filename, value in [("fidelity.json", packet), ("document-input.json", spec)]:
            (folder / filename).write_bytes(canonical_bytes(value) + b"\n")
        report = fidelity.audit(packet)
        assert report["status"] == "checked", report["issues"]
        (folder / "fidelity-result.json").write_bytes(canonical_bytes(report) + b"\n")
        output = (folder / "document-pack").relative_to(root).as_posix()
        manifest = documents.build(root, spec, output, synthetic=True)
        verified = documents.verify(root, spec, output, synthetic=True)
        (folder / "document-verification.json").write_bytes(canonical_bytes(verified) + b"\n")
        records.append({"case": name, "packet_sha256": digest(packet), "finite_model_status": report["status"],
                        "document_manifest": output + "/manifest.json", "DOCX_roundtrip": verified["file_hashes_equal"],
                        "author_constructed": True, "model_task_execution": "not_performed", "professional_review": "not_performed"})
    return records
