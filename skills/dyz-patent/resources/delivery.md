# 专利合成成品与普通阶段确认

本资源对应R04/R06、AC-CORE-06/07、AC-LIFE-04、AC-DRAFT-05及AC-REVIEW-03/07。只说明当前本地合成Python API，不开放真实案件、研究材料、外部模型、发送或提交入口；普通确认不是DG披露批准。全文由调用者完成并提供，工具不补造权项、说明书、摘要、实施例或附图。

## 1. 何时使用

已具备完整原创合成稿，需要生成实际Word、检查预期件、分离内部材料、修改后回查或记录某一版本的普通内部确认时，使用`tools.patent_delivery`。局部改句和分析任务不必装配整包。专利事实与原始支持仍按[事实与支持核查](fact-and-support-review.md)；文件格式和已编辑Word回查分别按[渲染工具契约](../../dyz-rendering/resources/tools.md)和[Word回查](../../dyz-rendering/resources/docx-readback.md)。

此薄编排复用`documents.resolve_document/build/verify`和`VersionLedger.put/is_current/export`。没有另建文档生成器、账本、数据库、专业评分器或通用平台。

## 2. 输入：已有documents配方加交付声明

沿用documents的`document_id/version/business/sensitivity/sources/blocks/figures/dependencies/fidelity`等字段，其中`business="patent"`、`sensitivity="synthetic"`，调用时必须显式传`synthetic=True`。`delivery_stage`为`draft`或`final`。源文件应位于调用者独占的根目录内；源行与图均按现有哈希绑定读取，不覆盖原件。

额外添加如下声明；示例中的块ID必须对应调用者实际提供的源行，不由工具代写正文：

```json
{
  "patent_delivery": {
    "project_id": "SYNTHETIC-PATENT",
    "scope": "合成CN内部起草",
    "purpose": "本地开发回归",
    "rules": [{"id": "synthetic-rule", "version": "1"}],
    "notice_block": "Notice",
    "expected_roles": {
      "claims": ["Claim"],
      "specification": ["Spec"],
      "abstract": ["Abstract"]
    },
    "drawings": {
      "applicable": false,
      "figure_ids": [],
      "not_applicable_reason": "本合成文字示例不使用结构或流程附图。"
    }
  }
}
```

- `expected_roles`明确列出权利要求、说明书和摘要的全部实际块。每个角色可有多个块；一个块不能兼任多个角色。内部块不能冒充主稿，未分配角色的正文不能被静默忽略。配方可使用标题、段落及现有支持的表格，不对段落数量或保护对象组合做硬编码。
- 角色完整性只核非空实际块及成员，不理解章节是否充分、权项是否有价值、实施方式是否足够或是否满足特定法域要求。角色齐全只能记`complete_declared_roles`，不能称法律完整。
- `notice_block`必须是实际主稿中的一个独立块，其源文本精确为：**合成示例；内部工作稿，待专业审阅，不得据此提交或外发。** 因而Word被单独取出仍带合成和待审身份。此块也应在提供fidelity时单独绑定；它不是技术披露。
- 附图适用时，`drawings.applicable=true`且`figure_ids`列出全部适用附图ID，对应现有`figures`的PNG、SVG和render_binding；缺图则不完整。不适用时必须明确说明理由，不能用空集合掩盖未知适用性。
- `scope/purpose/rules`都是确认范围的一部分。规则ID及版本是调用者记录，不代表现行规则核验；规则内容或来源如发生变化，应同步其声明版本/哈希。
- `sources`的文件SHA与source-map中每个源行块的`text_sha256`分别保存，**派生文本SHA不是PDF、图像等原件SHA**。现有`dependencies`绑定原始二进制载体，以下可选关联直接引用`capture_evidence`快照，不另建取证格式。本链不认证原件来源，不验证PDF/OCR抽取真实性、页码或语义映射。不得以派生文本一致宣称原件已核。

### 可选原件—派生文本关联

`patent_delivery.source_derivations`可显式记录某个派生source来自哪个已绑定原件dependency。每个source最多一条；复杂多原件拼接或多次提取应由调用者拆为明确的source，不由本工具猜测。每条包括：

```python
link = {
    "source_id": "SRC", "source_sha256": spec["sources"][0]["sha256"],
    "original_evidence": captured_record,
    "method": "caller_supplied_transcription",
    "scope": "调用者声明的原件节选范围",
    "block_ids": ["Claim", "Spec", "Abstract"],
    "location_status": "located"
}
spec["patent_delivery"]["source_derivations"] = [link]
```

