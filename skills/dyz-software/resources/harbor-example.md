# 港湾记录整理器：三案完整开发示范

本示范服务CN软件版权材料内部准备，关联SW-01/07/02/03/04/05；正式程序另接SW-06。先读[核心材料方法](cn-core-method.md)和[CN规则证据](../../../references/jurisdictions/cn-software-evidence-20261101.md)，返回[技能入口](../SKILL.md)。源码为本项目实际原创合成资产，沿用根目录PolyForm Noncommercial 1.0.0及单独商业授权。不是MIT或OSI开源许可；以下虚构实验组、合同、人物角色和权限不改变实际资产许可，也不是真实权属证明。

源码资源：[v1.0 core](harbor-demo/v1.0/core.py)、[v1.0 CLI](harbor-demo/v1.0/cli.py)、[v1.0 API](harbor-demo/v1.0/api.py)、[v1.1 core](harbor-demo/v1.1/core.py)、[v1.1 CLI](harbor-demo/v1.1/cli.py)、[v1.1 API](harbor-demo/v1.1/api.py)。下文文件路径均相对于本资源的harbor-demo目录。

N、C、V是相互替代的三套模拟事实，不能跨案继承权利、用途或秘密分类。特别是C案，整份教学示范、N/V正文和全体源码均不是C案拟外发包；其中的其他场景不能用于恢复C案被省略的配置值。C案的可交范围在C3交接中单独列明。现实中的源文件没有真实秘密或凭证，但C案演练仍按其给定限制处理。

开发题目、30项预设检查及字节清单在仓库evals/workflows/deepening-software-d2-{cases,rubric,inputs}.json；不随本资源分发。题目和评分均对作者可见，以下是作者开发作答，不是隐藏题、独立验收或专业签核。正文版本统一记为D2-SW-N/C/V-draft1。规则证据为2026-11-01研究版，专业审阅未执行；中国版权保护中心在线指南获取失败，正式页式细节、当前表式和实际接受仍待核。

源码清单于2026-11-01冻结。本作者读取实际六文件字节并复算SHA-256、字节及UTF-8解码后splitlines()行数，与输入清单一致。物理原行含注释和空行，文件均为UTF-8无BOM、LF及末尾LF；这些数不等于法定源程序量、有效代码量或原创性。以下原行映射已由主代理另行执行现有工具并实际导出所选文本和逐行map，开发证据见文末；内部展示行/逻辑页与正式交存分页分别记账，后者未生成。本作者未运行软件，正文示例为静态推导；已读取的夹具作者运行及主代理工具记录单独引用，不说成自己执行。

## D2-SW-N：同版CLI/API首次材料

### N0 材料、范围与理由

M-N01说明“港湾记录整理器v1.0”三组件同版内部发布，CLI和WSGI API直接使用core，没有独立商品版本、单独许可或独立交付，也没有GUI、数据库、联网客户端或部署脚本。M-N02是模拟职务约定摘要：内部工程角色在任务内负责三组件的设计、字段和错误分流，AI辅助起草后逐行选择与改写；约定对应表达归实验组，只有摘要、无真实签章、身份或贡献比例。M-N03允许三文件本地读取、统计、编辑、生成完整源码候选并经本机outputs交技术/版权负责人，限本轮内部准备；交存、公开、外部律师/云处理均未授权。M-N04给定仅引用Python标准库且无另标秘密。M-N05名称/版本一致，完成/发表日未知，源量待统计。

建议将core、CLI、API作为一个v1.0关联软件工作范围，同时逐组件审计。理由是共同功能、共同核心和同版交付，不是“有两个入口所以两个软件”。拆成两个登记对象缺独立版本/交付依据，会使共享core的表达和材料重复；若之后发现独立许可或交付事实，再由技术及版权人员重看拆合。实际表达候选是本版校验/转换源码、各入口错误组织和说明文字，不主张对“JSON转CSV”功能、算法思想、字段名或所有同功能实现排他。

| 组件 | 本版表达位置与拟处理 | 权利依据及剩余问题 | 当前动作权限 |
| --- | --- | --- | --- |
| core | S10-CORE 16—63行的解码、校验和CSV组织列入候选 | M-N02明确纳入任务/约定；AI辅助后的人工选择改写有摘要，真实任务/签章/创作记录待核 | M-N03内部处理及候选选材；不含正式交存/公开 |
| CLI | S10-CLI 10—46行的参数、I/O及退出分流列入候选 | 同一模拟约定覆盖CLI；不以员工称谓或Git作者单独确认现实权利 | 同上 |
| API | S10-API 10—54行的WSGI请求和响应组织列入候选 | 同一模拟约定覆盖API；与CLI共享core，不重复计算core表达 | 同上 |
| 标准库与AI辅助 | csv/io/json/argparse/pathlib/sys为依赖名称，不纳入三文件自有源码主张；AI参与方式如上，不虚构比例或作者 | M-N04及实际import；标准库源文件未读取/选入；实际示例代码许可保持项目NC | 依赖使用不自动等于依赖源码可交存或公开 |

M-N04足以在本模拟案选择不遮盖的内部候选，但不能写“真实产品已无秘密”。完成、首次发表、登记事件均没有给定事实，保持未知，不用文件时间、冻结日或本次作者操作填充。

### N1 实际源文件与选材审计

| ID/路径 | SHA-256 | 字节 | 物理原行 | 全量原行→选材行 |
| --- | --- | ---: | ---: | --- |
| S10-CORE / v1.0/core.py | 2ad5c9d389a7abbdb105c545d4ab2f72fdb4167aa728dbdb64dfb5df02f7bbe1 | 2198 | 63 | 1—63→1—63 |
| S10-CLI / v1.0/cli.py | 8929d151347f22ea23a3ace676e60ad0242da028577305198b1a36282883d86d | 1457 | 46 | 1—46→64—109 |
| S10-API / v1.0/api.py | f954b7b976992b45d601d8d22215c0a2308ee4b7f9f9fdcfc0734395e5a2aad7 | 2491 | 54 | 1—54→110—163 |

读取清单共3文件、6146字节、163物理原行。按M-N04固定core→CLI→API的全区间并集选取，选中去重原行163；没有重复core，没有拼入标准库、文档或生成物，也未补行。每段由上表完整文件哈希和原行定位。主代理实际工具记录为163展示行、5个内部逻辑页（40行/100列参数），逐行选材与原字节相等；所选文本及每行原位置map已经导出，包含跨文件接缝。正式交存分页及其页级复核未生成。原文件末尾LF仍属源字节，累计原行只表达顺序，不以分隔标题增加源量；串接材料不是可执行的合并程序。

本案推荐一般交存的全量材料准备路线：软件极短、当前模拟三组件内部候选权限齐备、没有另标秘密，完整源程序和完整本使用/设计说明先保全。规则证据C5及登记办法第10条分别判断程序、文档的完整母本；不足60页交全部，不能把本163物理行说成已满足官方页式或凑成60页。通常程序每页不少于50行、文档每页不少于30行及其特定情况/末页细节须按实际分页与机构指引核，当前不输出官方页数。第12条例外没有本案必要性，且短材料如何采用其固定页数组合未核，不为“更保密”强行选；第13条封存也未提出或获准。内部选材许可不等于正式交存批准。

