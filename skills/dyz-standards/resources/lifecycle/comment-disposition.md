# 征求意见汇总处理表：写法与结构

阶段4的主要产物。原始审查意见与意见处置是不同交付物：这里保留原文/来源、建议、决定、实际落地及统计。采用逐条详情与表尾统计，纸面列数按适用profile，不把12个语义字段强塞成一张宽表。 返回[阶段门禁](stage-gates.md)。

## 一、这份表解决什么

征求意见不是收集清单，是**逐条闭环**：每条意见要么被采纳并落到具体条款，要么有理由地不采纳，要么明确挂起并指定责任人。三件事缺一，送审时就会被问"这条去哪了"。

表的两段：

- **逐条段**：每条意见一行，含来源、分类、结果、理由、拟改条款、影响、是否重大、未决跟进。
- **统计段**：条数与分类统计，必须与逐条段一致；附少数意见清单与重征判断。

## 二、表头（文书信息）

| 项 | 要求 |
| --- | --- |
| 标准名称 | 与送审稿封面一致 |
| 标准编号（草案） | 未获编号时写"草案未编号" |
| 征求意见稿版本 | 稳定版本标识，与正文 `version` 一致 |
| 版本日期 | 实际日期 |
| 征求意见起止 | 实际起止；未定写"未定" |
| 发出份数 | 实际记录；无记录写"未取得记录"，**不填 0** |
| 收到意见份数 | 同上 |
| 意见总条数 | 与逐条段行数一致 |
| 汇总人 / 日期 / 审核人 | 审核人须有实际确认记录 |

发出/收到份数无数时写"未取得记录"而非 0，因为 0 会被读成"无人反馈"，与实际未统计是两件事。

## 三、逐条段行结构

| 列 | 字段 | 约束 |
| --- | --- | --- |
| 序号 | `seq` | 按章条排序，不重复 |
| 章条编号 | `clause_id` / `target_clause_ids` / `scope` | 稳定ID；可多目标或文档级；删除核基线，新增核目标，不用当前正文存在性排除合法增删 |
| 提出单位/个人 | `origin.organization` | 实际名称，不代拟 |
| 代表范围 | `origin.representative_scope` | 必填；无法确认写"未确认"，不省略 |
| 意见原文 | `text` | 照录，不改写、不摘要代替 |
| 分类 | `classification` | `technical` / `editorial` / `procedural` / `ip` / `insufficient_evidence` |
| 处理结果 | `outcome` | `accepted` / `partially_accepted` / `rejected` / `pending` |
| 处理说明与理由 | `reason` | `rejected` 必须带 `source`（依据来源） |
| 拟改条款 | `changes` 或有依据的 `no_change` | 每个add/replace/delete明确稳定目标；add/replace同时有拟文；no_change不冒充已经修改 |
| 影响评估 | `impact` | 是否影响验证/引用/编制说明/下游产品 |
| 是否重大修改 | `major_change` | `yes` / `no` / `undetermined` |
| 未决跟进 | `unresolved_item` + `owner` | `pending` 时必填 |

### 分类判据

- **文字短小不等于编辑性。** 意见即使只有几个字，只要改动量值、条件、例外或强度，就按 `technical` 处理。
- **`insufficient_evidence`** 用于有诉求但无依据的意见，不是用来把难处理意见归类的垃圾桶：须写明缺什么证据，以及谁可以补。
- **`ip`** 指专利声明、许可、权属类意见，与条款技术内容分开，交专利政策交接处理。

### 处理结果判据

- **`accepted`**：记录采纳决定及明确变更或有依据的no_change；再独立核新版条款是否实际落实，不能用决定状态代替落地证据。
- **`partially_accepted`**：说明接受哪部分、不接受哪部分，两部分各有理由。
- **`rejected`**：必须给理由与依据来源。理由不能只是"经研究不予采纳"。
- **`pending`**：必须绑定未决项与责任人，并写明阻塞哪一步。

## 四、统计段

```
意见总数 = 采纳 + 部分采纳 + 不采纳 + 待决
涉及条款数 / 实质技术变化条数 / 重大修改条数
按分类统计：technical / editorial / procedural / ip / insufficient_evidence
少数意见清单（保留原文与来源）
待重征意见判断
```

**一致性要求：** 统计段每个数字都必须能从逐条段重算得出。逐条段改一行，统计段必须同步；不一致视为表未完成。

## 五、三条硬约束

1. **不编造投票。** 本表是意见处理记录，不是表决记录。有真实表决资料才另附，并核版本、资格、重复票、法定分母与阈值来源。
2. **数字满足不等于共识。** 即使统计显示采纳率很高，也不得写"经充分讨论达成一致"；`tools.standards` 对治理结果固定 `consensus: not_inferred`。
3. **少数意见不因汇总而消失。** 同类意见可合并为一行分析，但每条原始来源与少数立场独立保留在清单中；不得用"多数已采纳"抹去异见。

## 六、与编制说明的接口

在内部11节profile中，这张表是[编制说明](compilation-note.md)第 9 节的直接输入；组织目录另按语义映射定位：

- 表尾统计 → 编制说明第 9 节的采纳/部分/不采纳/待决数字。
- 每条 `pending` → 编制说明第 11 节未决事项（含 owner 与阻塞点）。
- 每条 `major_change=yes` → 编制说明第 7 节重大分歧处理，并触发重征判断。

链路断开（比如表里有 5 条 pending，编制说明第 11 节只写 2 条）即为材料不一致，送审前必须回改。

## 七、工具支持现状

