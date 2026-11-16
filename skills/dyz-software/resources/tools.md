# 软件工具契约与调用

运行本地选材、秘密处理、事实稿或一致性辅助时阅读；命令以包根运行，沿用入口的读取前权限检查。 返回[技能入口](../SKILL.md)。

## 运行依赖与调用前检查

这是有运行工具依赖的专业入口，**单个SKILL.md不是完整安装包**：

- Python 3.11标准库；无第三方依赖、模型调用、网络调用或上游复制代码。
- 部署须保留完整包的 `tools/` 白名单，包含software、software_discovery、software_revision、software_import、software_delivery及其共享依赖，并使包根位于Python模块搜索路径；共享契约 `SCHEMA_VERSION=1.0`。
- 此目录内的 [demo.py](../demo.py) 是完整可执行合成案例。安装为独立包时保留该资源，并验证 `from tools.software import CAPABILITIES, run` 成功。不依赖 `.references/` 或开发机绝对路径。
- 原创代码沿用项目PolyForm Noncommercial 1.0.0及单独商业授权边界；不覆盖用户源码、第三方许可、登记表或标准材料权利。不得把本技能称为OSI开源许可产品。

### 工具输入、路径与留痕

每次 `run(capability, payload)` 必须带 `context`：`environment`、`permissions`、`sensitivity`、`purpose`、`now`。权限记录必须逐动作、目的、接收方匹配，带有权依据、有效时间；时间须含时区。合成案例可使用空环境；真实秘密/受限材料必须先由共享 `preflight` 核实宿主模型、索引、遥测、工具、日志、子进程六条数据路径及证据，外部处理另行授权。

源码根必须显式为 `authorized_root`，文件逐项列出，工具不递归采集其他目录、不执行源码。路径穿越、盘符、ADS、根外符号链接拒绝；根及文件在调用期间须由调用者保护不被其他进程修改。该工具是单次文件字节/文本快照，不是文件系统锁、可信时间戳或防篡改取证系统。宿主在调用前读取/索引和手工外发不受本工具控制；不能宣称仅因本地Python即全程离线。

所有输入正文已送入宿主时，函数中的预检无法撤销先前传输。私人源码不得为了测试贴入云端对话；公开样例和默认测试仅使用合成数据。缺授权时停在读取前。错误消息不复制正文或绝对文件路径；不要在CLI外围打印原始payload。

## 逐能力契约与步骤

所有工件含 `kind`、`binding`。binding为规范JSON哈希，用于一致性检查，不是有权签名；不得绕过旧工件校验自行修改binding来继承审核。输入其他能力时传结果的 `artifacts`，不是整个结果信封。

| 能力 | 输入与操作 | 实际输出、异常和边界 |
| --- | --- | --- |
| SW-01 | `metadata`含software_id/name/version，日期为value/evidence_id，runtime_environment为description/evidence_id；`components`含id/kind/version/origin/claim/exclusions/subjects。多组件给grouping_basis；升级/改编给baseline_evidence。 | software_scope表，原版/本版/主体/排除范围、冲突/未知清单。多主体缺共同权利依据标冲突，不从Git作者、提交日期推定权属、完成或发表。权属始终待专业判断。 |
| SW-07 | `scope`、逐组件`rights`：component_id/requested_decision/evidence_ids/permissions；第三方带license/notice；AI带human_contribution.description/evidence_ids。 | software_rights逐项claim/exclude/retain_notice/needs_permission/needs_evidence/prohibit。local_process、deposit、public、cloud权限独立；许可证名字不替代授权；缺人类贡献不伪造作者。先于选材执行。 |
| SW-02 | `scope`、`rights_decisions`、授权根、files、inventory_complete及pagination。每文件id/path/component_id/kind/include；排除必须exclusion_reason；可给ranges、encoding、source_type_evidence。 | software_source：真实字节SHA256、稳定ID顺序、文件清单、源码行/列映射、逻辑分页、排除清单、源量与选材量。禁止处理/缺处理权不读字节；选材目的默认为deposit，未获该用途不得选入；third_party、生成物与依赖不冒充原创。 |
| SW-03 | `material`、redactions（file_id/line/start/end/basis_id）、sensitive_literals，可带deposit_rule.evidence_id/review_evidence。 | software_masked的document与private_audit独立；按Unicode字符1基闭区间掩码，不保存被删原值；同值在元数据、其他行及通知中亦清除。未列出的秘密无法自动识别，语义/隐藏信息仍需人工检查。无例外交存规则只生成内部稿，不认定可交存。 |
| SW-04 | `scope`、mode=GUI/API/CLI/embedded、带证据的facts、operations（input/expected_output/failure/evidence_id），可带同版runtime_evidence。 | 可编辑Markdown说明稿，事实、操作及失败路径、证据引用。无运行证据static_only，不生成截图。GUI可引用实际截图证据；其他形态不适用GUI截图。引用运行证据不等于本工具运行过软件。 |
| SW-05 | `scope`、`material`、`manual`、form及可选field_limits、form_rule_evidence。 | software_consistency逐字段矩阵；名称、版本、日期、运行环境、总源量/选材量及上游版本绑定对照；不覆盖冲突，不以选材行数改写真实源码量。规则/日期未知待补；checked仅为确定性检查。 |
| SW-06 | before/after软件scope，event含id/type/evidence_id/source_status，notice_items、逐项responses、prior_reviews、可选deadline。 | software_correction保留新旧版本链、通知与替换位置、未答复项、相关旧签核失效及重审清单。type支持correction/change/succession；期限调用共享记录，但语义所有者SW-06，不套专利OA或固定天数。 |
| SW-08 | `scope`、branch=adaptation或dispute。adaptation用targets（jurisdiction/route/requirements及规则证据）；dispute用pairs（分类、左右版本/文本/来源定位、接触和来源证据）。 | 各地区要求映射/缺件表，不继承中国分页，无法确定规则时未核验；无登记路线单独not_applicable。争议仅对expression定位字面相同区段，功能/第三方/既有内容排除，接触/来源未知单列，不输出实质相似或侵权结论。 |