### N2 可编辑使用与设计正文

<!-- BEGIN D2-SW-N WORK PRODUCT -->
# 港湾记录整理器v1.0使用与设计说明

稿件标识：D2-SW-N-draft1。用途：内部软件版权材料准备。本文依据S10-CORE、S10-CLI、S10-API的冻结源码及M-N01—05模拟材料静态整理；示例是源码推导结果，本作者未实跑。完成日期、首次发表日期与真实权利人尚未确认。

## 1. 软件用途与运行准备

软件将UTF-8 JSON记录数组转换为CSV文本，提供命令行入口和供程序内部调用的WSGI application。两入口共用core的解码、校验与CSV生成逻辑。软件没有GUI、数据库、联网客户端、内置服务器或部署脚本；没有用户登录、鉴权或持久化API服务。本说明不声称性能、并发或公网部署能力。

使用Python 3.11环境准备本示例；冻结材料的环境记录为Windows、Python 3.11.15，不等于其他系统已经验证。core.py、cli.py、api.py须来自同一v1.0目录并保持相邻。三文件仅使用Python标准库，无需安装第三方包。先将工作目录切换到v1.0，输入文件和目标目录须由操作者有权读取/写入；目标目录应已存在，输出文件必须尚不存在。不将v1.1文件混入本目录。

可先查看命令帮助和版本：

```text
python cli.py --help
python cli.py --version
```

源码中的版本输出为1.0。命令入口是cli.py，不是名为harbor的已安装命令；本材料未提供安装器或系统服务。

## 2. 输入与输出

输入须为UTF-8编码的JSON数组，最多1000条；空数组合法。数组每项须为对象，包含id、label、value三个字段。id和label须为字符串，去掉首尾空白后不能为空，且能编码为UTF-8；程序检查非空但保留原字符串，不执行trim或规范化。value须为非负整数，true/false和浮点数不合法。v1.0允许重复id，忽略额外字段；它不会去重、按id排序或聚合。

CSV列固定为id,label,value，记录维持输入顺序，字符采用UTF-8，行结束使用LF。引号、逗号及字段内换行由标准库csv处理，不手工删字符。空数组只输出表头。CSV是数据导出，程序没有对电子表格公式式文本进行清洗；使用目标应用打开前应按实际用途审查。

## 3. CLI正常操作

以UTF-8保存records.json，内容如下：

```json
[
  {"id":"A1","label":"north","value":3},
  {"id":"A2","label":"south","value":0}
]
```

确保result.csv不存在，然后执行：

```text
python cli.py records.json result.csv
```

按源码，成功退出码为0，标准输出为wrote 2 records；新建result.csv的完整内容如下，末行后也有LF：

```csv
id,label,value
A1,north,3
A2,south,0
```

CLI先读取全部输入、完成解码与所有记录校验，并在内存生成CSV，然后才以独占新建方式打开目标。它不会覆盖已有文件。若希望再次转换，应使用新的输出路径，或在操作者另行确认后处理已有结果；程序本身没有覆盖开关。

## 4. CLI错误与恢复

| 条件 | 退出码/诊断 | 输出文件及恢复 |
| --- | --- | --- |
| 成功 | 0；stdout为wrote N records | 生成新CSV |
| JSON/UTF-8或记录内容不合法 | 2；stderr为固定错误类别 | 校验先于创建输出，不生成新目标；修正输入后换用不存在的目标再运行 |
| 参数缺失或不支持的参数 | argparse报告并退出2 | 未进入输入/输出处理；按--help修正 |
| 目标已存在且输入已通过校验 | 3；output_exists | 原有目标保全；改用新路径 |
| 读取失败 | 4；input_io_error | 未创建输出；检查输入路径和读取权限 |
| 输出打开/写入I/O失败 | 4；output_io_error | 写入开始后可能留部分新文件；检查目标与磁盘并单独核查残留，不承诺原子写入 |

例如将输入改成[{"id":"A1","label":"north","value":-1}]，固定错误为invalid_value，退出2且不创建新目标。true同样非法，0合法。缺label得到missing_field；id或label只含空白分别得到invalid_id/invalid_label；不能编码的字符串得到invalid_text_encoding。非法JSON得到invalid_json。若已有目标但输入本身非法，先发生输入错误2，不能认为所有已存在目标都必然先返回3。

重复id的两个合法对象在v1.0均按顺序输出。含额外字段note的对象仍只输出三列；不支持strict参数。输入为[]时正常输出id,label,value表头，记录数为0。

## 5. WSGI接口与内部调用

API入口为api.application(environ, start_response)。仅接受POST和路径/convert，查询字符串必须为空。内容类型取分号前部分，去空白并转小写后须为application/json，因此application/json; charset=utf-8可匹配；正文仍由核心按UTF-8解码。

CONTENT_LENGTH须可转换为正整数，且不超过65536字节；这是本v1.0实现的正文容量条件。wsgi.input须存在，其read(length)须返回长度正好相等的bytes。实现只读取声明长度，不额外探测流末尾，不能把它当完整HTTP协议检查器。合法正文是第2节所述JSON数组。

成功返回200 OK，Content-Type为text/csv; charset=utf-8，Content-Length为UTF-8响应字节数，响应主体是CSV。错误返回JSON对象，只有error字段和固定错误类别，不回显输入记录；错误响应Content-Type为application/json。

| 条件 | 状态 | error及说明 |
| --- | --- | --- |
| 路径不是/convert | 404 Not Found | not_found |
| 路径正确但方法不是POST | 405 Method Not Allowed | method_not_allowed，并含Allow: POST |
| 非空查询字符串 | 400 Bad Request | invalid_query |
| 内容类型不匹配 | 415 Unsupported Media Type | invalid_content_type |
| 长度缺失、不可解析或不为正 | 400 Bad Request | invalid_length |
| 声明正文超容量 | 413 Payload Too Large | payload_too_large |
| 缺流、读取错误、返回类型或长度不符 | 400 Bad Request | missing_body、body_read_error或body_length_mismatch |
| JSON/编码或数据字段校验错误 | 400 Bad Request | invalid_json或核心固定类别，例如invalid_value |

校验按表中路径、方法、query、类型、长度、流、内容的顺序发生；同一请求有多项错误时返回首先到达的分支。以下Python例在三文件所在目录中执行即可在内存调用接口，不开启端口、不启动服务器：

```python
from io import BytesIO
from api import application

payload = b'[{"id":"A1","label":"north","value":3}]'
captured = {}

def start_response(status, headers):
    captured["status"] = status
    captured["headers"] = dict(headers)

environ = {
    "REQUEST_METHOD": "POST",
    "PATH_INFO": "/convert",
    "QUERY_STRING": "",
    "CONTENT_TYPE": "application/json",
    "CONTENT_LENGTH": str(len(payload)),
    "wsgi.input": BytesIO(payload),
}
body = b"".join(application(environ, start_response))
print(captured["status"])
print(body.decode("utf-8"), end="")
```

上述静态例的预期输出为200 OK，随后为CSV表头和A1,north,3。将payload的value改成-1并同步CONTENT_LENGTH，预期为400 Bad Request与{"error":"invalid_value"}。当前材料不提供真实HTTP地址、TLS或鉴权配置；需要服务部署时须另有适配与安全设计，不能把此内部调用例当已部署服务。

