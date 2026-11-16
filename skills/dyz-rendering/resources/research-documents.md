# 原创研究示例的文件装配

关联CORE-07、WP-01/06/10。此模式用于已确认来源与数据路径的原创合成技术文本、原创公开资料研究及其组合，保留实际执行证据的类别；不处理私人案件、受限标准原文或组织模板。业务CLI仍只支持合成材料，83项专业支持状态不变。返回[文件工具](tools.md)或[Word回查](docx-readback.md)。

## 1. 明确声明，不改标材料

`tools.documents` 1.3增加`--research-example`，与`--synthetic`互斥。输入的`sensitivity`须为`research_example`，不能把新输入改成synthetic绕过。没有模式声明时，在读取输入文件前停止；在读取任何源内容前核完整的文件声明集合。

沿用`sources`、`dependencies`、`blocks`及源行区间。另有`research_materials`，须逐一覆盖实际读取的源、依赖及图的PNG/SVG，路径和SHA-256相符，不多、不少、不以不同别名重复。每项只含下列字段：

| 字段 | 内容 |
| --- | --- |
| path／sha256 | 本次根目录内的实际文件与冻结字节哈希 |
| content_kind | original_synthetic、original_public_research、original_mixed_research或original_execution_evidence |
| processing_basis | 当前处理依据的非空说明；空白及明确unknown/pending等缺口不得作为依据 |
| export_basis | 本次本地文件装配依据；不等于公开、收费使用或发送许可 |
| third_party_text | 此限定模式只接受not_included；原标准全文、第三方模板/代码及私人材料不纳入 |

这些是调用者声明和字节绑定。工具不能检测原文实际上是否公开、判断真实权利、认证授权主体或授予模型处理权限；虚假声明不会因程序接受而变真。目录可读、来源链接、已有许可文件或本地路径都不能自动填补缺口。manifest记录`mode: research_example`及`research_scope`，source-map保留逐文件声明，状态仍为needs_review。此模式暂不调用仅支持synthetic的fidelity消费者；有该字段会在读取源内容前拒绝，不能声称已经完成语义保真检查。共享装配会另对实际DOCX执行文字质量检查，报告置于`internal/quality-review.json`并绑定实物hash；即使该轻量检查checked，semantic_fidelity仍为not_performed，不改变研究标签、材料用途或第三方全文限制。draft允许保留带明确问题的内部工作包，final遇残留待确认标记拒绝；措辞命中仅review，不自动改写原句，也不等于视觉、语义、专业或外发批准。

## 2. 可直接运行的完整两版示例

全部为本项目原创合成技术与原创来源分析，不是真实协会项目。技术变化由既有RQ-RIVER-1.0/1.1给定，见[变化影响](../../dyz-standards/resources/river-delivery-source/change-impact.json)。原三案和原文件不变。

| 成件 | 当前文本 | 输入与冻结依赖 |
| --- | --- | --- |
| 1.0正文 | [draft-v1.0.md](../../dyz-standards/resources/river-delivery-source/draft-v1.0.md) | [draft-v1.0-input.json](../../dyz-standards/resources/river-delivery-source/draft-v1.0-input.json) |
| 1.0编制/验证/意见 | [review-v1.0.md](../../dyz-standards/resources/river-delivery-source/review-v1.0.md) | [review-v1.0-input.json](../../dyz-standards/resources/river-delivery-source/review-v1.0-input.json) |
| 1.1正文 | [draft-v1.1.md](../../dyz-standards/resources/river-delivery-source/draft-v1.1.md) | [draft-v1.1-input.json](../../dyz-standards/resources/river-delivery-source/draft-v1.1-input.json) |
| 1.1编制/验证/意见 | [review-v1.1.md](../../dyz-standards/resources/river-delivery-source/review-v1.1.md) | [review-v1.1-input.json](../../dyz-standards/resources/river-delivery-source/review-v1.1-input.json) |

Python 3.11标准库，在完整包根运行，四个输出目录须不存在：

```powershell
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-delivery-source/draft-v1.0-input.json --output river10-body
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-delivery-source/review-v1.0-input.json --output river10-review
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-delivery-source/draft-v1.1-input.json --output river11-body
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-delivery-source/review-v1.1-input.json --output river11-review
```

加同一命令的`--verify`回读已有包；输入、材料声明、源、正文或版本变化均须另建输出并重审。可显式加`--pdf-tool`指定本机已有soffice绝对路径，调用独立临时profile；不安装或联网，不使用日常Office配置。PDF仍需逐页文字及显示核对，生成器不会替人完成视觉审阅。完整包不携带LibreOffice或第三方标准原文。

## 3. 当前文件、意见与变化回查