### 源码和分页细节

- `files.kind`为source/dependency/generated/other；已知源码后缀为工具内清单，未知后缀必须给 `source_type_evidence` 才按源码处理，否则显式排除。支持严格utf-8、utf-8-sig、utf-16、gb18030、ascii解码，乱码/二进制显式排除，不替换成伪源码。单文件默认上限10,000,000字节，`max_file_bytes`可显式设置。
- `pagination`必须给lines_per_page、wrap_columns、selection、basis；selection为all或head_tail，后者另给pages_each_end。参数是调用者的版式依据，工具**没有全球或中国统一的内置法律分页规则**。短程序全部真实输出，不填充、不重复凑行。
- 长行按Unicode代码点折行；columns为代码点位置，不是字节偏移、字形宽度或打印机列宽。每渲染行保留file_id/source_line/column_start/column_end。空行保留实际空行，尾换行不新增虚假行。
- `total_source_lines`为已成功解析的声明清单源码总行数，包含清单中未选择的源码；`original_source_lines`为非第三方/生成物/既有分类的行数统计，不认定独创性；`selected_source_lines`为实际选取的去重原行数，`rendered_lines`为折行后的行数。
- `quantity_scope=declared_inventory`，inventory_complete只是调用者对清单完整性的声明，不是工具扫描整个产品的证明；未读、乱码及未知后缀不伪造行数。清单不完整返回partial，不得宣传已测得整个软件的真实总源量。
- `previous_material`可提交上一份source工件；内容、范围、权限或分页变化输出invalidated及supersedes。上下游scope/rights绑定不匹配拒绝或报告待重审。
- 返回JSON中含真实选定源码；该source工件本身可能敏感，不可直接公开。SW-03不复制完整源manifest、原始排除理由或原源码进脱敏结果。private_audit不默认放入外发包。正式持久化使用共享 `write_new_json` 写入明确授权私人根，拒绝覆盖；不覆盖源码。
- SW-02自身只输出JSON逻辑分页，SW-04输出Markdown；办公成品另走下述build-software链。该链的候选A4版式与真实PDF回读仍不等于官方接受，不能把JSON页数当官方分页已通过。

### 状态与责任

`run`返回共享信封：capability/status/artifacts/issues/evidence/adaptation/checks，并始终明确professional_review=not_performed、official_status=not_asserted、external_action=not_performed。输入结构、哈希、权限、路径错误抛ContractError；规则未知保留内部计算成果，不把unknown当通过。

技术事实由技术负责人确认；软件版权专业人员确认权属、人类贡献、排除、交存、各地区规则及争议分析；权利人确认具体行动。AI互评不等于签核。正文、内部风险报告和私有审计分别交付。SW-03/07涉及未公开技术时，交PROC/ANALYSIS/REVIEW审查实际申请支持，再经共享CORE门禁处理具体包/对象/用途/渠道/条件；软件登记许可不外溢到公开源码或标准提案（DG-08、DG-17、DG-19）。本模块没有发送出口，不代替共享WP-04固定包审批、执行前复核、回执、结果不明和事件闭环。

## 获准本地软件准备入口（首批）