## 6. 设计与已知限制

core.decode_payload把原始bytes转换为JSON对象，validate_records按输入顺序检验并只保留三字段，render_csv生成完整CSV字符串，convert返回字符串及记录数。CLI管理文件读取、独占新建和0/2/3/4退出状态；API管理WSGI请求约束、响应状态及长度头，两者没有另存一套转换规则。

输入和CSV均在内存处理；CLI没有API的正文容量检查，仅在解码后的记录数量上限处限制。API无服务器、鉴权和持久化，异常捕获只覆盖源码所列数据/I/O分支，不保证处理所有恶意WSGI对象或进程资源故障。CLI输出不是原子替换事务。软件无GUI，本文命令、代码和响应样例均不是运行截图。

## 7. 正文来源定位

| 本文内容 | 冻结源位置 |
| --- | --- |
| 字段、数量、编码与v1.0数据行为 | S10-CORE 7—48行 |
| CSV、顺序和空数组结果 | S10-CORE 51—63行 |
| CLI参数、打开顺序与退出码 | S10-CLI 10—42行 |
| API限制、错误与CSV响应 | S10-API 7—54行 |
| 同版发布、无GUI及材料用途 | M-N01、M-N03 |

本正文的内部审阅对象是上列冻结源码和D2-SW-N-draft1。正式交存页式、版权判断和向任何外部对象发送均未完成。
<!-- END D2-SW-N WORK PRODUCT -->

### N3 字段核对、问题与行动交接

| 核对项 | M-N05原值/本稿候选 | 依据与状态 |
| --- | --- | --- |
| 名称/版本 | 港湾记录整理器/v1.0；保留 | M-N01、三源文件首行及core第7行一致 |
| 组件/开发方式 | core/CLI/API同版；模拟职务开发候选 | M-N02与源码调用关系一致；真实权属由版权负责人核证 |
| 源量 | 三文件6146字节、163物理原行 | 已实际复算；填为内部清单口径，不直接声称官方表式字段可用 |
| 选材量 | 163去重原行，core→CLI→API | N1映射和真实导出；163展示行/5内部逻辑页，正式页数未生成 |
| 环境 | Python 3.11标准库；材料环境Windows/Python 3.11.15 | 源码依赖与冻结记录；全平台兼容/运行结果不从中推定 |
| 输入/输出 | JSON数组三字段→UTF-8 CSV三列；CLI/API行为如N2 | N2逐项源码位置可追溯 |
| 完成/首次发表/登记日 | unknown/unknown/无登记事件 | 没有证据，不填冻结日或Git日 |

内部问题单N-Q1由版权负责人补真实任务、职务约定和人工贡献记录后审权利；N-Q2由材料负责人针对拟交存用途核秘密及完整页式，当前只是无另标秘密的模拟事实；N-Q3由技术负责人核正文行为和本次拟版本；N-Q4由权限负责人取得真实具体包/对象/用途/渠道/有权批准后恢复对应外发。问题不阻止当前内部正文交付。

已读取夹具作者记录v1.0-cli-normal与v1.0-api-normal：同一包含“码头, A”和“乙”的两记录合成输入，前者退出0、stdout为wrote 2 records，后者200 OK，CSV实际为41个UTF-8字节，逗号字段带引号；它们不同于N2的英文静态例，不假称N2示例已运行。负数和bool检查退出2，已有目标检查退出3且原文本保留；重复ID及默认额外字段检查成功。命令/环境及限制见文末证据便笺。主代理N工具状态needs_review、deposit负例选中0行，说明本地映射已执行而正式用途未获准，不是专业或登记结果。

| 成果/拟动作 | 具体包、对象、用途、渠道 | 角色/当前状态及恢复条件 |
| --- | --- | --- |
| 正文候选交内部审阅 | N2完整说明D2-SW-N-draft1；对象为模拟实验组技术与版权负责人；用途为内部登记准备；本机outputs目录 | M-N03允许，当前已在本资源形成可编辑稿；实际向真人投递未执行 |
| 内部审计交接 | N0/N1/N3及三源文件哈希/映射；同两类角色、同用途渠道；秘密复核单不默认并入未来外发正文 | 材料负责人核字节/秘密、版权负责人核权利/规则；均待相应审阅 |
| 拟正式交存 | 未来固定的v1.0程序与文档鉴别材料、表式及所需证明；对象拟登记机构，具体系统账号/渠道未确定 | 需权利/材料专业核定、真实有权主体批准与发送前复核；未批准、未提交、无回执 |
| 外部律师审阅/公开/云处理 | 各用途均没有具体获准包、对象或渠道；不能沿用内部权限 | 权限负责人逐用途确认后另议；当前未授权、未执行 |

本案未执行SW-06程序；没有真实通知、补正或期限。正文、内部审计和行动条件是三个交接对象，不因共同存放在教学资源中而成为同一个可外发包。

## D2-SW-C：权利、版本与模拟秘密冲突

### C0 当前事实与选择

本案仅采用S10三文件。M-C01仍是v1.0共同发布的core/CLI/API，API依赖core但在本案假设为海堤工作室受托编写，无独立API商品版。M-C02完整模拟约定写明受托方保留API表达权利；实验组只有本机内部集成、排错和材料准备读取处理权，没有API交存、外部分发、公开或外部云处理权。core/CLI有同M-N02文字强度的职务约定，但不继承N案的API权限。M-C03经理以费用付清主张全部源码归实验组且均可交存，没有附转让、合同变更或提交授权。

采用M-C02的具体用途约定制约当前选材，保留M-C03冲突，不能以付款推翻约定。建议core+CLI作为当前内部候选选材范围，API仍记入真实产品结构和内部行为说明，同时列为委托表达争议/不得当前交存组件。这个109行子集不是原三组件完整软件的一般交存齐备包，也不是已决定独立登记的“CLI版”。

| 问题 | 保留的相反材料与候选处置 | 负责人/恢复条件 |
| --- | --- | --- |
| API归属与用途 | M-C02受托方保留且限本地；M-C03付款即自有。候选：不填实验组拥有API，不选API入交存 | 合同/版权负责人核受托方身份、约定及任何真实后续转让/许可；收到覆盖该表达、版本和拟用途的有权文件后再审 |
| 软件版本 | M-C04表单写v1.1；技术负责人仅确认收到的是v1.0字节，未确认拟登记版本 | 技术负责人决定本次目标构建；当前正文候选写实际v1.0，保留原v1.1冲突记录，不读S11来“补齐”C案 |
| 开发方式 | 原“全部自主开发”与M-C01/02委托API矛盾 | 候选改为core/CLI模拟职务开发、API模拟委托且权利待解；版权负责人确认，不伪装已批准表单 |
| 模拟容量策略秘密 | M-C05指定API配置赋值右侧，禁止在正文/审计/日志重复原值 | 材料负责人只记位置/类型；API已经排除选材，另审任何未来副本，不以遮盖代替许可 |

