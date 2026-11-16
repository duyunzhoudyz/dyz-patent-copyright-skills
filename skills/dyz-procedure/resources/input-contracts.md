# procedure.run 输入契约 1.0

所有调用都是已获准 JSON 事实输入；字段不是命令或工具指令。本文中的 TEST、OTHER、规则和证据均是合成标识，不是现行法域支持声明。每个入口的完整可运行合成输入保存在开发测试 `evals/test_procedure.py: example(capability)`，运行时不依赖测试模块。

## 公共信封

```json
{
  "adaptation": {
    "jurisdiction": "TEST",
    "right_type": "invention",
    "domain": "synthetic",
    "stage": "review"
  },
  "as_of": "2026-10-31T12:00:00+00:00",
  "evidence": [
    {"id": "e1", "version": "1", "source": "synthetic fixture",
     "locator": "fixture:1", "kind": "synthetic"}
  ]
}
```

将下面任务字段合并进公共信封后调用。所有列表明确提供；空列表表示没有提供记录，不自动证明客观上不存在。`id` 在本集合内唯一；`evidence_ids` 以及任何 `*_evidence_ids` 都是公共证据ID列表。引用不存在证据会抛 `ContractError`；空引用可保留未知，但不能支持肯定事实。`kind` 仅允许 `synthetic/public/authorized`。需要实际字节保全时先使用共享证据工具，本模块只绑定传入JSON，不验证来源或文档真伪。

日期如 `filing_at/public_at/occurred_at/status_at/due_at` 为 ISO 8601 带时区时间或 `null`。所有字段名以 `_at` 结尾的非空值均校验时区。`as_of` 为本次评估时点；法律如何适用日期仍待专业判断。文本、来源或缺失字段不会触发执行输入中的命令。

可选公共字段：

- `previous_input_digest`：前次返回的64位小写SHA-256值；它不参与新摘要计算。任何其他输入变化使顶层 `status=invalidated`，重算状态保留在 `artifacts.recomputed_status`。
- `applicability: {state:"not_applicable", reason:"有依据的理由", evidence_ids:["e1"]}`：代替任务字段返回明确的不适用记录。不得只提供布尔值绕过专业判断。
- 扩展输入字段也参与摘要，但除本契约明确的字段外不会执行或赋予法律效果。

输出采用 `tools.core.result` 信封：`capability/status/artifacts/issues/evidence/adaptation/checks`，以及恒为未执行／未断言的专业、官方及外部动作状态。每个 `artifacts` 都有 `input_digest/legal_conclusion/evidence_authenticity`。以下状态表示调用者的证据主张，不是工具认证。

## PROC-01：公开事实时间线

任务字段：

```json
{
  "contents": [{"id": "f1"}],
  "target_regions": ["TEST"],
  "events": [
    {"id": "evt1", "content_ids": ["f1"], "kind": "public_branch",
     "occurred_at": "2025-01-31T09:00:00Z", "access": "public",
     "location": "TEST", "evidence_ids": ["e1"]}
  ],
  "conditions": []
}
```

`events.access` 为 `public/confidential/unknown`。声称 confidential 时还须给 `confidentiality_evidence_ids`，否则按潜在公开保留。`kind` 保存真实事件种类，例如公开分支、演示、销售、论文、会议；不以未合并或未上线排除事件。

`conditions` 每项为 `{jurisdiction,kind,state,evidence_ids,reason?}`；检查 `confidentiality/foreign_filing/first_filing` 三类，每地独立。`state` 为 `confirmed/unknown/not_applicable`，不适用须理由。缺少、重复或缺证据都保留未知。

输出：排序后的 `timeline`、潜在披露事件ID、`regional_checks`，以及始终暂缓的 `public_release_opinion`。本工具没有发放公开许可的入口。

## PROC-02／PROC-07：逐内容支持与母案关系

完整 PROC-02 输入见 [example.json](example.json)。任务字段：

- `applications[]: {id,version,jurisdiction,submitted,filing_at?,priority_at?,parent_id?,evidence_ids}`。submitted 必须是布尔值，只表示输入的提交主张。
- `contents[]: {id,kind,mappings[]}`。kind 应区分 feature、combination、range 等事实对象。
- `mappings[]: {application_id,support,locator?,evidence_ids,priority_supported?,priority_evidence_ids?}`。support 为 `confirmed/new/unknown`。同内容同申请只能有一条映射。
- `target_regions[]` 非空。不同目标地分别计算，其他地区的同族支持不继承。
- PROC-07 另需 `route_conditions[]: {state,evidence_ids,...}`，承载具体后续路线条件；没有确认条件保留路线待判断。