完整仓库或当前源码复制包提供 `python -m tools prepare-software`，调用 `tools.software.prepare(payload)` 自动衔接SW-01/07/02/04/05。普通用户不必自行装配各阶段binding；Agent根据已获准事实组织请求，关键事实及用途仍由有权人确认。**首批只生成内部准备JSON，内含源码快照、字段工作表、说明Markdown和问题清单；不是DOCX/PDF、正式交存包或自动登记。** 不读取未列出的项目文件，不扫描目录，不执行源码，不联网，不新增依赖。

原 `run --synthetic`、`dispatch`、83项目录支持级别及文档装配模式不变。此窄入口支持synthetic/public/confidential/restricted，但实测采用合成内容模拟各敏感等级，不代表真实私有案件已验收。

### 两份输入及前置授权

1. 授权描述只放非敏感控制信息，`kind=software_local_authorization`；`authorized_root`为获准私人目录的绝对路径；`request`为任务文件的相对`path`与实际`sha256`；`files`列出每个获准源文件的相对`path`和实际`sha256`；`output`是该根内尚不存在、扩展名为.json的结果文件。不得将源码、证件或秘密正文放入授权描述。
2. `context`必须有environment、permissions、sensitivity、purpose。permissions须同时具有与purpose/local_tool匹配、有效且带有权依据的`local_read`和`local_write`记录。confidential/restricted还须六条宿主数据路径的核实证据；外部路径另核external_processing许可。
3. 执行者确认授权范围及其描述SHA256后，再运行命令。工具在读取任务正文前核授权字节、根目录、权限和有效期；真正的系统时钟用于有效期检查，载荷中的旧now不能恢复过期许可。授权描述上限1MB、任务JSON上限10MB，拒绝重复键及非JSON数值。
4. 任务JSON只接受scope_input、rights、files、inventory_complete、pagination、manual_input、form、form_rule_evidence、field_limits、field_candidates、confirmations、previous_preparation。前五项必需；scope_input沿SW-01，rights沿SW-07，manual_input沿SW-04。不允许请求覆盖context、authorized_root、selection_purpose或严格母本检查。
5. 任务files必须与授权清单逐路径对应，允许显式exclude但不能悄悄漏项。入口注入expected_sha256，源文件内容变化则拒绝，不产新的结果。禁止处理的文件仍不读字节，因而其hash未验证，完整性也不得记为complete。

在完整包根运行（两个变量由执行者从已确认的私人目录和授权描述取得，不是模型生成的许可）：

```powershell
python -B -m tools prepare-software --root "$privateRoot" --authorization authorization.json --authorization-sha256 "$authorizationSha256"
```

输出路径来自固定授权描述，不能在命令里临时换成另一目标。父目录必须存在，禁止覆盖原文件；返回0仅表示内部JSON写出成功，仍须查看status/issues；2为结构/权限/指纹拒绝，3为本地IO失败。stdout只打印result_written，错误不打印材料或私有路径。授权清单校验后、任务实际读取前、逐份源码读取前及写出前重核当前有效期；符号链接环和时间转换溢出也返回脱敏拒绝。

授权文件和SHA256是调用者提供的范围与版本记录，不是身份认证、数字签名或技术隔离；工具不能验证授权依据真假，也不能撤销调用前的宿主读取。不要为运行命令编造授权，真实任务不能冒标synthetic。

### 主张、交存上下文与完整母本

低层SW-02新增可选 `selection_basis`：默认claimed_expression保持历史行为；deposit_context仅用于local_process/deposit，不能用于public。claim正常选材；exclude/retain_notice若确须作为交存上下文，须在该文件给出非空deposit_context_evidence并具备对应用途许可。needs_evidence、needs_permission、prohibit不会被上下文选项绕过；第三方上下文还须具备license和notice，不能利用旧exclude分支跳过这些记录。原生成物/依赖处理不变，第三方上下文不进入原创分类统计。

新增 `require_complete_source` 默认为false；准备入口固定为true，并固定selection_basis=deposit_context、selection_purpose=deposit。`source_coverage`在首尾抽取之前检查母本：status为complete/partial，列candidate_source_lines、omitted_file_ids与incomplete_range_file_ids。未读/解析失败、源码漏项、只选部分ranges或inventory_complete=false不能称完整；严格模式报告source_coverage_incomplete。首尾抽取不会把本来完整的母本误记为缺失。

该检查只覆盖**调用者声明清单**，并不发现未列入清单的源码、证明整个软件完整或验证实体分页。传统SW-02仍可生成有理由的内部选段，但不据此认定一般交存完整。可选expected_sha256也适用于传统SW-02；给出时须匹配实际读取字节。