可选路线比较：优先补API权利及用途材料后再决定完整软件路线；代价是当前不能形成全量交存包。若业务选择独立core+CLI范围，应先由技术负责人给可界定软件/版本和交付事实，再由版权人员审是否适用，而非删文件改名。例外交存或封存只能处理满足条件的材料形式/秘密问题，不能治愈M-C02权利与交存许可缺口；短材料例外如何成页及当前机构要求仍未核。现有内部许可足够完成下文，无需全局停工。

### C1 字节、选材与受限位置审计

| ID/路径/版本 | SHA-256 | 字节/物理原行 | 当前选材映射与理由 |
| --- | --- | --- | --- |
| S10-CORE / v1.0/core.py | 2ad5c9d389a7abbdb105c545d4ab2f72fdb4167aa728dbdb64dfb5df02f7bbe1 | 2198 / 63 | 原1—63→选1—63；M-C02/06准内部候选 |
| S10-CLI / v1.0/cli.py | 8929d151347f22ea23a3ace676e60ad0242da028577305198b1a36282883d86d | 1457 / 46 | 原1—46→选64—109；同上 |
| S10-API / v1.0/api.py | f954b7b976992b45d601d8d22215c0a2308ee4b7f9f9fdcfc0734395e5a2aad7 | 2491 / 54 | 全部排除当前源码候选；只供本地行为分析，无对应选材行 |

已读产品清单是3文件6146字节、163物理原行；当前候选为core+CLI的3655源字节、109选中去重原行，按固定顺序完整选取，API54行未混入。3655在本表表示两个原文件字节之和；本轮实际选材文本/逐行map另见文末C导出记录。注释/空行计入物理数，未把其计作法定源量或原创度；不填行、不重复、不通过改名隐去API来源。正式交存页式未生成，短程序全部要求下本子集不能代表原完整软件交存。

秘密记录C-S1只含：文件ID S10-API；路径v1.0/api.py；原行7；标识MAX_BODY_BYTES；类型为容量策略配置赋值；本案处理状态为排除API原件及具体值。本表未复制赋值右侧。若将来有权制作例外副本，须先取得API用途授权与路线确认，再在副本处理，并检查注释、示例请求、错误阈值测试、输出、页眉路径、隐藏文本及附件；不能把N/V稿或全体测试记录附上恢复被省略内容。位置审计保留内部，原件只在受控本地保管。

### C2-a 可编辑CLI正文候选

<!-- BEGIN D2-SW-C WORK PRODUCT -->
# 港湾记录整理器v1.0 CLI使用说明

稿件标识：D2-SW-C-draft1-CLI。用途：当前内部材料准备；如未来另行获准对外，此部分可作为正文候选，现尚未授权发送。本稿绑定实际S10-CORE与S10-CLI字节，拟登记版本待技术负责人确认；不采用原表单v1.1字样更改源码事实。开发完成、首次发表和真实主体未知。

## 1. 用途、范围与准备

CLI将UTF-8 JSON记录数组转为CSV，使用同版core。实际产品还含API组件；该组件有委托归属及用途争议，本正文不附其源码、详细设计或受限配置。当前源码候选是core+CLI内部子集，不代表完整软件交存齐备，也不代表已经拆出独立软件。软件没有GUI，本文不使用或伪造界面截图。

准备Python 3.11环境，将v1.0的core.py与cli.py保持相邻，并在该目录运行。两文件使用标准库，无第三方安装步骤。本示例材料环境为Windows/Python 3.11.15，其他平台未据此认证。输入须有读取权，输出父目录须存在且可写，输出文件必须不存在。可先运行python cli.py --help或python cli.py --version查看入口；源码版本为1.0。

## 2. 输入与正常操作

输入是最多1000条的JSON数组，每项是含id、label、value的对象。id、label为去空白后非空且可UTF-8编码的字符串，程序保留原串；value为非负整数，不接受bool或浮点。v1.0允许重复id，忽略额外字段；不会排序、合并或去重。空数组合法，只产生CSV表头。

以UTF-8保存records.json：

```json
[{"id":"A1","label":"north","value":3},{"id":"A2","label":"south","value":0}]
```

确认result.csv不存在后执行：

```text
python cli.py records.json result.csv
```

源码推导的成功结果：退出0，stdout为wrote 2 records；新建文件采用UTF-8、LF，完整内容为：

```csv
id,label,value
A1,north,3
A2,south,0
```

固定输出列为id,label,value，行顺序与输入相同；逗号、引号和字段内换行由csv模块转义。程序没有电子表格公式清洗，打开目标应用前按使用目的检查数据。

## 3. 失败与恢复

| 条件 | 退出码与stderr | 文件行为/操作 |
| --- | --- | --- |
| 参数错误 | 2，argparse说明 | 尚未读写文件；按帮助修正 |
| 非法JSON/UTF-8 | 2，invalid_json | 不创建新目标；修正编码/语法 |
| 非法记录 | 2，例如missing_field、invalid_id、invalid_label、invalid_text_encoding或invalid_value | 全部校验完成前不打开目标，修正输入再试 |
| 已有目标且输入合法 | 3，output_exists | 原文件保全；改用不存在的新路径 |
| 输入读取错误 | 4，input_io_error | 未创建目标；核路径与权限 |
| 输出I/O错误 | 4，output_io_error | 写入后故障可能留部分新文件，须单独核查；不保证原子写入 |

输入[{"id":"A1","label":"north","value":-1}]在创建输出前得到invalid_value、退出2；将value写成true也不合法，0合法。两个相同id但其他字段合法的对象在v1.0仍均输出。加入note字段不会新增CSV列，v1.0没有strict选项。输入与已有目标同时有问题时先做输入校验，故可能返回2而不是3，原目标均不被覆盖。

## 4. 设计与证据边界

core先将UTF-8 bytes解析为JSON，检查数组、记录和字段，只保留三字段，生成完整CSV并给出记录数。CLI读取全输入，在内存校验/生成后，以独占新建方式写文件并转成0/2/3/4退出状态；没有数据库或后台任务。内存使用、未捕获的系统故障和输出部分残留均未通过该设计消除。

来源为S10-CORE 16—63行及S10-CLI 10—46行；当前说明是静态作答，本作者未实跑。已有夹具作者的正常、负数和已有目标记录仅证明其对应输入、冻结版本与Windows环境，不是本作者运行或专业验收。具体来源核对、版权冲突与秘密位置保留内部审计，不附本正文。
<!-- END D2-SW-C WORK PRODUCT -->

### C2-b 仅内部的API设计说明

文件标识D2-SW-C-draft1-API-internal；只交M-C06的内部技术/版权角色。API是与CLI共用core的WSGI application，不是独立运行服务器，无鉴权、GUI、数据库或外网地址。路径/convert、方法POST、空query；Content-Type的分号前部分去空白转小写后须为application/json。CONTENT_LENGTH须为可转正整数且不超程序内容量上限；具体容量值为“本案已省略”。这是当前硬编码条件的省略说明，不声称软件提供配置文件、管理界面或动态调参功能。

调用者提供wsgi.input流；application读取声明字节数，要求bytes且实际长度一致，再传给core.convert。JSON数组和三字段、1000记录上限、重复ID允许/额外字段忽略均为v1.0行为。成功把core生成的CSV编码UTF-8，响应200 OK，带text/csv; charset=utf-8及实际响应字节长度；不持久化。错误JSON只含error类别，不回显原记录。