```powershell
python -X utf8 -m tools.document_review --research-example --root . --input river11-body/body/document.docx --baseline river10-body/body/document.docx --output river-word-review.json
```

回查器1.1保留research_example标签；可用`--expected-sha256`及`--baseline-sha256`绑定已确认的当前/基线字节。否则报告所读实际哈希，不认证提供者身份。支持范围仍限实际文字、矩形表格、唯一书签和未解释项，不能自动裁定技术语义或专业正确性。实际Office另存可能引入尚未解释的样式、主题、设置等部件，必须保留partial，不能只因目标文字已定位就改为完整通过。

[意见文件绑定](../../dyz-standards/resources/river-delivery-source/file-bindings.json)列本次实际生成的DOCX哈希和目标书签；其中忽略输出路径只是观察位置，包搬迁后由上面命令另建文件，不依赖该路径。重用建议前核实际哈希及唯一目标，不能按章节可见编号猜身份。O-V01—05是新修订意见，不冒充原O-01—05的同一条。此记录和测试核对不是审批或发送硬门禁。

1.0至1.1应同时改变版本精确值、序号域/跳号、null缺测，术语、示例、验证及意见也同步；不将null转0、不填跳号、不对旧端自动回退。保留两版文件、实际文字差异和逐页检查，旧签核不迁用。model-run.json是有限作者执行证据，独立实现、GB/T全文/正式格式、专业和组织批准仍待完成。

## 4. 旧版本保留

1.3核manifest时仍要求实际工具版本匹配。旧1.2文件包保留，可用原冻结1.2工具核验，或按当前输入在新目录生成1.3包并重新回查；不覆盖旧包、改旧manifest版本或自动承接旧审阅。新模式不扩大其他业务工具、渲染器或fidelity的材料权限。

## 5. 专利混合来源两版示例

[原案](../../dyz-patent/resources/cn-gateway-example.md)是本项目原创合成设计；[官方版本研究](../../../references/jurisdictions/patent-official-evidence-20261103.md)是原创公开资料分析，不携带第三方原文。GW两版完整正文与独立交底／核查记录见[变化影响](../../dyz-patent/resources/cn-gateway-delivery/change-impact.json)，每份输入冻结7或9个实际读取文件，保留材料类别，不调用synthetic的fidelity桥。

在完整包根运行，四个目录须不存在：

```powershell
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.0-input.json --output gateway10-body
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/review-v1.0-input.json --output gateway10-review
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.1-input.json --output gateway11-body
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/review-v1.1-input.json --output gateway11-review
python -X utf8 -m tools.document_review --research-example --root . --input gateway11-body/body/document.docx --baseline gateway10-body/body/document.docx --output gateway-word-review.json
```

上述生成命令各加`--verify`核已有包。可显式指定本机已有soffice导出PDF，再逐页观察；不能把检查PNG／文字或回查JSON放入严格产物目录，额外成员也会被拒绝。检查证据置于旁边，旧导出与失败不覆盖。[文件绑定](../../dyz-patent/resources/cn-gateway-delivery/file-bindings.json)列当前四份DOCX和PDF及关键唯一书签；输出提示只作本机观察，不是包的隐藏依赖。

GW-1.1从原从项3将接收端校验、记录键和同事务持久提交上提主项1，实际正文变化5个书签、内部说明3个；其余从属项继承收窄的主项。历史1.0／1.1两份正文各5页（含原图A3附页），内部说明各2页。Word稿含未解释drawing／PNG和样式，仍为partial；内部说明只达complete_supported_subset，不代表任意Word或专业通过。该14页PDF实看、文字核对及实际办公另存副本的反例是有限作者工程证据，不能代替自然语言保真、CN修改支持、状态／FTO、正式格式或独立写作验收。

### 5.1 GW 1.2新增来源后的两件文件

GW-1.2将已读的两篇EPO公开文献加入背景和内部核查，逐一比较请求／用户确认／服务器删除及备库分组重放／可见性；原件内部疑点、优先／同族／状态未核范围保留。[来源变化](../../dyz-patent/resources/cn-gateway-delivery/source-update-v1.2.json)核7项权项、技术段落、摘要及图保持，旧稿和旧审阅不替代当前核查。

在完整包根运行，输出目录须不存在；若需下面的1.1比较基线，先运行上节对应生成命令：

```powershell
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.2-input.json --output gateway12-body
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-patent/resources/cn-gateway-delivery/review-v1.2-input.json --output gateway12-review
python -X utf8 -m tools.document_review --research-example --root . --input gateway12-body/body/document.docx --baseline gateway11-body/body/document.docx --output gateway12-word-review.json
```