prepare的工件kind为software_preparation，含scope/rights/source/manual/form/consistency及binding。未交manual_input时保留源码/字段、manual与consistency为null并报告manual_input_missing；自动字段只复用已有metadata和实际源量，不填日期/权属/运行事实。有form时保留输入并作一致性检查，不覆盖冲突。状态最多needs_review，任何步骤needs_evidence/partial或缺说明均汇总为partial；仅public/cloud未授权不阻断有权的本地/交存准备。previous_preparation接先前信封的artifacts，绑定验证后变化在新工件记录invalidated列表/supersedes，总status仍是needs_review/partial；不恢复旧专业签核。

该JSON包含原始选材与内部权利信息，`output_scope=internal_only_not_for_submission`。披露检查器将嵌套源码识别为内部工件，不直接外发；可交下述成品链做截图/办公装配和物理回读，秘密语义、视觉、权利与专业放行仍需独立审查。

直接函数 `prepare(payload, use_system_time=False)` 与旧run调用保留可复现的context.now语义；真实执行应传use_system_time=True，使用当前时间逐阶段和逐文件预检。CLI固定启用该参数，任务JSON不能关闭它。

首批定向回归命令（仓库根；临时合成文件自动清理）：

```powershell
python -B -m unittest evals.test_software evals.test_software_prepare evals.test_cli -v
```

## 软件成品链与集中采集

在完整包根调用，全部输出必须位于已获准私人根，且新目录不能存在：

```powershell
python -B -m tools software-intake --root "$privateRoot" --output intake-v1
python -B -m tools software-intake --candidates --root "$privateRoot" --output intake-candidates-v1
python -B -m tools build-software --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256"
python -B -m tools build-software --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256" --pdf-tool "$sofficeAbsolutePath" --pdf-text-tool "$pdftotextAbsolutePath"
python -B -m tools build-software --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256" --verify --pdf-text-tool "$pdftotextAbsolutePath"
```

两条构建命令是替代方案，不能对同一目录连续执行。先无PDF构建后若要加PDF，更新授权输出位置并确认新的授权hash，生成新包；不覆盖旧包。verify只回读，不转换，不能同时传pdf-tool。

- software-intake通过控制台收集处理许可、六数据路径证据、逐项源码、名称版本、事实与operation-N操作；GUI还可逐项提供现成PNG的路径、对应操作、实际版本、采集/本地使用权限与证据、visible_state。随后选择all/head_tail及已知敏感字面值，集中确认列明的源/图清单后才读字节；授权files为源/图并集，截图hash与源码build_binding自动装配。损坏PNG、错版、越界、重复别名、缺权限/依据拒绝；授权输出路径含声明敏感值也在读材料前拒绝，不回显该值。它只覆盖单组件，复杂组件由Agent按已有契约组织，用户不必手写各阶段binding。未提供的主体/日期/截图不补造，声明不是身份、运行事实或专业认证；不执行源码，不生成截图，不代作字段确认。
- build-software使用同一software_local_authorization契约，但output为新目录；files应为源码与截图的完整授权并集。request保留prepare字段，并可加delivery：selection为all/head_tail，screenshots为逐图绑定列表，sensitive_literals为需阻断的已知字面值。源码任务先以all构造母本，短程序不补行，不用先前逻辑首尾段冒充完整母本。
- 源码与说明候选在body/source.docx、manual.docx，配可编辑txt；字段工作表及txt存body/worksheet.docx/txt，整个构建目录仍是内部包；接收方副本只由export-software白名单生成，来源、确认者和内部依据不随接收方正文复制。缺说明时仅保留源码/字段并明确partial；内部准备、原行映射、完整母本及物理检查保留在internal，不默认外发。manifest记录实际字节、工具hash、缺件与检查范围。
- screenshot条目须有id/path/sha256/version/operation_id/build_binding/capture_evidence/local_use_evidence/visible_state；id对应manual_input.runtime_evidence中的截图，步骤必须存在，build_binding为source.manifest中source文件file_id/sha256有序列表的规范JSON摘要。相同文件名换内容、换版本、换步骤或换构建均拒绝。PNG须为可检查的静态结构；不生成伪SVG或伪截图，带未支持元数据的原图应另有有据清洁副本。可选visual_review需绑定图hash、actor、evidence和status=reviewed，只记录调用者审查，不认证图片真实。
- 已知秘密按原始字符串扫描源码、表单、事实与图片说明；命中则在写正文前拒绝，不自动掩码后放行。另复用fidelity.scan_placeholders并检查STOP_FOR_USER/NEXT_ACTION流程令牌，在折行和抽取前扫描完整输入；内部稿可保留但报告定位并维持partial，text_review不复制私密问题正文，verify重建扫描结果，清空自报问题不能绕过。没有列出的秘密、图片像素中的秘密和语义泄漏仍需人工审查；SW-03的例外交存/脱敏用途独立。
- 源码候选50展示行/逻辑页，以全角/Tab估算预折行但保留原文及原行/列映射；说明按内容与图片排布。PDF读取实际页数、文字、行位置及页边界，检查器失败/不足不会标为通过。一般路线与例外仍要当前规则及专业确认。
- head_tail对程序和说明分别建立完整母本，各自实际PDF检查成功后才取前后各30个物理页，各自不超过60页全取；选段再渲染再检查。源码沿selected_mother_pages/selection_applied，说明用manual_selected_mother_pages/manual_selection_applied；physical_review.manual_mother及internal/manual-mother.docx/pdf保留完整说明证据，映射中manual.pages绑定选段页、母本页与block_ids。任一母本失败时该文档保留全量内部稿和独立未验状态，不拿另一文档的成功替代；工作表不做首尾抽取。
- 返回0表示本次技术操作完成且仍needs_review，4表示已保留partial成果/缺件/版式失败，2为输入/权限/绑定拒绝，3为IO失败；IO中断可能留下无成功清单的部分目录。所有输出始终internal_only_not_for_submission，visual_review与professional_review不由机器回读升级。
- PDF可选依赖为已安装的LibreOffice及Poppler pdftotext；必须显式传绝对路径，工具不安装、不联网、不启动长期服务。转换使用隔离临时profile，不接用户日常办公实例。默认运行仍只需Python3.11标准库。

