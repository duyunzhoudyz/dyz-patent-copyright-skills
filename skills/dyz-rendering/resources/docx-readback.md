# 编辑后DOCX回查与条款身份

关联CORE-07、REVIEW-07及WP-02/04/05/06/07。用于取得获准的当前文件后，查实际文字、条款书签、表格和未解释部件；技术方案、软件事实和标准要求仍分别由原业务审阅。读取成功不等于内容正确、隐藏内容已清除、官方格式合格或允许外发。

## 先绑定两个实际版本

1. 保留编辑前文件、编辑后文件及各自完整SHA-256，不覆盖原件。说明基线由谁提供、是否与已批准版本一致；仅有hash不能认证来源、签核或正式提交身份。
2. 先分清生成器回读和编辑稿回查。`tools.documents --verify`只接受本生成器的原包；手改后被它拒绝是预期行为。编辑稿走`tools.document_review`，不能给原manifest换hash使旧审核继续有效。
3. 列明本次比较范围及所需输出：文字修改、条款身份、图表/引用、隐藏内容和视觉分别记状态。合成资料用`--synthetic`；明确的[原创研究示例](research-documents.md)用互斥的`--research-example`并保留分类。私人案件及受限原标准材料仍不在此限定模式内；不得改标synthetic绕过。声明不验证真实来源或权利。

在完整包根，取得两份已存在的合成DOCX后运行：

```powershell
python -X utf8 -m tools.document_review --synthetic --root . --input outputs/edited.docx --baseline outputs/baseline.docx --output outputs/readback.json
```

`outputs`父目录须存在，报告须为新JSON文件。可传`--expected-sha256`和`--baseline-sha256`核对已冻结字节。省略baseline时仅回查当前文件，comparison明确为not_requested；不凭文件名推测旧版本。CLI默认标准输出只给状态、位置及hash；可用下述`--summary`追加有界索引与变化片段。报告及摘要属于所检查材料，不能默认公开或整包外发。

纯字节接口为`review_docx(current: bytes, baseline: bytes | None = None) -> dict`；使用调用者提供的字节，不读取网络、启动Office或执行文档内容。

## 可选精简返回（工具1.4）

需要先定位变化和风险时，在上述CLI追加`--summary`，或调用`case_docx_review`时给`summary:true`。默认仍只返回原有状态／路径／hash；完整JSON始终写入指定新文件，不因摘要丢弃正文、标记或未解释项。

精简结果在`review_summary`中提供当前／基线hash、两侧读取状态、比较状态、各组总数／已显示数／省略数，以及最多32项、条目JSON累计不超过24000 UTF-8字节的定位索引。条目带指向完整报告的`report_pointer`，覆盖异常／未读部件／未解释片段／风险标记、变化书签及绘图、未配对身份、变化部件和无书签文字范围；相同书签正文不重复返回。每侧变化原文或无书签片段最多240个Unicode字符，截断标志和原片段hash保留。摘要不是全部报告，也不证明已读未显示的内容。

工具桥在`summary:true`时将stdout JSON只解析至`report_summary`，令`stdout`为空并标`stdout_format:parsed_into_report_summary`，避免两次返回相同片段。默认调用保持旧形状。摘要含受检原文片段，沿用材料及日志权限；默认调用留痕仍只存hash等元数据。

`omitted_items`非零或`coverage:partial_index`时，按各组`report_pointer`到完整报告补读；若通过文件工具读取，使用返回的`output`、`sha256`与`case_read`的行列／续读契约，不把JSON Pointer当文件路径或新增过滤参数。部分／未知、不比较、隐藏清理未评估和专业／视觉未验状态保持；不存在“摘要无变化＝审阅通过”。

## 差异与异常的读取顺序

完整JSON保留在获准目录，下面是审阅顺序，不是新API、报告裁剪或降低检查范围：

