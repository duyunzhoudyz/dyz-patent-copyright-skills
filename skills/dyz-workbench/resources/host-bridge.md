# 本地文件工具：控制器接入

这个入口供本地控制器或宿主适配开发使用。普通写作仍从相应Skill开始；不要求用户手写工具请求。完整包必须包含共享`tools`，不能只复制本资源或单个Skill。

## 已实现的接口

Python 3.11标准库：`tools.host_bridge.HostToolBridge`、`dynamic_tools()`；也可从完整包根运行`python -B -m tools.host_bridge --describe`。从其他目录可运行完整包中`tools/host_bridge.py`的绝对路径；使用`-I -S -B -X utf8`可关闭用户站点、环境搜索路径及字节码写入。这里只启动本地文件工具，不启动模型、账户RPC、浏览器或办公转换器。

| 接口 | 用途与限制 |
| --- | --- |
| `case_read` | 分段读UTF-8；返回原字节hash及实际行／列覆盖。`next_position`非空时，同实例对同scope/path传`next_chunk:true`续读，服务端重核源hash；也保留显式位置/hash方式。片段与hash不能当全文已读。 |
| `case_write` | 在`work/`或`output/`创建文本；更新必须给当前hash，并在控制目录保留原文。拒绝伪造DOCX／PDF／PNG。 |
| `case_info` | 读取一个允许文件的大小与hash，不列目录、不证明专业审核。 |
| `case_copy` | 按源hash复制至新的`work/`或`output/`路径，不覆盖。 |
| `case_image` | 返回有界PNG及原图尺寸；只验签名／尺寸，不认证来源、完整解码或宿主显示。 |
| `case_documents` | 调用包内文档装配／回验；生成须新建目录，`verify:true`须配方与由其生成的包目录成对，不作跨版比较。仅合成或明确声明的原创研究示例，不执行PDF转换。 |
| `case_docx_review` | `input`为已存在的当前DOCX；可选`baseline`为已存在的旧DOCX，没有旧Word稿时省略。`summary:true`可优先返回有界差异／异常／原文片段及完整报告定位。保留partial／unknown，不等于显示或专业验收。 |
| `case_fidelity` | 对合成的有限形式关系生成报告；调用成功时报告仍可能blocked，不证明自然语言或法律支持。 |
| `case_standard_package` | 以`input/output/mode`及可选布尔`verify`生成/回验同版标准五文书；`mode`仅synthetic，拒绝真实模式与PDF转换。缺证状态保留，不认证专业就绪。 |
| `case_software` | `action`为intake/prepare/build/verify，root仅省略或`.`。准备/构建/回验以authorization及authorization_sha256复用软件CLI；intake需新output，可传answers续接和candidates:true启用候选集中确认。缺答案返回实际next_question，未经最终确认不读取材料或创建采集目录；其他动作禁止candidates。仅DOCX本地链，PDF工具及正式动作不由宿主参数注入。 |

保持这些wire ID只为兼容既有控制器，不表示当前模型已发现或调用。`dynamic_tools()`返回十个函数schema；不同宿主的注册、权限、模型数据路径、读取确认、续接与交接仍须单独验证。

文档装配配方JSON是`case_documents.input`，不能作为`case_docx_review`的当前稿或旧稿。后者启动文件子进程前核文件及`.docx`后缀，字段类型错误分别返回`current_docx_required`或`baseline_docx_required`；DOCX实际内容仍由回查工具验证。错误实参不会被自动删除、替换或转换。源稿与装配包的绑定另用`case_documents`的`verify:true`核对，不充当两份Word稿的差异比较。