| 分支 | 状态/固定类别 | 源位置 |
| --- | --- | --- |
| 路径/方法 | 404 not_found；405 method_not_allowed及Allow: POST | S10-API 23—27行 |
| 查询/内容类型 | 400 invalid_query；415 invalid_content_type | 28—32行 |
| 声明长度不合法/超过容量 | 400 invalid_length；413 payload_too_large；容量值本案已省略 | 33—40行 |
| 流缺失/读取错误/类型或长度不符 | 400 missing_body/body_read_error/body_length_mismatch | 41—49行 |
| JSON或数据校验错误 | 400与核心固定类别 | 50—53行 |
| 成功 | 200与CSV字节 | 54行 |

内部调用可以用BytesIO封装合法JSON，构造REQUEST_METHOD=POST、PATH_INFO=/convert、QUERY_STRING为空、CONTENT_TYPE=application/json、CONTENT_LENGTH=len(payload)以及wsgi.input，通过application取得响应；不启动HTTP服务器。示例输入[{"id":"A1","label":"north","value":3}]得到CSV表头及A1,north,3；负数输入得到400与invalid_value。这里不含容量边界的具体测试载荷、阈值原值或API源码全文。未授权对外的内部设计仍可用于技术/版权审阅，但不得并入C2-a外部候选。

### C3 字段替换、有限核对与分流交接

| 字段 | 保留的原记录 | 当前候选及理由 |
| --- | --- | --- |
| 名称 | 港湾记录整理器 | 保留，M-C01与实际对象一致 |
| 版本 | M-C04：v1.1 | 当前正文/字节清单为v1.0；正式目标待技术负责人确认，原v1.1冲突不覆盖 |
| 开发方式 | 全部自主开发 | core/CLI模拟职务；API模拟委托且受托方保留表达权利；M-C02优先约束处理，不作现实权属定案 |
| 主张/交存范围 | 三组件全部原创且可交存 | 产品架构仍三组件；当前内部候选选材只core/CLI，API权利和用途待解；不是原完整软件一般交存齐备 |
| 源量/选材量 | 未统计 | 产品已读163物理原行/6146字节；当前选材109去重原行/3655源字节；官方字段口径待核 |
| 完成/发表日 | unknown/unknown | 保持未知；不以付款、表单或文件冻结日替换 |

本案不使用S11，也不把N案权利或秘密结论带入。正常/错误核对除源级读取外，可引用夹具作者记录v1.0-cli-normal：退出0、2条CSV；v1.0-cli-negative：退出2、invalid_value、未生成新文件；v1.0-cli-existing：退出3、已有文本保留。这三个记录本身不含本案标记配置原值，只将上述必要结果抽取给内部技术角色；不附整份fixture-checks或其他场景原件。作者的78项总记录不代表本案权利、秘密或正式交存通过；本作者没有重新执行。

主代理的现有SW-01/07/02实际记录给出C读163行、选109行、selected_lines逐条与原字节相等；40行/100列内部显示参数下为109展示行、3逻辑页，状态needs_review。尝试deposit用途的负例没有选中源码，报selection_purpose_not_authorized；不是登记机构拒收记录。该技术汇总不包含配置值，完整C原始工具文件仅内部保管。它没有补API权限，也不能将3逻辑页作为官方交存页式。

| 三类交接/动作 | 准确包边界、对象、目的、渠道 | 角色/状态与恢复条件 |
| --- | --- | --- |
| 当前正文与内部材料审阅 | C2-a CLI正文、C2-b仅内部API说明、C0/C1/C3审计及core/CLI原件；接收模拟实验组技术负责人、版权负责人；目的为内部范围/版本/合同审阅；本机outputs目录 | M-C06允许；本资源已成稿，真人投递未执行。技术负责人核目标版本，版权负责人核合同，材料负责人核分流 |
| API受限材料保管 | API原件留获准本地范围；审阅只给C2-b及C-S1位置审计，不复制容量原值 | 受限原件不进入候选交存；材料负责人检查注释、输出和元数据，不能把脱敏视为许可 |
| 未来外部正文候选 | 仅C2-a及经另行复核的名称/版本/范围字段；必须排除C2-b、C0/C1/C3内部审计、API原件、N/V全部稿、整份本示范、全部harbor-demo及完整测试/工具记录 | 当前无外部对象/渠道/有权批准；版权/权限负责人先核合同、用途和具体文件hash，技术负责人确认目标，方可另批；未发送 |
| 拟完整软件交存 | 原完整三组件对象仍缺API权利/用途和目标版本确认；不能以109行子集、遮盖或封存替代 | 拟接收为登记机构，具体渠道/账户未知；权利与规则审阅、实际分页、表式、完整固定包和有权批准均须落实；未执行 |
| 向受托方、公开或外部云 | 本案未给任何具体可发送包、用途授权或渠道 | 不因对方是受托方自动发送API或审计；逐项取得相应有权许可后再议 |

C案的内部动作许可已足够完成上述编辑；缺口只阻止相应权利结论和外部动作。没有真实通知或提交，SW-06状态为未进入，不算期限或声称补正。

## D2-SW-V：v1.0到v1.1的局部真实变化

### V0 双基线与范围/权利

M-V01明确本次内部目标为v1.1，S10只作保留的v1.0对照；三文件仍为同版core/CLI/API，没有新独立商品。模拟内部工程角色在同一职务任务下改动三组件，模拟约定覆盖新增表达，证据强度仍只是摘要，不补造现实权利人、签章或日期。M-V02旧正文允许重复ID、无严格模式、API数据错误400；M-V03旧表单/选材只绑定S10；M-V04记录R-S10只做旧源级一致性核对，没有专业签核、分页/截图或提交；M-V05本次只准经本机outputs向内部技术/版权角色交完整说明及三文件候选；M-V06变更简报是核对线索，不是替代源码的规格。

三组件可继续合并为同一产品版本工作范围。core新增重复ID集合与严格字段判断，CLI新增开关传递，API新增query选择与数据状态分流；拟主张的是这些本版具体表达及与原表达的组合，不因10行净增量认定全新软件或“重要改进”已满足。是否另行登记、是否事项变更仍须实际目标/旧登记事实和适用路线，当前不进入SW-06。标准库继续排除源代码主张；AI辅助仍有人工选择/改写摘要，无比例或身份定论。新增表达的真实贡献/职务依据由版权负责人核，不借旧R-S10代替。

| 基线ID/路径 | SHA-256 | 字节/物理原行 |
| --- | --- | --- |
| S10-CORE / v1.0/core.py | 2ad5c9d389a7abbdb105c545d4ab2f72fdb4167aa728dbdb64dfb5df02f7bbe1 | 2198 / 63 |
| S10-CLI / v1.0/cli.py | 8929d151347f22ea23a3ace676e60ad0242da028577305198b1a36282883d86d | 1457 / 46 |
| S10-API / v1.0/api.py | f954b7b976992b45d601d8d22215c0a2308ee4b7f9f9fdcfc0734395e5a2aad7 | 2491 / 54 |
| S11-CORE / v1.1/core.py | b91ea1a3cc3df01aa06d6c0f1f15bd15286821e750b7914e539f6f505f66f7cb | 2463 / 69 |
| S11-CLI / v1.1/cli.py | 127ffaef609a6e5a7c23bd66da43302aca88b4e63609c056c693f162da367c9a | 1572 / 47 |
| S11-API / v1.1/api.py | bdcb73959c61dbec97980323008fd457ef6277e6cd9c09682a3bece93480f005 | 2681 / 57 |