1. 先核current／baseline实际文件hash、readback_state、comparison.state和未执行状态；缺baseline明确未比较，不写“没有变化”。
2. 先查notices、unread_parts、unresolved_fragments及未配对书签／绘图，列需要恢复的部件、原因与责任；partial不能被相同正文或零差异冲掉。
3. 有两版时定位changed_parts、paired_bookmarks的变化和paired_drawings，随后读取对应blocks、原文区间及必要上下文。无书签文字仍查unanchored_text_ranges；不能仅因变化不在书签内就忽略。
4. 隐藏内容问题单独核两侧content_inventory的部件hash／XML位置，保留not_assessed。只读摘要不算逐标记处理，零标记也不证明清理完成。
5. 报告先交“问题ID—两版位置—旧／新片段—依据／影响—未解释项—责任／复查条件”，需要完整替换稿时仍交完整受影响正文。所有省略范围明确未读或未检查；图义、实际显示和专业结论另验。

## 解释报告

| 记录 | 用途与边界 |
| --- | --- |
| current / baseline | 实际ZIP字节hash、主文档部件、逐部件hash、正文块、XML位置、书签、未解释结构及关系 |
| blocks | 段落字面文字与矩形表格；表格逐XML行/单元格定位，不推断合并后的视觉列号 |
| bookmarks | 同一文件中按数值id配对起止；跨版本按唯一、完整的name关联。显示编号和数值id可以变，不能据段落位置猜身份 |
| paired_bookmarks | 同名书签的原文差异、块位置变化及一个包含变化的字面区间；该区间不是语义修改分类或完整修订历史 |
| unanchored_text_ranges | 未被已确认书签区间覆盖的实际文字。书签只碰到一段的一部分，余下文字仍须核身份 |
| unresolved_bookmarks | 名称重复、起止不齐、数字id复用、未解释范围或一侧未定位；不擅自认定条款被删除或新增 |
| changed_parts | ZIP部件内容的字节变化；样式/图片变化仍须视觉检查，不能由正文相同推定版式相同 |
| drawings | 本次正文遍历实际遇到的绘图位置、所属正文块、非可视属性、图片关系及嵌入部件字节绑定；不是图义或版式解释 |
| paired_drawings / unresolved_drawings | 按唯一docPr名称标签对照图片字节与绘图标记；缺名、重名或一侧未定位保持未配对，不按编号、顺序或相同图片猜身份 |
| unresolved_fragments / notices / unread_parts | 修订、域缓存、被跳过的结构、样式继承与未读取部件；不能当作无修订、无隐藏或无附件 |
| content_inventory | 工具1.3新增的跨部件指定XML标记清单：部件hash、位置、类别及隐藏开关声明；不摘录内容或个人属性，不解释显示／继承或清除风险 |

所有成功报告的`status`仍是needs_review。`readback_state`和`comparison.state`中的complete_supported_subset只表示上述有限字面子集已覆盖；有未解结构、部件或身份则为partial。professional_review、visual_review、external_action保持not_performed，official_status不作断言。书签本身也可被复制、改名或错误移动，不能用同名证明真实来源或作者意图。

范围偏移是各自正文**字面流中的零基Unicode字符**；不是DOCX字节、Word页码、可见屏幕坐标或原始材料citation。不能直接复制为`tools.fidelity`的来源位置；须对实际新文本重新建立文档版本、引文和覆盖后再复核。

## 嵌入图片的位置与字节回查（工具1.2）

`drawings`记录实际主部件、XML位置、正文块序号及当时字面流偏移；图像没有被展平成文字。`wp:inline`与`wp:anchor`的原始属性、extent属性及`wp:docPr`非可视属性按读取结果保留，不换算页码、裁切效果或屏幕位置。正文块位置不是稳定身份；图可能移位而保留名称。

每个`a:blip`的`r:embed`和`r:link`分别记录，二者同时存在时也不省略外链。只有实际主部件中的对应image关系为内部关系、目标部件存在时，才给`embedded_part_bound`及该部件的SHA-256和字节数。缺失关系、错误类型、外部目标与缺失部件分别列状态；链接目标不访问。这里只绑定已有字节，不解码PNG、验证媒体类型或证明该图片忠实表达源图。