生成命令加`--verify`回读；可显式选择已有soffice生成PDF，另逐页看最终显示。正文／核查输入各有11／9个原创材料声明，含开放元数据原字段的研究记录不在导出读集中；没有扩展CLI的第三方全文权限。[当前文件绑定](../../dyz-patent/resources/cn-gateway-delivery/file-bindings-v1.2.json)核同版两件：6页正文、3页核查件，49／25个唯一书签、105段／表格单元文字和16个目标。正文既有书签仅版本行变动，新增两背景；核查件原8个位置变化并新增5个位置。全部非document.xml部件含样式／图片字节保持，9页最终PDF和同DOCX独立渲染像素一致并实看。正文回读仍partial，核查件仅complete_supported_subset；未做任意Word、物理打印、独立或专业验收。故意错日期的私有副本只用来核文字定位及旧清单拒绝，不进入包或交付件。

## 6. 标准1.1验证补充成件

[验证补充](../../dyz-standards/resources/river-v11-verification/verification.md)连接原1.1要求／条款、78个新增输入、三条状态链的11步及原意见。它独立成件，技术正文与原RS-2四份文件保持；research_example逐一声明九份源／依赖，包括原创执行证据，不改标为synthetic调用STD业务工具。

```powershell
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-v11-verification/document-input.json --output river11-verification
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-v11-verification/document-input.json --output river11-verification --verify
python -X utf8 -m tools.document_review --research-example --root . --input river11-verification/body/document.docx --output river11-verification-readback.json
```

首次输出目录须不存在；按需显式指定本机已有soffice导出PDF，实际逐页核对，观察证据置于包目录外。[文件绑定](../../dyz-standards/resources/river-v11-verification/file-bindings.json)核补充的19个唯一组件和四个选定目标，并绑定原1.1内部说明的四个实际目标；原可见条款号不能替代书签身份。当前补充3页PDF已实际查看、99段／表格单元文字已核，Word只为complete_supported_subset，样式未全面解释，不表示专业、正式格式或组织批准。

## 7. 软件专业待审包成件

[软件待审稿](../../dyz-software/resources/harbor-review-readiness/review-pack.md)整理当前真实源字节与单独标识的合成条件演练，保留主体／日期／权利未知。逐文件声明的26份来源包含当前／旧版源码、字段／说明、三张既有截图、原创公开研究和实际执行证据；不把它们改标为synthetic调用业务工具或fidelity桥。

```powershell
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-software/resources/harbor-review-readiness/document-input.json --output harbor-review-readiness
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-software/resources/harbor-review-readiness/document-input.json --output harbor-review-readiness --verify
python -X utf8 -m tools.document_review --research-example --root . --input harbor-review-readiness/body/document.docx --output harbor-review-readiness-readback.json
```

输出目录须新建；可显式用本机已有soffice导出PDF，检查记录放在产物目录外。当前材料RS4为4页，129段／表格单元及22个唯一组件已核；首次孤立尾注及后续修订保留。20项字段共用HbrFields表书签，逐行来源另由evidence-map定位；[文件绑定](../../dyz-software/resources/harbor-review-readiness/file-bindings.json)核当前实际DOCX／PDF和六个选定目标。软件版本仍1.3，材料修订不是新软件版本、真实主体或登记日期；格式核对不认证真实权属或专业完成。


## 8. 标准本地双进程验证成件

[同作者两种实现验证](../../dyz-standards/resources/river-local-interop/verification.md)接两版串行内存语义和实际进程交换；原RS-2正文／核查、原V11补充不改。13个原创材料声明包括两实现、运行器、冻结计划、首轮实际结果、原需求／输入和旧稿，不含第三方原文或新规则。

```powershell
python -X utf8 skills/dyz-standards/resources/river-local-interop/run_interop.py
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-local-interop/document-input.json --output river-local-verification
python -X utf8 -m tools.documents --research-example --root . --input skills/dyz-standards/resources/river-local-interop/document-input.json --output river-local-verification --verify
python -X utf8 -m tools.document_review --research-example --root . --input river-local-verification/body/document.docx --output river-local-verification-readback.json
```

输出目录须不存在，检查证据置于严格产物目录外；可显式选已有soffice导出PDF再逐页核显示。[当前绑定](../../dyz-standards/resources/river-local-interop/file-bindings.json)记录材料RS3、2页PDF、58段／表格单元、19唯一书签、当前7个和旧稿5个实际目标。首轮与RS2跨页观察／源／文件保留，RS3只压缩3个重复说明段，协议、预期、实现和首轮执行未改。最终PDF与同DOCX独立渲染像素一致，两页实看；Word仅complete_supported_subset，不代表全部样式、任意Word或正式组织格式。新进程为空状态不当耐久试验通过，同作者进程交换不当两家独立产品互操作或专业验收。