v2使用`comments/comment_outcomes`为唯一输入真源，表头/行/统计是派生视图。`standards.closed_loop`核每条原意见恰一当前处置，漏项、重复、越界落点、冲突拟文和缺证分别记录。合法零意见必须有完成收集的依据；缺影响评估不得默认无影响。建议与有权决定分开，重大修改未定不能自动当no。

`standards_delivery`从实际正文生成独立`comment_realizations`，绑定决定、基线、目标与实际Word哈希，不回填处置payload形成循环。文本一致只证明落地的文字绑定，不认证权限或专业正确性。部分采纳保留接受/不接受部分及各自理由。

### 内容确认与旧记录承接

`standards_contract.comment_content_binding(payload, outcome)`对当前完整原意见、完整决定和系统推导的基线范围取digest；完整决定仅排除confirmation和confirmation_history，理由、影响、拟文、changes、重大变更、状态及扩展字段都参与。原意见全文与来源／提出者／版本任一变化，或相关基线及可确定引用依赖变化，即使标签未改也不能借旧确认。

有权角色核对当前原意见、完整处置和所绑定基线范围后，用`confirm_comment(payload, comment_id, confirmation)`返回新payload；confirmation给actor、authority_evidence、source、version和baseline_version。工具先形成拟保存的confirmed行再计算绑定，旧确认进confirmation_history；它只记录这次明确确认，不认证身份或代作专业决定。采集入口只登记原意见，导入已有v2保留原记录，两者均不代调此确认。

`unbound`表示历史已记录但缺当前内容绑定，`stale`表示内容／范围／版本不匹配；均保留历史且列待重确认。基线范围由目标、changes、no_change及引用依赖推导，不能由调用者自行缩小；文档级或无法证明局部时绑定全基线。可以证明无依赖的无关条目可承接；当前确认仍不表示正文已经落实，二者分别核查。

### 可读表式与最终文件

v2长原意见、决定、部分采纳理由及未决放可达详情，不用字数截断；短概览只负责定位。稳定ID与显示章号分开，`internal/source-map.json`的`clause_locations`连接条款显示号、书签和实际块，`internal/projection-coverage.json`核每条原意见与处置的读者投影和内部保留。缺处置与纯待审状态要出现在审查报告；manifest的pending_reviews独立参与就绪计算，机器issues为0但仍有待审时保持`internal_draft_needs_review`，不能写成已审无问题。有限审稿从实际正文唯一成对的原条款书签回读，完整结果在`internal/checks.json`的finite_review；纯`standards.closed_loop`只核输入文字，仍保留实际文件未核待审。

受限Word填写只接受明确映射的原创三列“位置／原意见—建议—理由”或六列“序号—条款—原意见—决定—理由—落实／状态”。组织表式先核实际列映射、权利和支持对象；经盘点合并格归一到承载格，全部操作预检再创建新副本。未映射、复杂域／修订／文本框、混合样式等写前拒绝；表格写入不确认意见、不推定实际条款已落实。

意见理由可用`source_bindings`连接`source_reports`内的确切citation、命题及适用版本；成件须实际核报告和固定原件／页段，不能信任载荷自报passed。仅能定位引文尚不证明命题适用，partial／仅转写／缺页状态保留；原件、报告或命题改变使依赖理由与文件块待重核。来源字段与实际文件权限见[工具契约](../tools.md#来源报告进入实际成件)。

本轮检查口径为`standards-consistency/1`、delivery生成版本为1.7。1.1／1.2／1.3／1.4／1.5／1.6包由新verify明确返回`standard_generator_version_unsupported_use_frozen_tool_or_new_directory`；保留原包及当时结果，用对应冻结工具复验，或新目录重建并重新确认，不填新hash将旧确认伪装为当前。

旧`header/items/summary`表式可经[显式转换入口](../tools.md#旧意见表显式转换)导入新候选，或从v2导出旧表候选；原表、源版本、实际输入hash/定位及逐项缺口/损失一并保留。转换不会补造有权决定、集合完整性或缺失的影响判断；需先补齐获准字段，再交v2闭环和实际成件核查。旧schema路径/ID与以下legacy行为不因转换而改变。

以下为缺省/1的legacy兼容约束；新闭环显式选2，不沿用其拟文/目标异或限制。

`_governance` 已支持受控处理结果（AF-04，2026-11-13 实施）：

- `comment_outcomes` 逐条给 `outcome`，取值限于 `accepted / partially_accepted / rejected / pending`，其他值报 `comment_outcome_unknown`。
- 采纳须有落点：`proposed_text` 与 `clause_id` 恰好一项，否则 `accepted_text_unresolved`。
- 不采纳须带 `reason` 与 `reason_source`，否则 `rejection_reason_unsourced`。
- 挂起须带 `unresolved_item` 与 `owner`，否则 `pending_item_unowned`。
- `classification` 五值受控、`major_change` 三值受控；统计见返回的 `outcome_tally`（含 `tally_balanced`）。

历史 `decisions` 自由文本仍可随附作为补充说明，但**不能充当处置结果**：每条意见都必须有一条受控 `comment_outcomes`，否则报 `comment_outcome_missing`。来源、代表范围与表尾统计仍须人工核对。

## 八、不适用范围

- 真实表决、组织决议、正式答复均不由本表产生；本表只组织已收到的意见与拟处理建议。
- 组织有固定表式时以组织表式为准，本结构用于组织表式未取得时的内部整理；两者字段映射须在送审前核对。
- 意见原文涉及第三方受限材料时，按材料许可处理，不因进入本表而转为可公开。