S10共6146字节/163物理原行；S11共6716字节/173物理原行。两版都是三文件，均实际读取并复算，旧哈希/行数作为历史保留。物理原行含注释/空行，不表示原创量；净增加570字节/10行不是法律改进门槛。

### V1 差异、重新选材及审阅影响

| 变化 | 旧源位置/行为 | 新源位置/行为 | 本次修订 |
| --- | --- | --- | --- |
| 版本 | S10-CORE 7行为1.0 | S11-CORE 7行为1.1；三文件标题同版 | 正文标题/环境目录、表单、映射与包绑定均改v1.1 |
| 重复ID | S10-CORE 24—48行无去重集合，允许重复 | S11-CORE 31、50—52行按原字符串拒绝重复，duplicate_id | 替换旧“同id可重复”，增加失败/恢复；不宣称自动去重 |
| 严格字段 | S10-CORE忽略额外字段 | S11-CORE 24、37—38、66—68行严格模式拒绝额外字段，默认仍忽略 | 保留默认行为，新增strict条件，不写成所有额外字段都非法 |
| CLI | S10-CLI 10—15、26行只有原两位置参数和version | S11-CLI 14、27行新增--strict并传入core | 给实际命令与unknown_field失败；退出码集合未变 |
| API query | S10-API 28—29行只接受空字符串 | S11-API 28—31行仅接受空、strict=0、strict=1 | 改请求说明和invalid_query边界 |
| API数据状态 | S10-API 50—53行将所有InputError报400 | S11-API 52—56行仅invalid_json报400，其余InputError报422 | 拆语法/原始编码错误和数据校验错误；路径/长度等状态保持 |

已读源码支持的不变项包括字段三列、原顺序、1000记录上限、value不接收bool/负数、空数组表头、字符串不trim、CLI独占新建/非原子写入、API容量/类型/长度分支、无GUI/服务器/鉴权。这些逐项来自S10与S11对应实现，保留正文描述；并非因为旧正文没提便假设不变。

| v1.1选材文件 | 新版原行 | 新累计选材原行 | 与旧映射关系 |
| --- | --- | --- | --- |
| S11-CORE | 1—69 | 1—69 | 旧63行不能截用，新增与位移已纳入 |
| S11-CLI | 1—47 | 70—116 | 旧起点64及终点109失效 |
| S11-API | 1—57 | 117—173 | 旧110—163区间不能改标题复用 |

选中去重原行173，来源字节总和6716；固定core→CLI→API顺序，完整保留短程序，不复制代码凑量。新的真实字节使三文件哈希全部变化，即便某函数正文相同也用S11哈希定位。一般交存仍以实际完整母本判断短程序/文档全部，不用本表当正式页码；没有新秘密标签，仍需对新包按用途做秘密审阅，不能继承N案“无另标秘密”当真实审查。当前M-V05仅支持内部候选；例外/封存没有给定必要事实，不自动启动。

| 历史记录/对象 | 保留什么 | 新版受影响项及接收者 |
| --- | --- | --- |
| R-S10源级一致性 | 保留其只对S10做过内部核对的事实 | 技术负责人重审S11真实差异、错误状态和参数；本作者源级分析不是其签核 |
| M-V03旧选材 | 保留S10原哈希、163行与旧累计区间 | 材料负责人使用S11映射重建173行候选；根工具已观察previous_material失效，不等于专业批准 |
| M-V02旧说明/M-V03旧表单 | 原文及v1.0字段不覆盖 | 用V2完整新版正文和V3新字段候选；版本、重复规则、strict、状态及量均待对应角色复核 |
| 权利/秘密 | 旧模拟约定和记录仍是旧事实 | 版权负责人核新增三组件表达的真实依据；材料负责人重新看新包与用途，旧未知仍未知 |
| 页式/渲染 | R-S10本来没有正式页码/截图，不制造“旧已通过” | rendering接V2当前字节，实际排版/截图由新证据记录；官方分页与实体打印未执行 |
| 旧拟外部审阅用途 | 仅曾考虑v1.0 CLI摘要，未执行 | 新完整CLI/API/源码超出旧方案；权限负责人重新核包、对象、用途、渠道与有权批准 |

### V2 可独立阅读的新版完整正文

<!-- BEGIN D2-SW-V WORK PRODUCT -->
# 港湾记录整理器v1.1使用与设计说明

稿件标识：D2-SW-V-draft1。用于内部软件版权材料准备，绑定S11-CORE、S11-CLI、S11-API冻结字节。本稿替换本次工作中对M-V02旧行为的依赖，旧稿仍保留为v1.0历史。正文为本作者静态整理；夹具作者的另行运行记录只覆盖其明确输入及环境。完成日期、首次发表日期及真实权利人未确认。

## 1. 软件及准备

软件将UTF-8 JSON记录数组转换为CSV，提供CLI与供内部程序调用的WSGI application，共用core。v1.1始终拒绝重复ID，并增加可选严格字段模式；没有GUI、数据库、联网客户端、服务器启动或鉴权模块。当前材料不提供公网服务部署和安全能力保证。

准备Python 3.11，将v1.1的core.py、cli.py、api.py保持相邻，在该目录运行。依赖只有Python标准库，不需第三方包。夹具环境为Windows/Python 3.11.15；没有据此验证其他平台。输入文件应可读，输出父目录应存在且可写，输出文件必须尚不存在。不要将两个版本模块放入同一运行目录；比较版本时用不同进程避免导入缓存串版。

```text
python cli.py --help
python cli.py --version
```

本版version输出为1.1。软件未提供pip安装命令、系统服务或网络监听入口。

## 2. 输入与转换规则

输入须为UTF-8 JSON数组，最多1000条，空数组合法。每项须为对象并包含id、label、value。id和label必须是去空白后非空且可UTF-8编码的字符串；原串仍保留，不trim、不转大小写。value必须为非负整数，bool、浮点和负数不合法。

v1.1对id原字符串作相等比较并拒绝重复；A1与a1、A1与带前后空白的不同字符串不被规范化为同一ID。程序不会替用户合并重复记录或改写ID。默认模式仍忽略额外字段；严格模式要求字段集合恰为id、label、value，有额外字段返回unknown_field，缺必需字段仍先返回missing_field。

输出固定三列id,label,value，保留输入记录顺序，以UTF-8和LF保存；csv模块负责逗号、引号及换行转义。空数组仅输出表头。软件未提供电子表格公式式文本清洗，应按后续打开用途审查数据。

## 3. CLI成功操作与严格模式

保存UTF-8文件records.json：

```json
[
  {"id":"A1","label":"north","value":3},
  {"id":"A2","label":"south","value":0}
]
```

以下两条均为合法操作，但须分别使用不存在的输出文件：

```text
python cli.py records.json result.csv
python cli.py records.json strict-result.csv --strict
```

对上述输入，两种模式预期均退出0、stdout为wrote 2 records，输出内容为：