### 字段候选、集中确认与变化失效

prepare/build请求可传`field_candidates`与独立的`confirmations`。候选不是事实，不能由模型把candidate直接改为confirmed。

- 候选严格包含field/value/status/sources，基础字段为software_id/name/version/completed_date/published_date/runtime_environment；可选目录扩展development_hardware/runtime_hardware/development_os/development_tools/runtime_platform/runtime_dependencies/programming_language/development_purpose/application_domain/main_functions/technical_features，使用value/evidence_id对象；没有提供的可选项不强造法定必填；状态为candidate/inferred/conflict/unknown，unknown的value必须是null。日期/环境沿metadata的带证据对象，不从文件时间或运行机器补值。
- 每项sources为`{path, sha256, locator}`或`{evidence_id, locator}`。文件来源只对照已授权读取的source.manifest，不因候选路径额外读文件；证据引用只对照现有字段或manual事实/步骤/运行引用，引用存在不认证事实真实。
- 首次prepare生成worksheet.rows/questions及input_binding；无候选的已填值仍为declared，未知为unknown。操作者集中核对值、来源与冲突后，独立确认记录须含candidate_digest/input_binding/status=confirmed/actor/role/evidence_id。Agent可代装配结构，不能替有权人作确认。
- 仅当前绑定且无冲突/未知/失效来源的确认可填入form，不修改scope、权属、源码计数或运行事实。字段DOCX同时列未采纳候选、原声明、来源/hash/locator、采纳状态及确认者/角色/依据和绑定，不能只看表单当前值；来源位置本身可能敏感，整个工作表仍仅限获准内部用途。准备阶段issues随工件进入成品链，版本冲突和待确认不会在导出时丢失。
- 相关输入变化使旧确认失效，previous_preparation记录dependencies/changes/invalidated/supersedes；同内容复用旧快照，不自增历史链。源码字节不变的日期或主体变化不无故改变截图build_binding。
- software-intake保留逐项路径，并支持候选集中确认：先给明确允许的文件和逐文件/分组处理许可，再核候选摘要、当前input_binding及勾选范围；confirmed只展开操作者本次实际确认的eligible候选。日期、权属、原创、性能不由自动发现补齐，未知保留。

### 本地成品验收命令与边界

仓库根的确定性回归（复制包不含evals）：

```powershell
python -B -m unittest evals.test_software_delivery evals.test_software_delivery_review evals.test_software_documents evals.test_software_layout evals.test_software_intake evals.test_software_facts
python -B -m evals.software_delivery_acceptance --output "$newAcceptanceDirectory" --pdf-tool "$sofficeAbsolutePath" --pdf-text-tool "$pdftotextAbsolutePath"
```

验收目录必须是新的且父目录存在；只使用明确标记的合成源码/像素夹具，不能称真实GUI运行截图。Windows上已实际使用LibreOffice 26.2.5.2与Poppler pdftotext 25.02.0，Word/WPS及其他系统未据此验证。完整矩阵包括59/60/61页母本、事实变化拒旧包、GUI原PNG、Tab/长行/原始LF及标题版式，实际每轮结果见施工台账，不承诺每个输入都通过。