跨版本只对照两侧各有一个、名称非空的单一容器docPr标签；不使用数值id、关系id、文件名、位置或同hash图片推断身份。这个名称仍由文件作者控制，`caller_label_only_not_certified`不证明同一真实图件或来源。改名、重名或没有可用标签时查看`unresolved_drawings`及两侧XML位置，交材料负责人确认。

- `embedded_bytes_equal`只比较顺序明确且均已绑定的嵌入引用字节序列；存在外链、缺件或未绑定引用时为空，不能按缓存图相同推断链接图相同。
- `serialized_drawing_markup_equal`比较本次解析后重序列化的绘图XML哈希，不是原文件内子字节区间，也不是OOXML语义或视觉等价。关系编号、属性序列化、裁切、尺寸或其他标记变化都可能使它不同。
- 图片字节相同而绘图标记变化，或正文／标记相同而媒体被替换，都分别记录。无论字节是否相同，视觉、技术图义和专业核稿状态不提升。

此范围仅覆盖正文遍历实际遇到的绘图，不包含被跳过的修订、内容控件、页眉／页脚等其他部件。所有绘图原有未解释提示、媒体未解释部件及partial状态继续保留；不能据此清除样式、隐藏内容、嵌入对象或其他未知项。上限为2048个正文绘图、4096个图片引用，超限报错，不输出截断的成功结果。

## 跨部件修订、批注和隐藏标记（工具1.3）

`current.content_inventory`与存在时的`baseline.content_inventory`分别绑定各自文件；遍历包检查器已经解析的XML部件，包括正文读取器跳过的修订／内容控件及未解释的页眉、批注等部件。只识别Transitional WordprocessingML命名空间中的`ins/del/moveFrom/moveTo`、`comment/commentRangeStart/commentRangeEnd/commentReference`及`vanish/webHidden/specVanish`，不凭文件名或同名外部命名空间猜类别。不是全部OOXML修订类型、批注扩展、视觉隐藏或二进制对象的识别器。

每项给`part`、`part_sha256`、`namespace`、`element`、`category`和`locator`。位置是XML根开始、按同本地名兄弟计数的一基路径，不是页码或屏幕坐标，也不是自动配对身份；同一批注的正文及起止标记可能产生多项，清单长度不代表批注／修订条数。未关联的XML部件也会被枚举，标记存在不能证明它参与当前文档显示。部件内的文本、批注作者、时间和标识属性不加入此清单；整个旧报告仍可能包含正文、修订片段及关系目标，不因此变成可公开材料。

隐藏标记的`declared_value`只记录`true/false/1/0/on/off`，无属性为`omitted`，其他值为`unrecognized`，不转存任意属性原值；`effective_visibility`一律`not_evaluated`。直接`false/0/off`、样式中的同值、继承和实际可见性不同，清单不计算这些效果，也不接受／拒绝修订。原`notices`、`unread_parts`、正文覆盖和`partial`判断继续保留。

处理顺序：先按当前文件hash选择清单，在对应部件／XML位置核本项线索；再由获准的办公／内容审阅流程确认实际内容、作用域及允许的处理；如需删除、接受或拒绝，由相应材料责任人确认并形成新副本，重新核新字节及实际表现。基线与当前清单只给各自事实，不按相同位置宣布同一批注已删除，空清单也不证明隐藏内容、附件或秘密全部不存在。

扫描状态仅为`enumerated_markers_only`，`hidden_content_clearance=not_assessed`；整体仍`needs_review`，视觉、专业和外部行动不升级。最多扫描200000个XML节点、返回4096个标记，超限分别以`docx_inventory_scan_limit`或`docx_inventory_count_limit`拒绝整次回查，不返回截断成功报告。无网络、Office、宏、外链或二进制载荷执行；原ZIP/XML资源限制仍适用。

## 已支持与未解释项

