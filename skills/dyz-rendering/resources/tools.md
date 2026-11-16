# 预览生成、浏览器检查与证据契约

涉及“哪些版本读了多少页／段／图”的声明时，另接[读取范围生成与回验](../../dyz-workbench/resources/reading-scope.md)。它在既有装配器中核结构化记录、单篇／合计和实际Word投影，不把PDF渲染或机器提取改称目视；自由文字与真实阅读记录仍另审。

生成预览、实际screen检查或旁证重验前阅读；命令以包根运行。此处工具只支持指定子集，不提供正式print放行。 返回[技能入口](../SKILL.md)。

获准软件材料另走[软件专用成品链](../../dyz-software/resources/tools.md#软件成品链与集中采集)：固定清单与许可后将同版原PNG嵌入对应步骤，以A4生成源码/说明/字段DOCX，可选本地LibreOffice转换及pdftotext物理文字/边界检查。它不放宽下述通用装配器synthetic/research_example门禁，也不把机器回读升级为逐页目视、图片真实性或正式print放行。

## 适用范围与安装

文件装配器与Word回查另支持显式的[原创研究示例模式](research-documents.md)：逐文件保留合成、公开研究、混合原创及实际执行证据类别，生成research_example清单。它不扩大本文预览渲染器或其他业务CLI的synthetic边界，不认证真实权利；原标准全文、私人材料和组织模板不在该限定模式内。

对应 CORE-07、FIG-05、REVIEW-07 的确定性导出和渲染证据分支，关联 WP-02/04/05/06/07。不是CAD、Word排版、官方申请格式验证器、完整CommonMark实现或专业图文判断器。机器可读的证据一致性检查不等于独立签核，仍须原专业责任人及共享披露门禁。

运行需要 Python 3.11 标准库及同包 `tools/__init__.py`、`tools/core.py`、`tools/rendering.py`。工作目录为包含 tools 的包根。生成三业务合成演示还需要同包 `tools/patent.py`、`tools/software.py`、`tools/standards.py`。技能目录的 [demo.py](../demo.py) 和 [dom-check.js](../dom-check.js) 是可执行合成演示/浏览器观察资源；只复制 SKILL.md 不可运行。不依赖 `.references/` 或本机绝对路径，不安装第三方包。项目原创代码/合成素材沿用 PolyForm Noncommercial 1.0.0 和单独商业授权，不称OSI开源。

## 输入、支持子集与失败

- `render_preview(name: str, content: bytes, manifest_hash: str) -> dict`：name为相对逻辑文件名（`.svg/.md/.txt`），content是调用者明确提供的完整UTF-8字节（最多2,000,000字节），manifest_hash是当前固定包的64位小写SHA-256。函数不隐式读取路径、网络、字体、链接、图片或代码，不解析真实客户材料权限。宿主读取、索引及模型数据路径必须在输入前按CORE预检；默认验证只用合成资料。
- SVG采用元素/属性白名单：svg、g、defs、marker、path、rect、circle、ellipse、line、polyline、polygon、text、tspan、title、desc及明确几何/文字/描边属性。要求有限正尺寸viewBox。只允许指向图内已有ID的marker引用。拒绝脚本、事件、foreignObject、image/use、外部引用、任意CSS、style/metadata、嵌套SVG、变换、动画、DTD、实体、注释和处理指令；不删除危险节点后悄悄生成变形图。XML声明也属于当前明确不支持的子集，输入错误抛ContractError。
- Markdown支持ATX 1—6级标题、逐行段落、一级数字/短横线列表、单反引号行内代码、三反引号围栏代码、首尾有竖线且分隔行为至少三个短横线的矩形表格。实际生成h/p/li/code/table元素，不把整个Markdown放进pre冒充排版。围栏代码和纯文本按40个真实源行生成逻辑页及行号，不补行凑页。逻辑页不是打印/官方页数；长行允许折行。
- 行内支持反斜杠转义ASCII标点、带分号的有效HTML字符引用，以及两侧均为字母/数字的下划线（如`source_partial`）。转义和引用解码结果只作为文本输出，不重新解析成HTML、链接、代码或强调；行内代码中的实体/反斜杠保持原样。数值和具名引用若引入Cc/Cf控制字符则抛`hidden_control_character`，不能借实体绕过源检查。
- 强调、未转义链接/图片/原始HTML、引用、嵌套列表、缩进代码、复杂表格、非标点反斜杠转义、脚注、公式及其他未支持结构保留为可见转义文本并报告 `markdown_*_not_supported` 等问题，status=blocked。表格仍按竖线分列，不支持单元格内转义竖线等复杂表格结构；未闭合反引号也阻断。受支持的围栏代码和行内代码按字面保留内容。不可把blocked预览升级为合格候选。
- 不支持格式、无效UTF-8、隐藏控制字符、非法路径和无效SVG均抛 `tools.core.ContractError`。错误不复述原材料正文。SVG字形真实尺寸/遮挡/裁切仍需浏览器与肉眼；安全解析不等于可读或图示正确。
- 返回 `source_name/source_sha256/manifest_hash/renderer/renderer_version/rendered_artifact_hash/html/issues/status/rendering/professional_review`。`rendered_artifact_hash`专指UTF-8 HTML字节，不是截图哈希。HTML含源和包绑定，可编辑来源仍保持独立。`preview_created`且`rendering=not_executed`是生成状态，不是浏览器通过。
- `write_preview(root, relative, preview) -> Path` 只创建根内新`.html`文件，拒绝已有文件、越界/ADS/根外链接；不隐式建父目录。调用者保护授权根免于并发恶意改动。不得覆盖原件。

## 最小完整预览例

在包根运行以下Python。仅处理字符串构成的合成资料；临时目录结束后删除。

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.core import digest, sha256_bytes
from tools.rendering import render_preview, write_preview

source = '# 合成条件表\n\n| 参数 | 条件 |\n| --- | --- |\n| 10 ms ±1 ms | 维护模式除外 |\n'.encode('utf-8')
manifest = {'mode': 'synthetic', 'files': [{'name': 'sample.md', 'sha256': sha256_bytes(source)}]}
preview = render_preview('sample.md', source, digest(manifest))
assert preview['status'] == 'preview_created'
assert preview['rendering'] == 'not_executed'
with TemporaryDirectory() as folder:
    output = write_preview(folder, 'sample.html', preview)
    assert output.read_bytes() == preview['html'].encode('utf-8')
```

## 真实浏览器步骤

1. 冻结当前完整文件清单及实际源字节，确定manifest_hash。将预览写到独立获准输出目录，不把真实资料放进fixture。
2. 先遵循当前工作区的浏览器策略与既有授权，再用获准浏览器载入该新文件或隔离loopback服务。技能目录的demo只暴露本次生成的内存HTML，不暴露仓库、目录列表、任意文件或POST出口；启动后只用其实际打印的URL。
3. 等待字体/布局稳定，记录浏览器确切版本、实际视口与media。在获准浏览器求值环境执行 `dom-check.js` 的函数，保留返回的DOM边界结果；检查SVG字形和图形边界、节点内长标签、文本溢出及页行连续性。DOM范围不包括复杂重叠/专业语义或官方格式。
4. 实际截图并保存原始PNG字节；长页逐段或全页覆盖，检查所有内容、页边界和图形裁切。将观察范围记录到scope；用肉眼对照源文本确认条件、例外、容差及未知项未丢失。浏览器截图不是所述CLI软件成功运行的证据。可另存PDF，PDF仅是附加证据，screen审阅不能代替print审阅。
5. 创建每文件记录，证据中同时保留DOM和视觉检查、实际截图字节哈希及位置引用。当前截图接口只回附件而无原始字节时，`artifacts=[]`、`status=blocked`，标 `not_collected`；不能重新绘图、编造哈希或用DOM代替截图。
6. 在发送前从固定快照重新校验。源、包、渲染器版本、HTML、截图、视口或范围变化均需重审。不继承旧签核。检查结果交CORE门禁，本技能无发送接口，不自行解除原有MD/SVG阻断。

合成演示命令（新目录名；重复使用会拒绝覆盖）：

```powershell
python -c "import runpy; runpy.run_path('skills/dyz-rendering/demo.py', run_name='__main__')" --output outputs/rendering-demo --serve
```

演示包含FIG-01成功/失败路径及长中文标签、故意越界SVG、STD-05条件/例外/容差、SW-04 CLI说明、实际表格和85行源码的40/40/5逻辑页。服务只绑定127.0.0.1随机端口，Ctrl+C停止；不默认长期运行。去掉 `--serve` 仅生成。合成图中的几何失败是反向验收案例，不能全部标passed。

## 每文件证据契约与接入

共享CLI已提供固定候选预览双输出和外置旁证重验，完整可运行例见 [共享工作台](../../dyz-workbench/resources/tools.md)。它先检查授权、当前依赖和固定快照；CORE-07摘要不能复用为签核，REVIEW-07/journal须显式重验原旁证。接入不解除MD/SVG原rendering_not_checked或专业门禁。

`preview_scope(name, width=1280, height=900)`返回精确检查范围；务必以实际视口填值，不照抄默认。所有必要checks为 `content_preservation/document_overflow/svg_bounds/text_overflow/pagination/visual_crop`，media目前仅screen。不适用的SVG/分页检查在notes中说明，无需伪造SVG或页。

```python
from tools.rendering import preview_scope, validate_rendering_evidence
from tools.core import sha256_bytes

# preview/source/package_hash来自上一步；png_bytes必须由实际截图接口返回，绝不可用占位字节。
# dom_observation/visual_observation必须来自已完成的当前版本观察；不从preview_created推导。
def check_observed_preview(preview, source, package_hash, png_bytes,
                           dom_observation, visual_observation, checked_at, now,
                           browser_version, actual_width, actual_height):
    scope = preview_scope(preview['source_name'], width=actual_width, height=actual_height)
    record = {
        'source_name': preview['source_name'],
        'source_sha256': preview['source_sha256'],
        'manifest_hash': package_hash,
        'renderer': preview['renderer'],
        'renderer_version': preview['renderer_version'],
        'rendered_artifact_hash': preview['rendered_artifact_hash'],
        'evidence': {
            'executed': True,
            'browser': {'name': 'Chromium', 'version': browser_version},
            'artifacts': [{'id': 'screen-full', 'kind': 'screenshot_png', 'sha256': sha256_bytes(png_bytes)}],
            'dom': {**dom_observation, 'scope': scope},
            'visual': {**visual_observation, 'scope': scope}
        },
        'status': 'passed' if dom_observation['status'] == visual_observation['status'] == 'passed' else 'failed',
        'reviewer': {'id': 'observing-agent', 'kind': 'agent'},
        'checked_at': checked_at,
        'scope': scope
    }
    validation = validate_rendering_evidence(
        record, name=preview['source_name'], content=source, manifest_hash=package_hash,
        artifact=preview['html'].encode('utf-8'), evidence_artifacts={'screen-full': png_bytes},
        required_scope=scope, now=now)
    return record, validation
```

`validate_rendering_evidence(record, *, name, content, manifest_hash, artifact, evidence_artifacts, required_scope, now)`没有文件读取。`evidence_artifacts`是ID到实际字节映射，不是路径；记录里的路径仅供外部保管方定位，校验器不读取。Screenshot为PNG，附加PDF的kind为print_pdf。所有证据必须有且只有对应清单项。观察对象须含`status=passed/issues=[]/scope/notes`；缺执行、浏览器版本、审阅者、带时区时间、缺截图、旧源/旧包、过期renderer、范围错配或失败观察均blocked。时间不得在now之后；当前不推导通用审核有效期，权限和法律时限归CORE/原业务。

渲染器当前版本为`1.1`。SEARCH-06普通工作稿中的查询方括号、来源字面转义与机器状态标识符可以生成安全预览；仍需根据preview.issues处理实际未支持的内容。`1.0`记录不能迁移版本号后继续复用，应从原固定源和包重新生成HTML并重新收集DOM、视觉和截图旁证；验证器返回`renderer_version_mismatch`时保持blocked。本轮只验证本地生成/CLI交接，不代表浏览器已经执行。

结果只有 `consistent` 或 `blocked`。consistent表示所给版本、字节和观察记录一致，**不证明PNG内容确由浏览器生成、记录真实、审阅者身份有权或专业通过**；文件头检查及哈希不能认证事实。即使kind=human也不认证其身份。上层必须验证证据保管和必要专业签核。默认门禁仍可独立拒绝未支持的格式，不得仅凭consistent全局删除渲染/隐藏信息阻断。

## 历史验证与真实限制

以下保留既有验证时点，不代表当前机器仍缺浏览器，也不代表r2已重新运行。环境可用性须按当次任务检查；旧截图缺口仍需对应版本的真实证据。

2026-10-31，Windows / PowerShell，Python 3.11.15。运行：

```powershell
python -m unittest evals.test_rendering -v
python -m py_compile tools/rendering.py evals/test_rendering.py skills/dyz-rendering/demo.py
```

原23项单测覆盖最小同包独立导入（不带业务模块）、活动SVG、文本转义、子集拒绝、源码页/行、路径/覆盖、无隐式I/O、版本变化、缺执行/证据、范围和观察失败；单测中的PNG头明确是合成契约替身，不计真实渲染证据。

实际内置浏览器 Chromium 150.0.7871.250、Windows、1280×800 已载入七份合成预览并观察：普通流程、标准段落、CLI说明、表格及85行源码DOM正常；故意裁切图被检出；当时FIG-01长中文原图发现两行超节点；随后Lin已在生成层按显示列宽换行和增高修复，并对新产物完成实际浏览器DOM/视觉复验，主代理35项独立专利回归通过。原长中文、混排、英文XML和360字长图均无该越界，故意裁切负例仍检出。标准条件/例外/容差、CLI失败路径和未执行声明、源码40/41与80/81页界均肉眼可读。实际截图只作为会话图像附件可见，当前接口未返回可保存原始bytes/路径；因此**截图哈希证据未收集，整体验证仍blocked**，不将本节当作可放行的per-file记录。两个MCP浏览器因指定位置缺少Chrome启动失败；未安装、未改配置。新产物源/HTML/DOM观察已保存，但截图仍无原始bytes/持久化路径，完整记录保持blocked/not_collected；源/HTML/DOM或PNG替身不能替代真实截图。真实观察及修复重验由开发仓库docs/implementation-progress.md唯一台账维护（不纳入本地包），本技能不是第二套进度台账；本次仅同步文字，未再次执行浏览器复验。

2026-11-01续建：28项渲染测试通过；渲染集成与专利联合68项通过，含真实CLI固定快照交接、生成HTML可见文本检查、旧1.0证据拒绝、缺截图和缺签核保持阻断。MCP Chrome本轮探测仍因缺可执行程序失败，没有安装、改配置或新启服务；没有新的浏览器截图或视觉通过记录。上述是本地确定性验证，完整进度仍以唯一台账为准。

未验证：官方Word/PDF模板、打印页高/物理页数、所有字体/设备、CAD/化学图、多法域正式格式、真实专业审阅/身份、宿主出口隔离、正式提交或真实发送。真实材料、许可、收费/账户和专业资源继续按原项目约束处理。


## 合成文稿的DOCX/PDF装配

`python -m tools.documents` 按冻结源文件及一基行区间装配内部文稿，关联CORE-07。默认只用Python 3.11标准库生成DOCX；传入`--pdf-tool`才调用操作者明确选择的本机LibreOffice，不安装依赖、不使用云端转换或日常办公profile。现有HTML预览与证据校验接口保持独立。

```powershell
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output outputs/patent-document
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output outputs/patent-document --verify
# 可选PDF转换；路径必须指向本机实际安装的soffice，不能照抄不存在的路径。
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output outputs/patent-document-pdf --pdf-tool "C:/Program Files/LibreOffice/program/soffice.com"
```

父目录须已存在，输出目录须为新目录。失败会保留已产生的文件供检查；没有最终manifest不能按成功包使用，不能直接覆盖或盲目重试。PDF转换最长等待60秒，失败/超时不能记成导出通过。

输入包含`document_id`、`version`、`business`（patent/software/standard）、`sensitivity=synthetic`、sources及blocks。sources逐项指定id、相对路径和实际SHA-256；blocks指定稳定id、source_id、start_line/end_line、kind及audience。kind支持paragraph、heading1、heading2、code及下节所述矩形table；audience必须明确为body或internal。标题仅去除行首Markdown标题标记，其他文字、空格、换行、单位及否定词原样保留。复杂合并表格、公式、自动编号、脚注和既有审阅Word稿当前不属于这个装配入口的支持范围，不能伪称已保留其结构。

可选figures逐项给出id、svg/png的路径与hash，以及`core.digest({"svg": svg_hash, "png": png_hash})`得到的render_binding。SVG须通过现有被动内容检查；PNG必须来自对应图源的实际渲染。该绑定只证明指定字节对，不能代替对箭头、文字和分支的观察；本示例PNG已有本轮实际headless浏览器渲染证据，其他图不能借用它。

可选`dependencies`逐项指定相对`path`与`sha256`，用于绑定事实表、源码行映射及PNG等不进入正文的证据；不将二进制附件作为文字读取或嵌入文稿。任一依赖缺失或改变，生成与回读均拒绝。港湾两份输入均绑定同版事实表、映射及两份截图；改变事实并不能自动证明新版软件或截图一致，仍须重建并实际核对受影响材料。

产物分为`body/document.docx`、`body/source.txt`、可编辑SVG，以及`internal/notes.txt`和`internal/source-map.json`；可选PDF也放body。正文中的稳定id写成Word书签，版本/源行及完整文件hash在内部映射保留。工具不会把完整原件、内部块、批注或外链自动加入正文；但调用者须正确分类blocks，工具不识别错误标成body的秘密。整个根目录含内部资料，不能把根目录默认当作可外发包。

当前documents生成版本为`1.5`，标准v2部件和排版字节已升级；旧`1.3`／`1.4`包保留原冻结工具复验，或用新目录重建，不只改清单版本。默认及标准v1的低层make_docx字节兼容；生成版本不是专业或页面认证。manifest绑定实际输入、每份产物字节和工具版本。`--verify`回读已有包：源版本、稳定块、正文、内部说明、图和目录成员均核对，多余附件或改后未重建会拒绝；只改manifest中的hash不能使改写正文通过。DOCX按本生成器的固定部件逐项比对，拒绝新增/修改的批注、修订、隐藏文字、关系、嵌入内容和图片；这不是任意Word稿的清洗器。PDF只记录转换成功及字节，仍须实际回读、逐页截图及观察。源/参数/图发生变化时新建版本和输出目录，旧观察记录不自动继承。

`--verify`的输入配方与输出目录须成对，`case_documents`的`input/output/verify:true`遵守同一约定：

| 要核的包 | 输入配方 | 输出目录 |
| --- | --- | --- |
| 旧版包是否仍与其生成依据一致 | 生成旧包的配方 | 该旧包目录 |
| 当前包是否与当前生成依据一致 | 生成当前包的配方 | 该当前包目录 |

不能把旧配方交给当前目录来比较版本；不同规范化输入绑定会报`document_input_binding_changed`，不要自动替换实参、重写manifest或重建旧包来消除此拒绝。新旧内容差异使用下节的实际DOCX回查：当前Word作为`input`、旧Word作为`baseline`。只确认旧文件未变时也可逐件核其已留存的精确hash。

续接时，对每个包一起保存生成配方的路径与精确文件hash、manifest的规范化`input_sha256`、输出目录、manifest／DOCX的hash及实际校验结果；规范化输入摘要与配方文件字节hash分别记。新版另存一组，旧组保留。配方核验、Word差异、当前页面观察和专业审阅各有范围，不能互相替代。

生成清单的needs_review、未视觉／专业审阅、未执行外部动作及确定性checks须与本工具实际结果一致；直接改成passed／已执行等会被回读拒绝。后续真实审阅、签核与行动另存绑定该版本的记录，不通过改写生成清单冒充完成。

PDF中的条件箭头等符号须结合页面位置回读并对照实际PNG。抽取器可能保留字符却改变其读序；保留该差异，用明确记录的版面读取方式复核，不能删掉符号或改变条件方向来迁就抽取结果。某一读取器核对成功不代表所有阅读器均已验证。

当前版式为A4正文及可选A3内部审阅图页，不声称符合官方申请、登记或标准格式。`needs_review`、专业审阅、打印布局、物理打印和正式提交分别记账。字体及LibreOffice版本影响分页；不因生成成功或字节相同宣称专业正确。实际验证与失败保全只见施工台账，本资源不维护第二套成绩。

### 编辑后的文件另行回查

`python -X utf8 -m tools.document_review --synthetic --root . --input outputs/edited.docx --baseline outputs/baseline.docx --output outputs/readback.json`只读两份实际DOCX，按唯一完整书签名称比对文字及区间覆盖，列原生表格位置、修订/域/隐藏指示和未解释部件。父目录须存在、报告须为新文件；不覆盖原稿、不接受修订、不访问外链或执行Office内容。有限子集、报告字段、资源上限和返工步骤见[编辑稿回查](docx-readback.md)。这不放宽上面的生成器`--verify`，不代表任意Word文件、专业内容或视觉已通过。

### 可选事实关系与实际正文绑定

使用[专利事实／支持复核](../../dyz-patent/resources/fact-and-support-review.md)时，可在spec增加`fidelity={"payload":关系载荷,"blocks":绑定表}`。绑定表必须恰好覆盖每个body块及每个figure id，值为该实际文本／完整SVG在候选文档中的citation；内部说明不作为正文依据。程序先检查有限关系及实际输出文字，不通过时在创建输出目录前拒绝。没有提供此字段的旧调用仍可运行，但不能声称已执行关系复核。装配器独立检查实际DOCX，`internal/quality-review.json`与manifest质量摘要绑定实物；轻量检查不替代此处的fidelity。`delivery_stage=draft`保留带问题内部稿，`final`残留标记时拒绝；旧resolution不能豁免成件残留，措辞只报review。主稿、内部报告、视觉与专业审阅各自留证，不合成笼统通过。

完整合成样例已包含候选正文、内部参数分析及原始内联材料，运行：

```powershell
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/fidelity-document-example.json --output outputs/fidelity-document
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/fidelity-document-example.json --output outputs/fidelity-document --verify
```

父目录须已存在且目标须不存在。新增`internal/fidelity-review.json`保存完整检查和内部理由，manifest只登记范围与hash等摘要；这些不混入body。回读会按当前输入重新核关系、每个正文块／SVG与完整报告，改manifest的hash不能掩盖报告被替换。该机制不自动理解自然语言、不核参数分析质量、PNG与SVG视觉一致性或专业／正式格式，仍需对应观察与审阅。


### 专利最终正文的强制门禁

通用documents装配器对business=patent且delivery_stage=final（或显式提供final_text_sources）的实际body块另执行[最终正文门禁](../../dyz-patent/resources/tools.md#最终正文验收门禁)，失败在创建输出目录之前抛final_text_gate_blocked。不能改走通用Word装配器绕过专利交付检查。输入来源不足或句法不在受支持子集也阻断；普通draft保留内部用途，软件与标准沿各自原契约。成功报告存internal/final-text-gate.json并在verify时重算，文本、原文、报告或绑定变化不继承旧结果。该报告不替代fidelity、实际DOCX质量、视觉或专业审阅。

### 同版软件与标准文件样本（输入沿用1.1；装配1.2）

完整包内提供下列显式输入，沿用上面的 `python -m tools.documents --synthetic --root . --input ... --output 新目录`；可选 `--pdf-tool` 仅调用指定的已安装LibreOffice，不安装依赖。

| 用途 | 输入文件（相对完整包根） | 范围 |
| --- | --- | --- |
| 港湾v1.2源码 | `skills/dyz-software/resources/harbor-delivery-v1.2/source-input.json` | 5份真实合成示范源文件，255物理行，逐行前缀及source-lines.json；原源码和选材源都绑定哈希 |
| 港湾v1.2说明 | `skills/dyz-software/resources/harbor-delivery-v1.2/manual-input.json` | 实际GUI、CLI、API说明；同目录facts.json及两份实际PNG另存，不声称截图已嵌入DOCX |
| 溪桥规范正文 | `skills/dyz-standards/resources/river-delivery/standard-input.json` | N案完整规范正文及两附录，RIV_01至RIV_08为稳定Word书签 |
| 溪桥意见、说明、验证计划 | 同目录`comments-input.json`、`explanation-input.json`、`verification-input.json` | 分文件、同版原始来源绑定；comment-bindings.json保存意见到条款书签及规范DOCX哈希 |

1.1新增原生矩形管道表（1—6列）：表头重复、行不拆分，逐单元格回读；拒绝列数不齐、转义管道及未支持合并结构。条款编号来自原稿，不自动重编号；书签不是自动交叉引用域。超高行、复杂公式、脚注、合并表或编辑后任意Word文件仍需另行处理，不能据样本宣称完整GB/T格式支持。

1.2将整表书签的起止移到首尾单元格段落内，避免已观察到的LibreOffice将表外包围书签缩成空范围。旧1.1文件和检查保留历史，不改hash或版本冒充新包；新包按当前源重建并重新核对。该修复不保证所有办公软件均保留书签；编辑稿须实际检查书签范围和未覆盖文字，不能只查名称还在。

软件说明[原稿](../../dyz-software/resources/harbor-delivery-v1.2/manual.md)包括GUI启动命令；实际源码在[gui.py](../../dyz-software/resources/harbor-demo/v1.2/gui.py)。v1.2是本次新增原创合成GUI版本，历史v1.0/v1.1事实不改。服务器只绑定127.0.0.1，不提供用户认证，退出后关闭本地服务。源码PDF实际分页及截图只证明对应运行版本，不是登记交存或主体/权利证明。源码变化须重建来源清单、说明、受影响截图与文档，旧检查不继承。

所有清单仍为needs_review。标准意见为建议而非有权决定；软件facts.json中的主体、日期、发表及登记事实保持未知。可编辑文件、实际PDF、来源行、截图、隐藏部件检查与专业审核分别记录。

标准意见输入另以dependencies绑定当前comment-bindings.json和standard-input.json；映射保存实际1.2规范DOCX哈希、输入文件哈希及规范manifest使用的规范化输入摘要。正文内容版本N_1.0_r1与装配器版本1.2分别记录。任一映射或规范输入变化都须更新依赖并重建意见文件，不能沿用旧导出检查；映射本身不批准意见或证明实际组织决定。