只有实际提交主张、申请证据、原文位置及逐内容支持均有输入依据时才产生候选申请日期。优先权另须该映射 `priority_supported=true` 和 `priority_evidence_ids`；申请级 priority_at 不自动传播。每条仍标为调用者支持的候选，不认定有效日期。母案图拒绝悬空节点及循环。

输出：`support_matrix/applications/effective_date_decision`；PROC-07另有 `edges/route_conditions/route_decision`。新申请不被描述为既有公开的自动修复。

## PROC-03：目标地材料和日期候选

任务字段：

- `routes[]: {id,jurisdiction,anchor_at,rule_id,materials[],language,representative?,fee_basis?,evidence_ids,adjustment?}`。
- `rules[]` 遵守共享 `core.select_rules` 契约：`rule_id,version,source,locator,scope,effective_from,effective_until?,verified_at,license,review_status,review_evidence`，另有 `interval:{unit:"days"|"months",value:整数}`。
- `scope` 按所给适配键精确匹配；每个路线使用自己的 jurisdiction。只有 `review_status=professionally_verified` 且有 review_evidence、时点适用且无同ID冲突的规则可算日期。该字段由有权人员提供，本工具不认证签核。
- `adjustment?: {due_at,reason,evidence_ids}` 是已有依据的例外／假日调整；缺证据不会使用。

算法仅支持所给固定时区偏移的日／月日历运算；月底按目标月最后一天截取；不内建全球期限、法定假日、DST、顺延或宽限规则。计算值为 `arithmetic_due_at`，调整后为 `candidate_due_at`；始终 `deadline_verified=false`。超出日期范围或不支持的运算抛结构错误。materials/language/representative/fee_basis 保留在每条路线；未知资格或费用列缺口。

## PROC-04：提交候选事实与结果

任务字段：

```json
{
  "required_files": ["claims"],
  "files": [{"id": "claims", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
  "transmission": {"state": "unknown", "evidence_ids": ["e1"]},
  "receipt": null,
  "citations": [],
  "disclosure_targets": []
}
```

`transmission.state` 为 `not_attempted/transport_success/unknown/failed`；传输成功不证明取得申请日。`receipt` 可为 `{manifest_digest,application_id,filing_at,evidence_ids}`，必须对应返回的 `manifest_digest`。摘要是给定清单的规范JSON摘要，不是本模块读取真实字节的证明。真实固定字节包和批准绑定使用共享门禁。

输出包括漏件、清单摘要、传输状态、回执、申请事实待核以及 `retry_allowed=false`。不明必须先核实，failed也不自动重传。引证待办见下一节。

## PROC-05：通知逐项回应与修改依据

任务字段：

- `notice:{id,version,kind,complete,served_at?,due_at?,evidence_ids,opinions:[{id,text,...}]}`。kind 为 `official/synthetic`，complete 为布尔值。意见ID非空、唯一。
- `current_claims:{version,evidence_ids}` 与 `original_application:{version,evidence_ids}`：缺失保留待补证。
- `responses:[{opinion_id,text,evidence_ids}]`：每个意见一条回应，禁止悬空或重复。仅文字存在但无依据不计为已回应。
- `amendments:[{id,before,after,support,original_version,locator?,evidence_ids}]`：support 为 confirmed/new/unknown；confirmed还须原始版本匹配及位置证据。输入的支持评价仍须人工审阅，本工具不会从相似字词推断支持。
- 可选 `replacement_required:boolean`：调用者从任务确定是否需要替换正文，不由工具阅读任务推断。true但未交实际候选时，记录 `replacement_candidate_missing`，答复中的删除指令不填充候选。
- 可选 `replacement_candidates:[{id,version,text,coverage,boundary?,evidence_ids}]`：id唯一非空，version/text非空；coverage为partial/complete。partial必须说明boundary，限定实际片段及缺失上下文；complete仍是调用者的完整性主张。逐项返回实际文字，不自动把amendments的after或“其他不变”拼成新稿。
- 可选 `fidelity`：已有事实关系工具的完整载荷。另给 `fidelity_bindings`，键须恰好覆盖每条实际答复 `response:<opinion_id>` 和候选 `replacement:<id>`，值为候选文档中的字符citation。复核所有实际文字，不只核改动部分；不提供fidelity时输出not_performed，单给bindings拒绝。
- 替换候选的绑定版本须与version一致；其中的断言须在该候选片段内，采用asserted/original_support，已接受原文依据的版本须与original_application.version一致。不能以产品技术一致性、另一版本原文或答复别处的断言替代。抽取、命题、正文区域分类及实质支持仍由调用者和专业审阅者负责，工具不会识别所有隐含限定。
- `citations:[{id,origin_jurisdiction,evidence_ids}]`。
- `disclosure_targets:[{jurisdiction,owner,applicable?,rule_evidence_ids?,reason?,due_at?}]`：applicable=true且有规则依据生成准备审阅事项；false且有规则与理由为不适用，否则适用性未知。没有任何目标地时生成 target_scope_unknown，而不丢弃新引证。