`captured_record`是已有`tools.core.capture_evidence`返回的记录，不是新构造的第二套原件字段。其`path/sha256`必须对应`dependencies`中的原件，`evidence_id`按已有规则核对，size与实际载体核对，locator、acquired_at、source版本和extraction_status仍沿用取证记录。合成入口只接受synthetic且authenticity为not_verified的记录，不因此授予材料权限。

`source_id/source_sha256`单独冻结派生文件；`block_ids`必须属于该source，范围与定位直接采用已有source-map的一基行号及块文本SHA，不复制原文或伪造PDF页码。`method/scope`必须明确写明提取方式与范围；`location_status`为located或unlocated，无法定位时应如实选后者，原件locator记录无法定位的事实而非补造位置。method、范围、定位和状态都是调用者声明，不是工具观测到OCR执行。

原件、派生文件和块文本三类哈希分别核对，任何一类都不能替代另一类；即使两份不同文件碰巧字节相同，也不据哈希相等证明来源或提取真实性。源文件与原件不能指向同一规范路径。原件或派生字节改动由documents实际回验拒绝；只更新dependency/source哈希而沿用旧关联仍拒绝。关联变更属于当前输入与确认范围，会使旧确认失效。

无关联时明确报告`status=not_performed`，不从相同文字推断原件关系；可选关联缺失不改变既有合成候选接口，但任何候选仍不得称原件已核。有有效关联时仅报告`bindings_checked`和`declared_scope_only`。partial、ocr_uncertain、missing_pages、unreadable、not_checked、unlocated或未覆盖全部声明角色块时报告partial，不能升级final或允许普通确认自动继续。无论调用者是否声明complete，`original_verification`始终not_performed、`extraction_authenticity`始终not_verified、法律支持始终未评估。

## 3. 实际产物与缺件规则

在含`tools/`的仓库或已验证完整包根，按已有配方调用：

```python
from tools import patent_delivery

manifest = patent_delivery.prepare(root, spec, "new-pack", synthetic=True)
verified = patent_delivery.verify(root, spec, "new-pack", synthetic=True)
```

`root`为源文件根，`spec`是调用者完整配方，输出目录必须不存在且父目录已存在。此模块没有新增CLI、worker或宿主桥接入口。主文稿采用一个组合DOCX，角色在清单中映射到具体源块，不用三份同名空文档伪装完整件数。

| 产物 | 用途 |
| --- | --- |
| `document/body/document.docx` | 包含声明角色的实际合成专利主稿候选 |
| `document/body/source.txt`、适用的`document/body/<figure-id>.svg` | 主稿文本副本与附图资产，仍不是批准外发包 |
| `document/internal/notes.txt` | 仅内部说明，不进入主稿 |
| `document/internal/source-map.json` | 已有源文件哈希、源行范围及块文本哈希 |
| `document/internal/quality-review.json` | 实际DOCX文字质量检查完整报告 |
| `document/internal/fidelity-review.json` | 提供有效fidelity绑定时才生成的有限保真报告 |
| `document/internal/final-text-gate.json` | 最终交付或显式要求门禁时的实际正文检查报告，缺失不能获最终放行 |
| `internal/input.json` | 原始配方、声明和绑定，可能含原文，只限内部 |
| `internal/delivery-review.json` | 角色、附图、可选原件—派生关联、检查缺口及准确边界 |
| `manifest.json` | 全部实际文件哈希、用途和状态；不含自身哈希 |

所有文件通过后才写外层清单；写入失败可留下半成品，但没有成功清单，不会自动覆盖或清理用户材料。调用者须独占根目录并防止并发替换，工具不是OS沙箱或防篡改审计。