```csv
id,label,value
A1,north,3
A2,south,0
```

CLI先读完输入、完成全部解码和记录校验并生成内存CSV，再以独占新建打开输出。不会覆盖已有文件。严格模式只改变额外字段规则，不能关闭重复ID拒绝。

## 4. CLI失败、对照与恢复

| 条件 | 退出码/诊断 | 处理结果 |
| --- | --- | --- |
| 成功 | 0；wrote N records | 创建新CSV |
| 数据或JSON/UTF-8非法 | 2；固定错误类别 | 打开输出前失败，不生成新目标 |
| 参数错误 | 2；argparse帮助 | 未进入文件处理 |
| 已有输出且输入合法 | 3；output_exists | 保留原目标，选新路径 |
| 输入I/O错误 | 4；input_io_error | 未创建新目标 |
| 输出I/O错误 | 4；output_io_error | 写入后故障可能留部分新文件，需单独核查，不承诺原子写入 |

重复ID示例：

```json
[{"id":"a","label":"A","value":1},{"id":"a","label":"B","value":2}]
```

v1.1默认与严格模式均返回duplicate_id、退出2且不新建输出。v1.0曾输出两条；升级后须由数据提供者核实记录身份并提供合法唯一ID，不由程序静默删去一条。

额外字段示例：

```json
[{"id":"a","label":"A","value":1,"note":"extra"}]
```

默认模式输出a,A,1；带--strict时返回unknown_field、退出2且不创建新目标。需要严格模式时先确认note确可从该输入表示中移除，再用修正文件重试；若本次业务允许额外字段，则明确选择默认模式。缺id/label/value为missing_field；空白ID/label为invalid_id/invalid_label；负数、bool或浮点为invalid_value；不能编码的字符串为invalid_text_encoding；原始UTF-8或JSON语法错误为invalid_json。先输入校验、后目标创建，因此非法输入与已有目标同时存在时先返回2，原目标仍保全。

## 5. WSGI接口

入口为api.application(environ, start_response)，只接受POST /convert。QUERY_STRING只允许空字符串、strict=0或strict=1；后者开启严格模式，前两者关闭。实现按整个query字面值判断，不接受重复参数、其他字段、其他拼写或自动URL规范化的推定。三种合法query均拒绝重复ID。

Content-Type的分号前部分去空白转小写后须为application/json。CONTENT_LENGTH须能转换成正整数，不超过65536字节；wsgi.input应提供read(length)，结果必须为同长度的bytes。实现只读声明长度，不额外确认流末尾。成功返回200 OK、text/csv; charset=utf-8、实际响应字节长度及CSV主体。

| 条件 | 状态 | error/说明 |
| --- | --- | --- |
| 非/convert路径 | 404 Not Found | not_found |
| 正确路径、非POST | 405 Method Not Allowed | method_not_allowed，Allow: POST |
| 非法query | 400 Bad Request | invalid_query |
| 内容类型不符 | 415 Unsupported Media Type | invalid_content_type |
| 声明长度缺失/无法转换/不为正 | 400 Bad Request | invalid_length |
| 超容量 | 413 Payload Too Large | payload_too_large |
| 流缺失、读取错误、类型/长度不符 | 400 Bad Request | missing_body、body_read_error、body_length_mismatch |
| 原始UTF-8或JSON语法错误 | 400 Bad Request | invalid_json |
| 已解码数据校验错误 | 422 Unprocessable Entity | duplicate_id、unknown_field、invalid_value等核心类别 |

JSON中转义产生的未配对代理字符会在字段UTF-8可编码校验处触发invalid_text_encoding，属422；原始字节不能解码为UTF-8则在decode_payload触发invalid_json，仍是400。不能把所有“编码错误”或所有失败笼统改成422。错误主体为仅含error字段的JSON，Content-Type为application/json，不回显记录。

下例在本版目录中作内存调用，不启动服务器：

```python
from io import BytesIO
from api import application

payload = b'[{"id":"A1","label":"north","value":3}]'
captured = {}

def start_response(status, headers):
    captured["status"] = status
    captured["headers"] = dict(headers)

environ = {
    "REQUEST_METHOD": "POST",
    "PATH_INFO": "/convert",
    "QUERY_STRING": "strict=1",
    "CONTENT_TYPE": "application/json",
    "CONTENT_LENGTH": str(len(payload)),
    "wsgi.input": BytesIO(payload),
}
body = b"".join(application(environ, start_response))
print(captured["status"])
print(body.decode("utf-8"), end="")
```

静态预期为200 OK及CSV表头、A1,north,3。将payload换为含note的上例、保持strict=1并同步CONTENT_LENGTH，预期为422与{"error":"unknown_field"}；将QUERY_STRING改为strict=0或空则成功。若换重复ID输入，即使strict=0也返回422与duplicate_id。传入非法JSON则400与invalid_json。每次调用均须重新构造BytesIO，已经读过的流不能直接当新请求复用。

## 6. 设计与限制

core.decode_payload解析UTF-8 JSON；validate_records保留原顺序，先检查必需字段，按strict检查额外字段，再核ID/label/数值，以seen_ids拒绝重复ID；render_csv输出三列，convert返回CSV及记录数。CLI仅新增--strict到core的传递，文件处理与退出码仍沿上述路径。API把合法query转成布尔值传core，把invalid_json分为400，其余InputError分为422；协议入口检查仍有独立状态。

输入与输出在内存处理。CLI没有API的正文容量上限检查；API无服务器、鉴权、持久化或完整HTTP协议栈。源码仅处理列明错误，不承诺恶意WSGI对象、磁盘满/崩溃、性能或并发保障。CLI非原子写入；现有输出不覆盖和失败前不创建只是各自分支事实。无GUI，命令和响应例不等于截图。

## 7. 本稿依据

| 内容 | 新版来源 |
| --- | --- |
| 输入及strict/重复ID | S11-CORE 24—54行 |
| 输出与空数组 | S11-CORE 57—69行 |
| CLI参数、调用与文件状态 | S11-CLI 10—43行 |
| API query/容量/流/状态 | S11-API 21—57行 |
| 本次版本、内部用途与旧稿边界 | M-V01—06 |

本稿需要技术事实、版权/规则和材料/渲染各自审阅。旧v1.0的内部核对与拟外部用途不批准本版发送、登记或公开。
<!-- END D2-SW-V WORK PRODUCT -->

### V3 表单候选、行为对照与三类交接

| 字段/旧段落 | 本次实际替换候选 | 保留/待核 |
| --- | --- | --- |
| 软件名称 | 港湾记录整理器 | 同一产品，名称未变 |
| 版本 | v1.1 | M-V01和S11绑定；M-V03的v1.0原记录保留 |
| 组件/开发方式 | core/CLI/API共同发布；模拟同一职务任务含新增表达 | 真实权利/贡献依据仍待版权负责人，未变成“已确权” |
| 源量/选材 | S11三文件6716字节、173物理原行；全量173选中去重原行 | 替换本次候选中的S10 6146/163和旧区间；官方字段口径另核 |
| 旧“同id可以重复” | v1.1始终拒绝原字符串相等的重复ID，CLI退出2/API数据状态422 | V2完整段落可独立使用，不只改版本号 |
| 旧“无严格模式” | 默认忽略额外字段；--strict或query strict=1拒绝额外字段，缺必需字段仍先处理 | API合法query仅空、strict=0/1 |
| 旧“数据内容校验失败400” | 数据校验失败422；invalid_json及入口/query/长度等既定400仍400 | V2分表；不把全部错误改422 |
| 完成/发表日 | unknown/unknown | 无新事实；冻结/运行时间不替代 |
| 环境/无GUI | Python 3.11标准库；本次夹具Windows/Python3.11.15；无GUI | 源码与实跑范围分别表述，不增加平台保证 |