`verify:true`只核给定配方／目录这一组。核旧版用旧配方和旧目录，核当前版用当前配方和当前目录；把旧配方指向新目录会因规范化输入绑定不同而拒绝`document_input_binding_changed`，不能事后当成成功比较。续接记录保留每组配方／manifest／Word的路径与hash以及实际校验结果；两份实际Word之间的差异交`case_docx_review`。配对与hash种类见[文档装配契约](../../dyz-rendering/resources/tools.md#合成文稿的docxpdf装配)，不自动修正错误配对或沿用旧审阅。

## 按需读取与结果定位

先用Skill任务导航确定方法与主材料；已知路径只需版本时用`case_info`，需要判断才用`case_read`取原文。`case_read`的`max_lines`是单次范围，不是全文覆盖；仅在`next_position`非空且后续内容确需读取时用`next_chunk:true`。同版已读且仍可用的内容不重复请求；源变更保留旧覆盖并从受影响位置重新读。

长回查优先给`case_docx_review`传`summary:true`，返回有界变化片段、异常定位、分组数量和明确省略项；完整报告仍写入`output`并绑定hash。详细字段与补读方式见[可选精简返回](../../dyz-rendering/resources/docx-readback.md#可选精简返回工具14)，审阅次序见[Word报告阅读顺序](../../dyz-rendering/resources/docx-readback.md#差异与异常的读取顺序)。该选项只适用于Word回查，其他接口没有摘要／投影参数。摘要片段仍是受检材料，控制器保存返回须沿用留痕权限；不能声称模型已读未返回的内容。

## 目录与可信绑定

包、工作区、控制目录须预先存在、互不嵌套，控制目录须无本入口保留的旧调用产物。工作区只有`input/`、`work/`、`output/`可读，只有后两者可写；控制器文件放在工作区以外。包只读固定清单文件。拒绝相对路径逃逸、链接／reparse、硬链接文件；控制器负责防止并发替换根目录和文件，这些Python检查不是OS隔离。

构造入口必须给包外保留的准确清单SHA-256；不要从未经信任的包自行取hash来认证它。用[包校验器](package-use.md#1-先保留构建依据再核字节)核对来源绑定；清单一致不证明来源、许可、专业状态或宿主验收。工作区使用合成材料或明确允许的原创研究示例；真实案件的数据路径和授权须另核。

文件子进程直接使用当前Python的基础解释器，带`-I -S -B`，只继承必要OS临时目录变量，不继承供应商密钥、代理、账户或会话环境。业务模块只从已绑定清单中的源码加载并核hash，不读／执行包中未列出的pyc。审计绑定实际子进程PID及worker源码hash；Python文件／网络／子进程事件受到检查，不代表全部OS或本机原生进程出口受控。worker上限30秒，超时只结束该自有文件子进程，可能保留部分输出，先核实再恢复，不自动重复。

## 本地NDJSON示例

由控制器创建独立目录并填写已可信保存的清单hash后启动：

```powershell
python -I -S -B -X utf8 D:/dyz-local-bundle/tools/host_bridge.py --package D:/dyz-local-bundle --workspace D:/dyz-case --control D:/dyz-case-control --manifest-sha256 <可信清单SHA256>
```

每行一个UTF-8 JSON对象，响应也每行一个；关闭stdin正常结束：

```json
{"id":"read-1","tool":"case_read","arguments":{"scope":"workspace","path":"input/source.md","max_lines":1}}
```

仅在上一回`next_position`非空时，在同一入口实例中继续：

```json
{"id":"read-2","tool":"case_read","arguments":{"scope":"workspace","path":"input/source.md","next_chunk":true,"max_lines":80}}
```

`next_chunk`缓存只含该scope/path下一段的行、列和源SHA，不缓存正文；每次仍读取并重核实际源字节。源改变返回`source_version_changed`，没有前次位置或已经EOF返回`no_continuation_available`。它不能与`start_line`、`start_column`或`expected_sha256`混用；混用拒绝，不自动修正调用者给出的错误hash。手动位置/hash方式仍按原契约校验。失败不推进位置，返回对象被调用者改动也不改变内部位置；跨实例不能继承该内存状态。

必须使用唯一请求ID；重复ID拒绝且不重放。默认最多120个已接纳调用，已登记失败也消耗额度，每次返回剩余额度；非法传输帧或重复ID不进入文件执行。单行上限32000000字节，超限拒绝并结束，不能拿默认额度充当整个案件的合理预算。Python原生回调方法另要求明确thread／turn绑定，并拒绝同一会话重复callId；它不创建模型线程或发送RPC。

## 留痕与恢复

产品默认只把请求／回答hash、工具ID、成功／错误及额度写入`call-NNNN.json`并保留在内存，不存调用正文、读回文字、图片base64或完整stdout／stderr。返回给调用者的实际结果含所需内容，宿主自己的日志政策仍需核实。任务文件、worker任务路径／必要审计元数据及`write-NNNN.before`原文备份仍是私人材料，不可把整个控制目录当已脱敏的公开日志。

开发评测适配器才显式选择完整合成轨迹，包括参数、回答与stdout／stderr；该适配器不随包分发。产品Python API的`record_payloads=True`只可在材料／留痕获准时显式使用，命令行没有这个开关。

一个控制目录对应一次执行器实例；已有保留产物会在新实例构造时拒绝。中断后保留原目录和产物，先确认旧worker已结束、审阅部分结果，再使用新控制目录和新的请求ID，按当前文件hash续接。它不自动恢复跨进程额度、验证案件授权或继承旧专业签核。