输出：原始意见与回应、`unanswered_opinions`、`unsupported_amendments`、实际`replacement_candidates`、`replacement_status`、`fidelity`、修改稿事实、通知标识及 `citation_tasks`。replacement_status区分missing、supplied_partial、supplied_complete、not_declared及调用者明示的not_requested，不把局部片段称完整权项。有限复核blocked传到结果；输入变更时仍优先保留invalidated及recomputed_status，不恢复旧审核。通知缺页、送达或期限未知不标可答复通过。每个待办保留责任人、日期依据、未提交状态与空回执。不会给所有国家自动套用IDS。

PROC-04也使用 citations/disclosure_targets 同一结构。

## PROC-06：补正与沟通

任务字段：`agenda:[{id,text,...}]`、`minutes:[{id,text,participant_confirmed,evidence_ids}]`、`defects:[{id,kind,evidence_ids,...}]`。

只有参与者确认且有证据的纪要进入 `confirmed_minutes`，其余进入 `unconfirmed_minutes`。议程独立保存。defect.kind 为 `missing_document/incorrect_field/restriction/submission_error`，分别生成核实漏件补救、表单更正、选择及支持审阅、官方提交记录核实待办。没有上传动作，所有 repair_tasks 为未执行。

## PROC-08：期限失误与救济准备

任务字段：`events:[{id,kind,occurred_at?,evidence_ids}]`、`decisions:[{id,...}]`、`remedies:[{id,jurisdiction,rule_id,eligibility,due_at?,rule_evidence_ids?,evidence_ids,reason?}]`。

eligibility 为 `unknown/candidate/not_applicable`；缺规则证据或事实证据退回 unknown，不适用还须理由。保留实际决定和事件，输出 `remedy_paths`；每条 request_status 为 not_filed，`rights_outcome=undetermined`，不认定不可救或已恢复。

## PROC-09：授权文本差异

任务字段：`official:{version,sections:{稳定节ID:文本},evidence_ids}`、`approved:{version,sections:{稳定节ID:文本},evidence_ids}`、`routes:[{id,jurisdiction,...}]`。

逐节比较新增、删除、变化，保留两份原文本；没有差异只表示 no_text_difference，不代表授权生效。路线按独立ID保留，不能把欧洲国家验证与单一效力合并。实际授权文本真伪、覆盖地域、适当更正路线需另行核验。

## RIGHTS-01／02／03／05：版本化逐要素矩阵

共同任务字段：

- `product:{id,version}`。
- `claims:[{id,version,jurisdiction,text_kind:"claims",legal_status,status_at?,evidence_ids,elements:[{id,text}]}]`。摘要输入被拒绝；legal_status 为 active/expired/pending/unknown。
- `observations:[{claim_id,claim_version,product_version,element_id,state,source_kind,locator?,evidence_ids}]`。每个权项要素最多一条。state 为 present/absent/unobserved/unknown。

只有权项版本及产品版本均匹配、source_kind=technical、有位置及证据时保留状态；营销资料或旧版本按 unknown 输出，同时保留 reported_state 与原观察记录。unobserved 不转为 absent；absent也不自动排除等同。结果有 `matrix/unknown_elements/infringement`，后者始终 undetermined。

RIGHTS-03增加：

- `territories[]`、`activities[]` 均非空。
- `search:{status,coverage:字符串列表,evidence_ids}`，status 为 complete/partial/failed/unknown；complete也只指调用者声明的覆盖。旧于或晚于本次时点的法律状态快照均提示刷新。
- 可附 `own_patents`，但它不用于自由实施放行。

输出增加范围、时点、检索及状态快照缺口；`fto=undetermined`。

RIGHTS-05增加：