`check_scope=pdf_text_geometry_and_candidate_pagination`只证明实际文字几何/候选分页；含图时image_rendering=not_verified，visual_review=not_performed。图注坐标不是图片坐标，实际PDF图片像素、尺寸、位置须另看；空行也不能被提取器证明为有效代码行。字形框不等于文字基线：不同字体框高间的行距标记line_pitch_check=partial_font_metrics，baseline_verified=false，不以框顶差误判或宣称基线已测；原边界/重叠检查仍执行。verify不信清单自报成功状态，重建DOCX、映射和文本扫描；程序/说明首尾选择须各自连同完整母本重查，selection_verification分别给checked/not_verified/not_applicable，未传PDF检查器不能沿用旧的物理页通过。成品生成器为1.2，记录当前工具源码hash和输入快照；1.1只按历史兼容回读，不虚构当前代码证明。旧格式结果不覆盖；需要新检查覆盖时使用新授权输出目录重建。

## 完整正文、新稿和接收方候选

`manual_input.blocks`优先于旧facts/operations骨架，包含id/kind/text/evidence_ids/status，可带section、operation_id、image_id及来源定位。支持heading1/heading2/paragraph/code/list/table/image；列表/表格保留文本与结构来源，重新排版而非任意Word无损往返。ID保持稳定；没有依据或未确认的块保持needs_review。prepare为每块生成input_binding，绑定块内容、scope、源码及事实/步骤/运行引用；提供previous_preparation后，变化块或源码依赖变化块的旧confirmed降为needs_review。重新确认需在块内提供confirmation={input_binding,actor,role,evidence_id}，绑定本次准备结果中的当前块input_binding；仅保留旧status/evidence_ids不能恢复确认。facts/operations/runtime_evidence继续作为事实及操作索引。名称/版本用document_metadata与scope并排核，冲突拒绝，不能全局替换掩盖。

Markdown或DOCX新稿需在授权files中独立列path/sha256，任务加`manual_revision={path,sha256,format}`，format为markdown/docx。可提供document_metadata核软件身份；previous_preparation引用旧准备包artifacts。新稿保留来源hash、块级差异、名称/版本变化及旧manual绑定，所有导入块重新待审；旧原件、旧包和旧verify不变。

```powershell
python -B -m tools import-software-manual --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256"
python -B -m tools import-software-manual --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256" --build
python -B -m tools discover-software --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256"
```

前两行择一：默认输出新的准备JSON，--build直接生成新的成品目录；PDF需显式已安装工具参数。修订图片只接受逐项授权screenshots：Markdown引用与其path匹配，DOCX内嵌PNG与其原图sha256匹配；两者仍须既有运行、步骤、版本、捕获与本地使用证据，不把Word内嵌图片当作真实性证明。缺原图授权、浮动图/文本框、复杂域、修订标记、外部关系或未支持对象明确拒绝，不输出伪成功。DOCX页眉保留为内部来源，原版式不继承。

Markdown可用`<!-- block:stable-id evidence:source-id status:needs_review -->`锚点；所有导入确认均重新待审，文档注释不能替代有权确认。对全稿（包括未选页、页眉和差异）扫描声明敏感字面值；未声明秘密、图片像素与语义仍需审查。

discover-software沿用固定授权控制文件和task.files；每项须有组件rights的local_process依据或明确local_permission。只读列出的配置/README/源码，不递归扫描；name/version/environment/function均为候选，来源path/hash/locator跟随。机器候选不自动写入事实。其输出是内部候选JSON，不能当作外发申请表。

受限宿主的`case_software`复用相同授权CLI函数；prepare/build/verify与采集分别受schema限制，返回文件索引和问题码，不返回源码或完整许可。仅本地执行证据不证明宿主自动发现或模型任务已通过。

多项目用固定hash的批次控制JSON：`projects`每项包含id/root/authorization/authorization_sha256/action，action为prepare/build/verify，可enabled=false跳过。root为各自独立绝对目录，拒绝重用；每项目独立输出和状态，单项失败不覆盖其他结果。

```powershell
python -B -m tools software-batch --root "$controlRoot" --input batch.json --input-sha256 "$batchSha256" --output batch-results.json
python -B -m tools export-software --root "$privateRoot" --authorization "$authorizationPath" --authorization-sha256 "$authorizationSha256"
```

export-software任务除原构建字段/delivery外增加package（已有内部包目录）及export_approval。审批含files[{path,sha256}]、recipient/purpose/channel/evidence_id；权限另须同用途local_read/local_write及向该对象copy。仅允许body/source或manual的txt/docx/pdf及已确认字段投影application-fields.json，工作表、内部map/hash/确认者不纳入。未确认正文、来源冲突、未核图片或用途权利缺失阻断相应导出。只写本地接收方候选，不发送、不登记；具体发布或提交另核行动授权。