两组真实输入的版本对照如下，源码位置见V1；“已运行”均指夹具作者的记录，本作者没有重跑：

| 对照输入及证据 | v1.0记录 | v1.1记录 | 说明影响 |
| --- | --- | --- | --- |
| [{"id":"a","label":"A","value":1},{"id":"a","label":"B","value":2}]；input SHA-256 7804dcf6de85a93a4c1bd09f87e5708bb4e9d3d6d416a174f9ea1501cad563b4 | v1.0-cli-duplicate退出0，输出两条；v1.0-api-duplicate为200 | v1.1-cli-duplicate退出2、duplicate_id且无新目标；v1.1-api-duplicate为422与duplicate_id | 必须修订旧允许重复的正文和失败恢复 |
| [{"id":"a","label":"A","value":1,"note":"extra"}]；input SHA-256 1ba7d86b728a5c0fb0086c23abd9c4df45249ea19228fdfa5b45ede372fb89ac | 默认成功；--strict未识别而退出2；strict=1 query为400 invalid_query | 默认仍成功；v1.1-cli-extra-strict退出2、unknown_field且无新目标；v1.1-api-extra-strict为422与unknown_field | 新严格模式及默认不变须同时写，不能把旧参数错误与新数据错误混作同一结果 |

另已读记录v1.0-api-negative→v1.1-api-negative从400改422，主体均invalid_value；v1.1-api-invalid-json与v1.1-api-invalid-utf8保持400 invalid_json。记录为Windows/Python3.11.15、独立版本进程与内存WSGI，无服务器/网络。fixture-checks共78项、78通过/0失败/0跳过只证明列出的合成输入；未作磁盘满/崩溃注入、性能、跨平台、GUI、专业或登记验收。

主代理实际SW-01/07/02记录V为173源行/173选中原行，逐行与S11相等；40行/100列内部显示得173展示行、5逻辑页，previous_material返回invalidated，表明旧材料绑定不适用于新版本，不是新版权审阅通过。deposit负例为无选中源码，仍需正式用途许可。实际导出与逐行映射见本资源末尾开发证据便笺，不用内部5页充当官方页式。

| 三类成果/动作 | 本次包、对象、用途、渠道 | 状态/责任与恢复条件 |
| --- | --- | --- |
| 正文候选内部审阅 | V2完整D2-SW-V-draft1，绑定S11三哈希；模拟实验组技术/版权负责人；完整CLI/API内部材料准备；本机outputs | M-V05已准内部，稿已完成；技术负责人复核行为，真人投递未执行 |
| 内部审计 | V0/V1/V3及新173行映射、S10对照、R-S10保留与影响表；同内部角色/渠道 | 材料负责人核字节/秘密/表式，版权负责人核新增表达与路线；旧未知不因升级关闭 |
| rendering交接 | 仅V2当前正文及必要来源/用途说明，要求同版排版、裁切/隐藏信息检查；不附全部权利审计到正文 | 由实际渲染记录证明完成范围；正式页式/实体打印未执行，不改R-S10历史 |
| 外部审阅候选 | 具体拟包需在V2及源码中另行选定；外部对象/实际渠道未给，不能继承旧v1.0 CLI摘要方案 | 权限负责人核新对象、用途、渠道、有权批准和版本hash；未授权/未发送 |
| 正式交存/公开/云处理 | 每种动作分别固定材料和接收对象；交存拟登记机构但账号/渠道未定；公开和云处理对象均未定 | 补权利/机构要求/实际页式、秘密处理和具体行动签核后方可恢复对应动作；本轮均未执行，无官方回执 |

这是一次同一产品内部版本修订材料交付，不宣称已登记、变更或补正；没有原通知/送达便不算SW-06期限。

## 开发证据便笺（不属于任一案的外发正文）

本资源已自含做出取舍和复核正文所需的模拟材料、源哈希、行映射及行为事实。以下为主仓库的开发证据位置，运行包不携带这些记录，也不依赖它们解析本资源；只需相对链接的六源文件和规则研究即可检查静态方法。包外记录不能自动并入C案交接。

| 记录 | 实际完成与限制 |
| --- | --- |
| evals/workflows/deepening-software-d2-inputs.json | 2026-11-01冻结六源文件、题目与预设检查；本作者读取字节并复算，与上表一致；未修改冻结源码 |
| evals/workflows/deepening-software-d2-fixture-checks.json | 夹具作者以python -B outputs/deepening-software-d2/fixture-checks-run.py在Windows/Python3.11.15实际执行，退出0；每版15 CLI+24内存WSGI，总78项全满足，无跳过；未开服务器/联网。未做磁盘满/崩溃注入、性能、跨平台、GUI或专业验收 |
| evals/workflows/deepening-software-d2-source-tool-checks.json | 主代理实际执行已有SW-01/07/02，N/C/V原行分别163/163/173、选中163/109/173；逐条与来源相等；内部逻辑页5/3/5，非官方页式；三案deposit负例选中0；V旧绑定失效 |
| evals/workflows/deepening-software-d2-source-exports.json | 主代理导出三个所选文本及逐行原位置map，未插页眉/伪代码；C输出不含API。串接文本是材料，不是可执行合并程序；正式交存分页未做 |

实际导出绑定如下；map逐行含来源文件/原行，来源全文已由前述六文件哈希固定，不用重复源码填充本文。

| 场景 | 所选文本及SHA-256 | 逐行映射及SHA-256 |
| --- | --- | --- |
| N | outputs/deepening-software-d2/N-selected-source.txt；d987e726c77ebb982e8996cbb22b1036b8f3931e271a93e464e61019b6010b35 | outputs/deepening-software-d2/N-line-map.json；8539b9ac9331393ecef47af72184c2b306d6c23f404a029b4c187436ea74d3b0 |
| C | outputs/deepening-software-d2/C-selected-source.txt；f5f1eeff10e85f21235c37f0727c062873782a82af7339d7cf53e03685a5e05e | outputs/deepening-software-d2/C-line-map.json；dcd8a9882c4daaa9950fe40a4378b45ce2e672165ea594085b7f17cf746163a4 |
| V | outputs/deepening-software-d2/V-selected-source.txt；79771e097b95685d59522af53f71af883641a823049204c1dcc6e79912f13954 | outputs/deepening-software-d2/V-line-map.json；3bec25eef0655637577ef3d8a24849d6fc00e1a06445ca8a9219b40a47f79b33 |

原始开发作答另保全于evals/workflows/deepening-software-d2-development-response.md。方法预审、作者开发检查、其他执行者作答、渲染和工具回归分别记录；本示范不以篇幅、78项技术结果或来源研究代替独立/专业验收，也不关闭历史B06问题。
