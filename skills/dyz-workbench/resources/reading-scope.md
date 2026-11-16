# 读取范围：逐文献记录、生成与回查

适用于专利文献、软件材料和标准来源的已读范围说明。普通用户交材料即可；执行者整理记录并调用同包工具，不要求用户手写JSON。它接CORE-03/07与WP-01/02/05/10，只核指定记录、范围运算和选定文字，不认证实际阅读、原件身份、许可或专业结论。

## 工作顺序

1. **先核记录。** 每份来源分别记录身份、版本、介质、计数单位、操作、事件及直接记录／转述记录，保留依据位置与实际字节hash。PDF页、XML段、逻辑图和绘图对象不是同一单位；机器提取、渲染、文字阅读和目视不互换。
2. **范围不明就保留。** 未知、未检查、未取得、声明不适用分别记录及说明理由，不等于已覆盖0页。总量或版本未知不能写成全文已审；明确记下的零覆盖才用known与空范围。
3. **逐份生成，合计单列。** 单篇只取本篇及本版本。合计列出各身份／版本，不能混加介质、单位、操作、记录方式或事件；同一文献重叠范围取并集，不重复加数。同组总量冲突、范围越过任一已知总量时拒绝；有未确定总量的记录不从另一条自动补齐。
4. **核实际文件。** 由reading_scope块生成句子，再用同一输入严格verify实际DOCX。Word或来源改动后重建，不给旧清单改hash冒充检查。自由改写的其他段落仍须逐句核归属，工具不自动发现所有范围陈述。

## 同包可运行示范

完整包根运行，目标须不存在：

```powershell
python -B -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/reading-scope-example.json --output scope-demo
python -B -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/reading-scope-example.json --output scope-demo --verify
python -B -m tools.document_review --synthetic --root . --input scope-demo/body/document.docx --output scope-demo-readback.json
```

示例是合成资料，不是真实阅读回执。[记录原文](../../dyz-rendering/resources/reading-scope-records.md)与[预期文字](../../dyz-rendering/resources/reading-scope-statements.md)均随包提供。两份分别10/13及21/38，合计31/51；不能把合计归给第二份。实际Word文字与internal/reading-scope-review.json由同一记录绑定。普通Word回查不自动证明本检查执行，另核manifest的reading_scope与报告。

## 执行者的数据契约

`tools.fidelity.audit_reading_scope(payload)`无文件／网络／执行副作用：

- documents含记录来源的id/version/role/text/sha256。role为original或source，hash绑定所给UTF-8原文，不是原始申请或官方身份认证。
- readings含唯一id和citation(document_id,start,end,quote)。零基字符区间精确命中来源文本，quote须为严格JSON记录；不从自由文字自动抽取或猜值。
- statements含唯一id、kind=single/aggregate及reading_ids。可加expected={subjects,covered,total}核人工解释的旧陈述；自由文字解释本身不由程序验证。

被引JSON须含subject={document_id,version}、medium、unit、operation、origin、event_id、state、total、ranges。版本或总量可明确为null，保持待核，不从同标题／同族推定。取值见下表：

| 字段 | 当前取值与边界 |
| --- | --- |
| medium | pdf/xml/text/docx/image |
| unit | physical_page/numbered_paragraph/line/logical_figure/drawing_object/image/paragraph_block；单位须由记录者核定 |
| operation | visual_review/text_read/machine_extracted/rendered |
| origin | direct/reported；这是声明，不是认证 |
| state | known/unknown/not_checked/unavailable/not_applicable；非known须空ranges及非空reason |
| ranges | 一基闭区间，重叠／相邻区间归并；正整数且不越已知total，拒绝布尔值当整数 |

每组最多256记录／陈述，每记录最多256区间，单计数上限1000000；输入上限4000000字节，投影每句32000字符、合计200000字符，区间工作预算受限。超限明确拒绝，不静默截断。

## 接到实际DOCX

装配输入增加reading_scope={payload,blocks}；blocks将每个kind=reading_scope的正文块id绑定到陈述id，所有陈述须至少有一个实际块。证据文档同样列入sources，id/version/sha256/text必须与实际文件一致。

推荐块带generate:true，source_id与行区间指向被冻结记录文件，覆盖该主来源的实际引用字符位置，别处相同文字不能替代。程序从数据生成文字、算合计，在source-map中保留derivation、主来源字符区间、原数据文字hash及全部依据引用；这是计算投影，不伪称原行已写有该句。body/source.txt是实际输出文字，计数修改应回记录重建。示例中的statements.md另列预期文字便于核对，自动块不从其中抄计数。

省略generate或设false时，源行必须与计算投影逐字相同，否则创建输出前拒绝。严格verify会重新核来源字节／版本、报告、清单及实际Word部件和文字；仅改Word并重算清单hash仍不能通过。

合成与逐文件声明的原创研究示例都可用，研究模式仍不启用既有法律／逻辑fidelity字段，不扩大到真实案件或第三方全文。新块种类使不支持的旧装配器明确拒绝，不能把旧工具退出0或缺报告当检查完成。

报告checked只表示有限数据及文字检查，整体DOCX仍needs_review、专业仍not_performed。未归类自由文字、记录真实性、从原件／日志到JSON的解释、视觉／隐藏层、物理打印与正式适用性仍分别复核。