manifest记录代码快照、输入/图字节、确认输入绑定、工具版本、页数来源及视觉/专业未审状态。estimated与rendered分开，没有Word原生/人工确认就不标native_word/human_confirmed；共享工具变化时当前包需重建或明确历史回验。

## 完整合成JSON调用例

以下为完整SW-01请求，可另存临时 `sample.json`；所有事实、许可、主体和日期均为合成。合成的固定now仅为可复现测试，不得用于真实授权到期判断。

```json
{
  "context": {
    "environment": {},
    "permissions": [{
      "action": "local_read", "purpose": "synthetic_demo", "recipient": "local_tool",
      "decision": "allow", "authority_evidence": "synthetic-consent",
      "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"
    }],
    "sensitivity": "synthetic", "purpose": "synthetic_demo", "now": "2026-10-31T10:00:00Z"
  },
  "metadata": {
    "software_id": "demo", "name": "合成计数器", "version": "1.0",
    "runtime_environment": {"description": "Python 3.11 CLI", "evidence_id": "synthetic-env"},
    "completed_date": {"value": "2026-10-01", "evidence_id": "synthetic-date"},
    "published_date": {"value": "2026-10-02", "evidence_id": "synthetic-publication"}
  },
  "components": [{
    "id": "cli", "kind": "standalone", "version": "1.0", "origin": "own",
    "claim": ["本版命令表达"], "exclusions": ["Python运行时"],
    "subjects": [{"subject_id": "demo-owner", "basis": "合成合同", "evidence_id": "synthetic-contract"}]
  }]
}
```

```python
import json
from pathlib import Path
from tools.software import run

payload = json.loads(Path("sample.json").read_text(encoding="utf-8"))
response = run("SW-01", payload)
assert response["artifacts"]["kind"] == "software_scope"
assert response["official_status"] == "not_asserted"
print(response["status"])
```

八项完整纵向演示在demo.py：从零生成临时合成源码，经过scope、rights、源码映射、掩码、CLI说明、一致表、补正链及两个跨境/争议分支，最后删除临时目录。使用仓库或部署包根为工作目录：

```powershell
python -c "from runpy import run_path; run_path('skills/dyz-software/demo.py', run_name='__main__')"
python -m unittest evals.test_software -v
python -m py_compile tools/software.py evals/test_software.py skills/dyz-software/demo.py
```

独立部署不带evals时，保留运行demo的验证，不能声称完整AC回归已执行。demo打印每能力的真实状态和缺口，不打印源材料；SW-05为checked，SW-06为invalidated，其他保留needs_review/未核验。这些状态是预期边界，不应为了演示改成统一通过。

## R11字段候选的同版文件

[公开指南补核](../../../references/jurisdictions/cn-software-guide-20261103.md)支持对照[港湾字段候选](harbor-delivery-v1.2/form-candidate.md)的已知事实和未解项。[form-input.json](harbor-delivery-v1.2/form-input.json)绑定实际facts、五份源文件、原行映射、完整说明和研究版本；在完整包根运行：

```powershell
python -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-software/resources/harbor-delivery-v1.2/form-input.json --output outputs/harbor-r11-fields
python -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-software/resources/harbor-delivery-v1.2/form-input.json --output outputs/harbor-r11-fields --verify
```

父目录须存在、输出须为新目录；可选本机PDF转换及渲染观察按[文件工具](../../dyz-rendering/resources/tools.md)执行。产物是原创内部工作表，保持未知主体/日期/权利和未审状态；不是统一申请表、签章页或可直接交存的正式格式。255只描述所列文件的内部物理行，含注释/空行。变更任一依赖须重建受影响材料，旧检查不移作新版本通过。

## 验收与尚未验证

`evals/test_software.py`将AC与分支直接挂到测试名，合成fixture为 `evals/fixtures/software/synthetic.json`。测试会创建/删除临时文件，不触碰用户材料：