- 支持Transitional WordprocessingML主文档中的直接段落、普通运行、文字、制表/换行、矩形原生表格，以及可跨段或相互重叠的完整书签区间。按OPC根关系选实际主部件，不硬编码默认路径。断行或拆分run可保持字面相等；数字、单位、否定和条件不归一化。
- 带`colFirst/colLast`的表格书签可能只选不连续列，本工具不解释，其text为空且记录未核；不把整个连续窗口当成被选文字。合并、嵌套表格也保持partial。
- 生成器1.2把整表起止放在首尾单元格段落内；此前1.1的表外包围书签在已测LibreOffice保存后曾缩成空范围。即使名称还在、全稿文字没变，也必须核区间覆盖；不能把空书签当作整表身份已保留。
- 插入、删除及移动修订不自动接受或拒绝；修订文字另存fragment。域指令和缓存不执行、不更新、不作为已核正文；复杂域未闭合、域引用或书签未核分别记录。
- 保留直接隐藏运行中的字面文字并提示隐藏属性；direct false/0不等于开启隐藏。样式中的隐藏开关与继承未解释，不能把样式false当作全稿可见，也不声称识别所有视觉隐藏方式。
- 主正文内的普通书签超链接可定位到该子集；未定位或带未核关系目标则提示。不能把正文查不到说成整个文件引用必坏。自动编号、样式编号及字段结果不作权威条款号。
- 页眉/页脚、批注、脚/尾注、公式、形状、图片、内容控件、嵌入对象和额外部件不自动展平进正文；逐项列未解释。图片只绑定字节，图文、裁切、分页仍须实际观察。外部关系仅记录，不访问目标，不开启宏、嵌入程序或外链。
- 当前拒绝Strict命名空间、宏主文档、加密、不合法或歧义包结构。ZIP不落地解包；有大小、部件数、XML节点/深度及文字/书签范围上限，拒绝DTD/实体及危险路径。资源限制不构成安全认证或完整OOXML一致性验证。

默认上限：ZIP 16,000,000字节，解压总量64,000,000字节，1024成员，单部件16,000,000字节，单XML 8,000,000字节/100,000节点/128层；正文2,000,000字符、2048书签、书签区间总计8,000,000字符、10,000正文块。超过限制须换获准处理方案，不能将截断结果报全稿。

## 从差异到返工

1. 逐项对照变化的条件、例外、数值、单位、引用和图表。仅是字面差异时也不要自动标法律/技术等价；专业变化回patent、software或standards。
2. 未核身份回材料负责人确认稳定条款；不要按“原第8段”把后续意见强接到“新第8段”。保留旧编号、书签、两版实际hash及确认依据。
3. 编辑后的DOCX若成为新稿来源，先纳入新的源版本/区间及对应事实关系，再重建受影响文件；不能只改输出Word后宣称生成链已更新。当前回查器不自动把Word修改回写原稿。
4. 新包重新核正文、内部说明、图、关系及所需实际视觉/打印；旧签核和截图保留历史，不能改版本标签迁移。复验范围由变化及依赖决定，未覆盖部分单列。
5. 把文字核对、身份核对、隐藏内容、视觉、专业批准及具体行动分别交接。partial可交付有据发现及恢复条件，不能作为全稿放行。

## 技术依据

本方法的格式语义参照Microsoft公开文档，不复制其SDK实现，不新增依赖：书签起止按id关联、可跨段且表格列范围可能不连续，见[BookmarkStart](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bookmarkstart?view=openxml-3.0.1)；隐藏属性的直接格式与样式开关行为不同，见[隐藏文字](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-remove-hidden-text-from-a-word-processing-document)；删除修订独立于普通运行文字，见[DeletedRun](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.deletedrun?view=openxml-3.0.1)。这些技术说明不提供专业/官方格式批准。

图片关系与非可视属性的本次实现另参照[Blip的嵌入与链接属性](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.blip?view=openxml-3.0.1)、[Inline](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.wordprocessing.inline?view=openxml-3.0.1)及[DocProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.wordprocessing.docproperties?view=openxml-3.0.1)，2026-11-03核对公开可读内容。使用现有Python标准库解析，不安装Open XML SDK；没有执行格式一致性认证。