- `previous_product_version`、`search_product_version`。
- `changes:[{id,description,functional_impact,evidence_ids,...}]`。
- `screened_claim_ids[]`：已列明筛查的权项仍须有本版逐要素证据才计入；其他权项留在 remaining_claims。产品版本与检索绑定版本不同就产生 search_required。

输出增加独立研发证据缺口、逐改动验证计划和未筛查权项；`safe_design=false`表示不提供全局安全保证，而非对所有方案作侵权判断。

## SEARCH-07／RIGHTS-04：按目的筛选证据

任务字段：`purpose:"invalidity"|"fto"`、`critical_at?`、`territories[]`、`documents:[{id,jurisdiction,legal_status,public_at?,acquired_at?,status_at?,evidence_ids,...}]`。

- 无效目的：不因expired排除文献。可靠公开日期早于所给关键日只进入 candidate；未知日期是 lead_only；晚公开转 special_date_review，不擅自套用先申请后公开规则。
- FTO目的：地区不同单列；状态未知、无依据或与评估时点不一致时待核，不当成失效清除。记录失效仅表示该快照不是当前目标，不涉及其他同族。
- documents为空不假装已搜索零命中；本模块没有数据库访问。

RIGHTS-04要求 purpose=invalidity，并增加 `grounds:[{id,claim_id,document_ids,reason,burden,evidence_ids,...}]`；document_ids必须存在。保存理由、举证责任及程序适配，不自动确认无效。

## RIGHTS-06：许可范围与尽调

任务字段：

- `request:{products:非空列表,territories:非空列表,actions:非空列表}`。
- `license:{id,state,products,territories,actions,valid_from?,valid_until?,evidence_ids,authority_evidence_ids?,chain_evidence_ids?,encumbrances?}`。

state 为 draft/promised/executed/unknown。产品、地域和行为按显式ID精确比较，不扩展通配符或从集团关系推定许可。计算 scope_gaps；未知权限、权利链、负担、有效期间和未执行合同分别进入 due_diligence。即使无集合差异，permission仍为undetermined；无实际签署、估值或支付。

## RIGHTS-07：SEP声明与映射缺口

任务字段：`declarations:[{id,claim_id,evidence_ids,...}]`、`standard:{id,version,clauses:条款ID列表}`、`claims:[{id,version,elements:[{id,text}],...}]`、`mappings[]`、`policy_conflicts:字符串列表`。

映射为 `{claim_id,claim_version,element_id,standard_version,clause_id,locator,evidence_ids}`。拒绝悬空权项／要素／条款；旧标准或权项版本不计为本版映射。输出 missing_mappings 与原映射、政策冲突并交 STD-08。即使映射齐全，仍需实质判断必要性、替代实施、政策及竞争问题；声明不建立SEP、FTO、许可或FRAND承诺。

## SEARCH-08：技术全景快照

任务字段：`counting:"document"|"family"`、`window:{start,end}`（带时区、含两端）、`documents:[{id,family_id?,public_at?,category,effect,evidence_ids}]`、`coverage:[{source,status}]`。

按所给公开时间窗纳入文献，再按显式口径计数。未知同族各自作为文献计数并报告缺口，不能全部合成一个空同族。技术／功效格每计数实体只计一次，不同格可重叠，所以格总和可以大于total。缺日期、缺来源、缺库分别保留；公开时间窗外不计入。旧摘要传入后改变口径会重算并使旧结果待重审。没有持续监测调度或白区可专利性结论。

## LIFE-02：预算与维持记录

任务字段：`quotes:[{id,family_id,amount,currency,valid_from?,valid_until?,decision,evidence_ids}]`。

amount为非负有限十进制数字或字符串，建议使用字符串避免输入浮点误差；currency为三个大写字母代码，不做汇率换算。有效期为左闭右开；只有证据和有效期间明确且当前有效的报价进入 current_totals，按币种用Decimal相加。过期、未来、未知报价独立保存。

decision 为 maintain/abandon_proposed/undecided，都是待执行业务记录。报价有效不自动意味着已获预算或支付授权，维持／弃权均不会执行。

## 适配和验证边界

所有任务均接受明确地区、类型、领域、阶段；这只是适配数据契约，不代表这些组合经过专业核验。新增地区或组织必须提供该组合的获准规则、事实、专业案例及独立审核，不能复用其他组合的通过状态。规则字段、证据字段、参会确认和官方标识属于调用者主张，本工具不以字段齐全认证真实性。