| 契约 | 自动化证据范围 |
| --- | --- |
| AC-SW-01 | 多组件升级冲突、主张/排除、日期未知、非法日期、重复组件、更名版本变化 |
| AC-SW-02 | 短程序真实行数、长程序首尾/逐行逐列、多字节、稳定排序、范围、未知后缀/乱码/生成物/依赖、路径穿越/ADS/符号链接、读取前预检、快照及权限用途变化 |
| AC-SW-03 | 字符掩码、元数据与重复秘密清除、独立审计不含原秘密、未改源文件、未知交存规则、登记与公开权限隔离、无敏感项和非法范围 |
| AC-SW-04 | CLI/API/GUI/嵌入式事实稿、无运行证据、非GUI截图不适用、旧版运行证据拒绝、事实变更 |
| AC-SW-05 | 名称/版本/日期/环境/字段限制、源量与选材量分列、不修改原记录、缺表单规则、过期scope |
| AC-SW-06 | 版本/权属变更失效、旧记录保留、逐通知应答、期限未知、来源不明、不适用通知、错误通知引用 |
| AC-SW-07 | 第三方排除、许可不等于public/cloud权限、人类贡献未知与补证、缺权利覆盖、禁止读取、空主张和非AI不强造AI事实 |
| AC-SW-08 | 表达定位、功能/第三方/既有排除、接触/来源未知、版本变更、无登记路线、跨地区规则缺口与变化，不产生侵权结论 |

已验证运行环境为Windows/PowerShell、Python 3.11.15；跨平台可移植结构不等于其他系统已执行。当前可用的是八项本地材料准备算法和合成纵向链，不是八项完整专业支持。现行CN/US或其他地区规则、官方交存接受、身份及权属证据真实性、独立专业盲评、真实GUI截图/业务运行、其他办公组合、外部适配和真实外发均未在此模块验证。当前成品链仅有上述Windows本地工具组合的合成渲染证据，不将其迁成真实产品或官方合规结论。必须取得具体资料许可、规则版本、运行环境和合格审阅资源后才能提升相应组合的支持等级；未知不由另一地区的成功样例替代。

## 软件1.3的变化与同版材料

[1.3使用说明](harbor-delivery-v1.3/manual.md)与[同版字段候选](harbor-delivery-v1.3/form-candidate.md)对应真实新增的可选id排序；旧1.2保持。CLI提供--sort-by-id，HTTP用sort_by_id=1，GUI有显式复选框；默认均保留输入顺序。不要把Unicode字符序当数值或地区排序。范围与权利未知见[范围表](harbor-delivery-v1.3/scope-and-rights.md)，原文件/原行映射及变化记录与材料同目录。

完整包根运行以下源码、说明和字段稿命令；每个输出目录须不存在，父目录须已存在。当前三张截图为实际合成软件操作，仅表示本次Windows/ego-lite观察。

```powershell
python -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-software/resources/harbor-delivery-v1.3/source-input.json --output outputs/harbor13-source
python -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-software/resources/harbor-delivery-v1.3/manual-input.json --output outputs/harbor13-manual
python -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-software/resources/harbor-delivery-v1.3/form-input.json --output outputs/harbor13-fields
```

对相同命令追加--verify回读；需要PDF时首次构建显式加本机已安装的--pdf-tool路径，仍须文字及逐页显示检查。源码PDF保留原文件/原行前缀，只是内部核稿母本，正式交存范围/格式另核；截图为独立PNG随包提供，现有生成器不把它们自动嵌入说明正文。旧1.2导出在其原输入下仍是旧版证据；不能拿新输入核成同版。绑定的源码、facts、映射或截图字节变化时先拒绝，再重建和复核，保留旧输出和旧审阅。

## 范围、贡献、秘密与字段的专业待审包

[完整待审稿](harbor-review-readiness/review-pack.md)连接五份源文件、1.2至1.3的继承／变化、20项字段、具体补证、选材用途及接收角色。[证据映射](harbor-review-readiness/evidence-map.json)给文件／函数／原行／字段行及SHA；19个行差异不是19项法律贡献，266物理行不是原创表达或正式程序量。主体、日期和真实权利未知保持；项目许可、Git信息和工具输出都不补权属。

在完整包根运行既有SW工具的[四个开发情景](harbor-review-readiness/review-cases.json)：

```powershell
python -X utf8 skills/dyz-software/resources/harbor-review-readiness/review-cases.py
```

脚本只打印[有限结果](harbor-review-readiness/case-results.json)的同口径观察，不启动软件服务／浏览器或发送。当前缺件分支不形成主张选材；其他分支明确是假设主体／用途变化或独立假秘密探针，不能回填实际facts。claim为条件性内部选材标记，外部／交存许可仍分别未授；旧范围与权利组合被拒，变化后材料invalidated。受限目标为不存在的合成路径，不是宿主全出口隔离证明；已列假值被掩码也不证明可发现全部真实秘密。

实际Word／PDF采用[研究示例独立成件](../../dyz-rendering/resources/research-documents.md#7-软件专业待审包成件)，绑定26份实际读取材料，[当前文件目标](harbor-review-readiness/file-bindings.json)另列。文稿22个唯一组件，20字段在同一表书签中；不是20个独立Word身份。真实资料、主体／人类贡献、规则路线及专业签核仍待补，旧1.2／1.3完整材料及本次首次失败／排版返工均保留。
