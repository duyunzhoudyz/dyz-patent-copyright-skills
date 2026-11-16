# 程序工具契约与调用

仅在使用19项本地结构化辅助或核对状态/依赖时阅读；命令以包根为工作目录。 返回[技能入口](../SKILL.md)。

## 工具支持范围与依赖

实现入口为 `tools.procedure.run(capability: str, payload: dict) -> dict`，能力常量为 `CAPABILITIES`。覆盖 WP-05 程序前置、WP-08 的辅助分支，并提供 WP-10 可复用的适配轴与显式规则计算机制。**19个入口不是19项完整专业支持**；不得称为现行全球规则库、自动审查答复或可直接办理业务的工具。

必须与本项目 `tools/__init__.py`、`tools/core.py`、`tools/procedure.py` 同包使用；PROC-05实际文本质量与可选有限关系复核需同包的 `tools/fidelity.py`，并使该包的根目录位于 Python 导入路径。只复制本技能目录不能运行。Python 3.11 标准库，无第三方依赖；本轮验证环境为 Windows / PowerShell 5.x / Python 3.11.15。未验证其他宿主安装、独立分发或外部服务。原创新增工具遵循项目 PolyForm Noncommercial 1.0.0 与单独商业授权；没有复用上游代码或受限标准全文。

- 使用场景：已获得合法结构化证据，需要发现逐内容支持／日期缺口、通知遗漏、版本错配、程序异常、产品证据未知、许可边界或成本过期。
- 不适用：要求工具认定新颖性、有效优先权、侵权、自由实施、SEP必要性、许可已获、权利恢复；要求代签、付款、公开或正式提交。
- 本工具不抽取 PDF、获取官方记录、验证身份、检索互联网、识别隐藏正文、计算语义支持或生成法律意见。真实通知先通过获准取证与人工核对转成稳定意见ID；不把合成通知标成官方。

## 先确认资料权限

本模块接收内存 JSON，不读取文件、不发送网络、不运行命令。**本地函数不是宿主的外发隔离或离线证明**。敏感材料进入宿主、索引或工具之前由共享 `core.preflight` 核验路径及权限。材料合法取得不等于允许上传、翻译或再分发。私有输入与输出放在获准私人存储，不进入公开示例或日志。

`evidence.kind=authorized` 是调用者的事实主张，不是工具授予权限。示例全部为合成数据，无真实申请号、签章、当事人材料或现行规则结论。

## 调用步骤

1. 选定一个能力ID，固定法域、权利类型、领域、阶段以及评估时点。
2. 按 [输入契约](input-contracts.md) 准备公共字段和该能力字段。证据有ID、版本、来源、位置、材料类别；引用不可指向不存在的证据。技术特征与组合分别建ID。
3. 对每条日期保留原时区；未知用 `null`，不得用取得时间替代公开时间。程序截止日不得从统一模板天数推断。
4. 调用 `run`，查看 `issues`、实际任务产物及保留的未知项。不得仅依据顶层状态省略审阅。
5. 保存 `artifacts.input_digest`。输入、适配或证据改变后把旧值放入 `previous_input_digest` 再运行。新结果为 `invalidated`，同时提供重算结果与 `recomputed_status`；这是旧审核重审提示，不等于自动授予新的审核。
6. 交给相应法域专业人员及技术负责人确认。拟公开支持交 PROC-02、ANALYSIS-05、REVIEW-02；SEP／许可交 STD-08 与 RIGHTS-03/06/07。任何外发转共享 CORE-04 的具体包审批，不由本模块执行。

在项目根目录运行合成样例，不访问外部服务、不写输出文件：

```powershell
python -c "import json; from pathlib import Path; from tools.procedure import run; p=json.loads(Path('skills/dyz-procedure/resources/example.json').read_text(encoding='utf-8')); print(json.dumps(run('PROC-02', p), ensure_ascii=False, indent=2))"
```

Python API：

```python
from tools.procedure import CAPABILITIES, run
from tools.core import ContractError

# payload 是调用者经过授权、已解析并完成权限预检的字典。
try:
    report = run("PROC-02", payload)
except ContractError as exc:
    # 只记录结构错误码，不打印私人输入。
    diagnostic_code = str(exc)
```

例中 `payload` 的完整内容见 [example.json](example.json)。其中旧申请支持 `feature-a`，新增组合 `combination-ab` 在 TEST 地无支持；第二目标地 OTHER 不能继承 TEST 的支持或日期。结果是可复核的支持矩阵，不是公开许可。完整19项可运行合成输入还见开发用 `evals/test_procedure.py` 的 `example(capability)`；它不属于运行依赖。