- 缺角色、角色重复、内部块冒充角色、适用图缺失等，草稿记录`incomplete`和问题；不称完整。
- 无fidelity可生成明确工作稿，但`fidelity=not_performed`、`checks_ready=false`。实际Word质量扫描不能替代关系/来源支持检查。
- `final`只代表请求构建待专业审阅的候选。必须声明角色完整、实际fidelity为checked、实际质量检查为checked，且[最终正文门禁](tools.md#最终正文验收门禁)checked；若显式提供原件—派生关联，该声明也不得处于partial，否则拒绝`patent_final_requirements_missing`或对应检查错误，不升级。现有附图、复杂公式等可能导致质量覆盖partial；该状态不会被编排抹平或升为final。
- `final_text_sources`为固定原文列表；未显式提供时仅从fidelity.payload.documents取original。正文门禁在创建交付目录前检查每个实际body块，条件倒转、重复／无依据从属项、缺源或未支持语法抛`final_text_gate_blocked`，不会生成最终主稿或成功清单。成功时子包内保存`internal/final-text-gate.json`，回验重新计算并比较，不能改报告和清单hash复用。draft若显式提供final_text_sources同样触发；未触发的草稿可保留内部修订，但不能获普通确认的may_continue。
- 门禁2.0的条件、类型关系和组合检查用于每份实际正文；答复与替换稿分别从权项1开始时按各自工件核编号，连续块的从属引用仍继承前块。Word整段／按正常标题块装配均执行同一规则，技术标题不能改标heading绕过。正文／原件／生成器变化后重新构建并verify；旧包报告不迁作新实现通过。
- 成功候选仍为`candidate_needs_professional_review`。门禁checked与原题交付完成度分开：例如材料只支持一条从属项时，不能把原题要求两条改记满足。专业、视觉、官方和外部动作分别维持未执行/未主张；不存在自动可提交状态。
- 此入口拒绝真实/研究材料。它不放宽documents已有的research_fidelity_not_supported、逐文件材料权限或真实材料preflight边界；这些路径需使用原有授权入口，不能改synthetic标签绕过。

## 4. 普通确认与恢复后失效

确认者身份由调用者负责；仅记录明确人类普通确认，不调用专业`add_review`：

```python
from tools.core import VersionLedger
from tools import patent_delivery

ledger = VersionLedger()
binding = patent_delivery.register_package(ledger, root, spec, "new-pack", synthetic=True)
event = {
    "id": "confirmation-1", "actor_id": "synthetic-caller", "actor_type": "human",
    "stage": "internal_review", "decision": "conditional",
    "conditions": ["等待技术与专业责任人核查"],
    "confirmed_at": "2026-11-01T00:00:00Z",
    "manifest_sha256": binding["manifest_sha256"]
}
record_id = patent_delivery.record_confirmation(
    ledger, binding, event, root, spec, "new-pack", synthetic=True)
state = ledger.export()
restored = VersionLedger(state["records"], state["reviews"])
status = patent_delivery.confirmation_status(
    restored, record_id, root, spec, "new-pack", synthetic=True)
```

时间必须是实际确认时间且不得在未来，以上时间和确认者仅是合成调用示意，不能作为真实确认事实。`conditions`必须显式给出；conditional必须列非空条件。

`binding_current`只说明依赖仍对应当前包，不说明接受。`may_continue`仅限本地内部审阅：当前绑定、decision为accepted、conditions为空且必要机器检查就绪才为真。rejected、conditional、带未决条件的accepted，以及缺件/无fidelity工作稿均不自动允许继续。它不授予专业通过、披露、发送或正式提交权限。

登记包、记录确认和查询确认都重新核实际输入与实际文件；不可只提交旧manifest的hash。篡改主稿、改清单内hash、改变源、正文、图、用途/范围或规则均不能沿用旧确认。更新同项目选择通过既有版本依赖失效传递，导出恢复不复活旧确认，无关项目记录不受影响。同内容复制到另一输出位置也不承继原位置的确认。条件状态返回值与账本记录隔离，调用者改返回列表不能修改原确认。

## 5. 编辑后回查与本地验证

外部编辑应在副本中进行，冻结原基线；不要将改后Word直接放回旧包再重新自报hash。使用已有API：

```python
from tools.document_review import review_docx

report = review_docx(edited_docx_bytes, baseline_docx_bytes)
```

完整报告分别保留权项条件字面变化、附图标签/字节绑定、缺失书签和隐藏修订。书签身份无法确认时保持partial，不猜测原位置身份；隐藏修订不等于已接受/拒绝或已清除，图标签不证明图像语义等价。修改内容应回到调用者配方、支持材料和当前绑定重新生成新包，不复用旧普通确认。

本地回归只用`TemporaryDirectory`生成原创合成文件，不读取真实outputs。运行环境为项目Python 3.11标准库，无新增依赖。在仓库根运行：

```powershell
python -B -m unittest evals.test_patent_delivery -v
```

实际本轮次数、首次失败、修复和最终结果由维护者记入唯一施工台账。本地回归不提供真实案件、独立专业/视觉审阅、同版宿主资格、模型稳定性或发布资格；需单独完成相应验收。