## PROC-05实际答复与替换候选

先实际写出任务要求的候选，再由执行者准备记录；不让使用者重新填写事实表。给定材料只能支持局部时，交局部正文并列片段边界；缺上下文不要求补造完整权项。`replacement_required`记录任务要求，`replacement_candidates`携带实际文字，不能用删除指令或回到旧稿替代。完整输入见[原创合成示例](oa-delivery-example.json)，字段见[PROC-05输入契约](input-contracts.md#proc-05通知逐项回应与修改依据)。

```powershell
python -B -m tools run PROC-05 --synthetic --root . --input skills/dyz-procedure/resources/oa-delivery-example.json --output oa-delivery-result.json
```

结果目标须不存在。示例返回“光学接口”的实际局部候选及边界，状态仍为needs_review；不代表正式提交、法律支持或专业签核。可选fidelity只复用已有的[有限事实关系方法](../../dyz-patent/resources/fact-and-support-review.md)：逐条实际答复和候选绑定到当前文本、版本和字符位置；替换稿已登记的旧条件及新增关系一并核，不只查本轮amendments。原文只给接口时，另加自动启泵的已形式化关系会得到反例；确有依据的保留条件、局部文字及合法保义表达不因与原句字面不同而自动拒绝。

不提供该复核时明确not_performed；独立的`artifacts.text_quality`仍扫描实际responses与replacement_candidates，无实际文字时标not_performed而非空检查通过。正文残留待确认项使输出blocked，但工作文字保留供修订；只提交resolution记录不豁免残留。措辞只作review建议，不自动改写答复。轻量检查不认证语义、原始支持或专业可提交。提供fidelity后不能只引用另一份正确示范，bindings须覆盖全部实际答复与候选。候选不得借用另一版本原文、产品事实或其他片段的断言。自然语言到命题的解释、正文区域分类、材料真实性、语义支持及局部是否可扩成完整权项均未由工具验证，错误分类仍可能漏掉未登记关系；需要逐句审阅。不把程序接口可拦指定反例称为任意模型输出的硬门禁，也不据此恢复旧审阅或外发权限。

**首版限制：** 原申请的技术修改支持与答复论证的事实、引证及法律依据应分别审阅；当前工具尚未分开这两类最终核验。法律／程序／对比文献论证往往不来自原申请，与替换稿共用原申请门禁可能被拒绝。通常完整OA不承诺通过本版final；在draft中保留有来源的内部论证及替换工作稿，逐类交法域专业审阅，不将后到文献或法规伪装为role=original，也不删除论证换通过。draft不取得最终提交或发送许可。

PROC-05设置`delivery_stage=final`或显式提供`final_text_sources`时，对实际responses和replacement_candidates一起运行[最终正文门禁](../../dyz-patent/resources/tools.md#最终正文验收门禁)。原文列表采用id/version/role=original/text/sha256；缺省时只用fidelity.documents的original。任何文字缺依据、条件方向改变、从属重复、无法解析或缺覆盖均抛final_text_gate_blocked，不返回可交付候选。普通draft保持原内部分析用途，未检查不称最终放行。该门禁不裁定答复策略或法律支持，复杂论证超出支持子集时须保持阻断。

## 实际交付与专业边界

| 能力 | 已实现的确定性辅助 | 仍需外部事实／专业资源 |
| --- | --- | --- |
| PROC-01 | 逐内容事件排序、公开／潜在公开识别、逐地保密／涉外／首次申请条件缺口 | 公开法律效果、例外、首次路线意见 |
| PROC-02 | 内容×目标地支持矩阵、实际提交与候选日期、逐内容优先权证据隔离 | 原始支持实质判断、有效优先权及主体资格 |
| PROC-03 | 逐地显式已审规则选择、日／月运算、显式例外调整、材料及费用资格缺口 | 当前规则来源与专业审阅、真实假日／时区／例外及关键日签核 |
| PROC-04 | 文件清单与摘要、漏件、回执版本错配、失败／不明／传输成功分列、新引证待办 | 官方接口、表单规则、签章、有效申请日核验；无真实提交 |
| PROC-05 | 真实／合成标识、稳定意见ID覆盖检查、实际候选及局部边界、可选全部答复／候选的有限关系与版本绑定、跨地引证待办 | 通知原件提取真实性、自然语言抽取、实际修改支持、答复策略／替换稿专业起草与当前规则 |
| PROC-06 | 议程和参与者确认纪要分离、漏件／错填／限制／提交错误的处置待办 | 实际沟通、补救资格与正式程序 |
| PROC-07 | 母案图及环检出、内容／新增内容／地区支持分离、后续条件缺口 | 分案／延续／CIP等法域适配、权属及期限判断 |
| PROC-08 | 决定／期限失误事实和救济路径整理、未知资格／期限保留 | 具体救济适用性、正式请求、实际恢复决定 |
| PROC-09 | 官方版本与批准稿的逐节差异、独立路线记录 | 更正、授权生效、欧洲不同途径资格及费用核验 |
| RIGHTS-01 | 权项版本—产品版本—要素—取证位置矩阵 | 术语解释、完整档案与真实内部产品机制 |
| RIGHTS-02 | present／absent／unobserved／unknown分列、营销证据不替代内部机制 | 文字及等同原则、逐地侵权意见 |
| RIGHTS-03 | 产品行为／地域／时点、检索和状态证据缺口、未知要素 | 真实数据库覆盖、当前法律状态和FTO专业结论 |
| RIGHTS-04 | 按关键日筛候选／仅线索／特殊日期审查、理由与举证事项对应 | 各地无效／异议实体及程序、证据真实性 |
| RIGHTS-05 | 设计变化、功能验证计划、未覆盖权项与新产品版本补检索待办 | 独立研发真实性、重新检索、等同及不侵权意见 |
| RIGHTS-06 | 产品／地域／行为集合差、期限、权利链／负担／签署权限缺口 | 有效交易范围、谈判、实际签约；无估值或代签 |
| RIGHTS-07 | 标准版本—权项版本—逐要素技术映射缺口、政策冲突交接 | 必要性／替代实现／FRAND／竞争合规；声明不推出许可或FTO |
| SEARCH-07 | 无效与FTO筛选目的分离、失效文献保留、过时状态不清除风险 | 真实检索和各地法律效果；不是搜索引擎 |
| SEARCH-08 | 按时间窗与文献／同族口径重算功效矩阵、未知同族分列、缺库披露 | 数据覆盖、主体消歧、持续监测调度及可专利性判断 |
| LIFE-02 | 报价有效期、逐币种精确加总、维持决定记录 | 实际报价／收费规则、预算批准、付款／弃权授权 |

以上每行对应同名 `AC-能力ID` 的机器辅助分支。GAP-01相关逐内容支持问题及其他日期、引证与异常发现的处理须以能力契约原表为准；此技能不另造完整GAP台账。DG-01/02/14/20所需支持与SEP事实可交接，但**本模块测试不等于完整DG门禁通过**。

## 状态与失败

- `needs_review`：已完成结构计算，仍需专业审阅；不是法律或官方通过。
- `needs_evidence`：保留任务产物及具体证据缺口。`unknown` 与 `failed` 用于提交尝试结果，均禁止本模块重试。
- `partial`：全景统计有来源、日期或同族缺口；`checked` 仅表示当前统计运算已完成。
- `not_applicable`：必须由调用者提供明确理由和证据；不自动推定不适用。
- `invalidated`：旧输入摘要与当前不同，不继承旧签核。
- `blocked`：PROC-05实际文本残留待确认，或可选有限复核发现文本、版本、已声明关系问题；工作稿保留供修订，不是法律结论或整个案件无法继续。
- `ContractError`：结构、枚举、悬空引用、重复ID、缺时区或不支持能力等错误；不吞掉当成正常零结果。
- 所有结果保留 `professional_review=not_performed`、`official_status=not_asserted`、`external_action=not_performed`。

## 验证方式

在项目根目录：

```powershell
python -m unittest evals.test_procedure evals.test_procedure_delivery evals.test_fidelity -v
python -m py_compile tools/procedure.py evals/test_procedure.py evals/test_procedure_delivery.py
```

合成测试覆盖19能力基础调用、异常/未知、不适用、输入版本变化，以及对应AC的辅助预期；另核实际候选缺失、保留关系、正确保义表达、原文/候选版本、真实正文绑定及接入DOCX后的内容。上述命令用于完整源仓库，开发测试不随运行包分发。不能据此声称真实官方通知已处理、当前规则已核验、身份已认证、法律意见已通过或外发已被技术门禁覆盖。专业审阅、真实外部服务、各法域规则组合、独立宿主安装／支持、正式提交和付款均未执行。
