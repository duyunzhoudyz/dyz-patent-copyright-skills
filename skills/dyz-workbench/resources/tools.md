# 共享工具、完整包与合成预览

安装/调用CLI、LIFE-04版本记录、固定预览或披露演练时读取对应章节；纯任务问诊无需加载代码示例。所有命令以包根为工作目录。 返回[技能入口](../SKILL.md)。

按任务定位：复制见“本地完整包”，只读校验、加载与中断接续见[完整包使用](package-use.md)；准备载荷见“共享输入与输出”；变更/覆盖记录见“LIFE-04版本影响与覆盖表”；生成HTML见“固定候选预览”；审批替身见“持久披露演练”。先读本页“合成工具的适用与责任”，再读所需章节，不默认执行所有示例。

## 合成工具的适用与责任

适用于 CORE-01—07、REVIEW-07、LIFE-01/03/04 的本地合成任务；统一入口同时发现专利、软件版权、技术标准模块。任务关联 WP-01/02/04/10，验证引用 AC-CORE-01—07、AC-REVIEW-07、AC-LIFE-01/03/04 和 DG-01—20。编号可调用不等于全部专业能力已经验证。

共享层不作权属、申请支持、期限、SEP、FTO、登记、标准批准或认证判断。联合语义、逐内容与组合、第三方权利、目标地区和申请事实由专业人员负责；本工具只验证**合成审核记录**是否完整、匹配且有效。合成角色注册表不是身份认证，哈希不是法律签章。

不适用：真实未公开技术、客户源码、身份材料、受限标准，或实际发送、上传、邮件、外部模型、正式提交、签署、付款、发布。`--synthetic` 是使用者对测试输入的声明，不证明宿主离线、不自动核实材料来源，不允许通过声明把真实材料变为合成材料。

## 安装与运行

运行环境：Python 3.11，只有标准库，无pip依赖、无账户、无网络服务。保留六技能及其引用资源、**整个 `tools/` 包**、实际`references/`和根目录的 `LICENSE`、`COMMERCIAL-LICENSE.md`、`THIRD-PARTY-NOTICES.md`，优先使用下述完整白名单包；不能仅复制SKILL.md或依赖忽略的上游研究目录。只复制本技能目录、工具和许可不足以保留同级专业路由。四业务模块缺失时 `list` 如实标为 `unavailable`，不创建占位实现。

### 本地完整包

从开发仓库或已有完整包根运行，目标父目录必须存在，目标本身必须不存在（即使空目录也拒绝）：

```powershell
python -m tools.bundle --destination D:/dyz-local-bundle
Set-Location D:/dyz-local-bundle
python -m tools list
```

本命令只进行本地复制，不安装到系统、不注册宿主、不发布。固定逐文件白名单维护于 `tools/bundle.py` 的 `BUNDLE_FILES`；包中 `bundle-manifest.json` 列出该版本全部源的相对路径、字节数与SHA-256，数量以实际清单为准。清单不包含自身哈希，不是签名、身份认证或来源真实性证明。新增资源必须显式更新白名单并回归，不能仅按后缀自动纳入。

已有包可用`python -B -m tools.bundle --verify D:/dyz-local-bundle`只读检查，`-B`避免解释器写字节码缓存；另给`--manifest-sha256`及包外可信构建时保留的清单哈希，才能核对该外部字节依据。不带此参数只证明清单内部一致，文件与清单被一起改写可能仍匹配。校验先核固定同版路径清单，再读取列入源，不执行被核业务源码或枚举未列文件。具体命令、拒绝恢复、宿主加载和续接见[完整包使用](package-use.md)。

不包含 `.references/` 上游快照、private、outputs、tmp、.git、.breezell、缓存、evals、统一施工进度台账或未列入的凭据文件；不跟随源路径、目标及父路径中的符号链接、Windows目录链接/其他reparse point。逐文件白名单不能识别已入选源码中人为写入的秘密；复制前仍须维护者检查源码及许可。缺源文件、非法/链接路径或已有目标退出2并输出 `bundle_rejected`；I/O失败退出3并输出 `bundle_io_failed`；成功仅输出 `bundle_created`。先在目标父目录私有暂存，再独占新建目标；失败只清理本次自建内容，不删除其他既有文件。源与目标父目录必须由调用者保护不受并发替换，本命令不是恶意进程隔离或原子发布系统。

根README和本次范围内设计/规范已同步为已有可运行本地合成辅助；83项catalog仍均为synthetic_helper_only，不解释为83项完整专业支持。每个模块的状态及专业限制仍有效。施工进度仅在开发仓库docs/implementation-progress.md维护，该台账不纳入本地包，不是包内运行依赖。

在该安装根目录运行：

```powershell
python -m tools list
python -m tools run CORE-02 --synthetic --root . --input skills/dyz-workbench/resources/example.json --output synthetic-contributions.json
python -m tools demo --synthetic --root . --output synthetic-demo.json
```

示例JSON位于本技能的 `resources/example.json`。CORE-02返回两份冲突贡献事实，`status=needs_evidence`、`ownership=undetermined`，不会选定权利人。`demo` 实际创建临时TXT及SQLite journal，冻结原始字节、记录必需合成角色签核、执行内建本地收件替身一次并保存同版本回执；结果 `execution.state=synthetic_confirmed`、`attempts=1`，`external_action=not_performed`、`official_status=not_asserted`。临时材料和数据库退出前删除，仅保留指定结果文件。

结果文件必须尚不存在，父目录必须存在。输入与输出路径相对于 `--root`；拒绝绝对路径、父目录跳转、盘符/ADS及根外符号链接。CLI将 `--root` 作为唯一文件授权根，payload中的 `root` / `authorized_root` 也只能指向该根或其子目录，相对业务根基于 `--root` 解析；不允许借输入JSON扩大读取或journal写入范围。入口拒绝重复JSON键和非有限数。此策略不隔离其他进程，直接Python API的根目录仍由调用者独立授权。不覆盖源文件。`run`、`demo` 和 `preview` 在读取输入前检查 `--synthetic`。终端只输出 `result_written` 或固定错误代码，不打印材料。`list` 只打印能力ID/模块/支持状态。

退出码：0表示确定性任务完成并写出结果，不表示专业审核通过；2表示输入/契约拒绝，3表示本地I/O失败。文件失败或业务阻断不能当作未命中或专业通过。输入可携带敏感值时，错误终端不会复述它；本入口仍不授权处理真实敏感材料。

## 共享输入与输出

`run <ID> --input <JSON>` 直接接收业务payload，不包裹另一层 `payload`，不补造权限、适配、证据或签核。业务结果保持自身字段，附加 `mode=synthetic`、`host_egress=not_controlled`。专业模块各自维护契约；软件版权的完整 `context` 原样透传，标准保留project_id/version/四轴adaptation，专利保留sensitivity及四轴adaptation。

| 能力 | 必需输入 | 实际输出／边界 |
| --- | --- | --- |
| CORE-01 | project_id、requests（business/goal/owner/adaptation）、evidence_ids | 三业务独立任务状态和共享证据关联，不自动启动业务 |
| CORE-02 | facts：subject/claim/evidence_id | 保留冲突、权属undetermined；样例可直接运行 |
| CORE-03 | root/path、source(id/version/origin/level)、locator、context、extraction_status | 原始字节哈希及稳定证据ID；不做OCR，missing_pages等状态如实保留 |
| CORE-04 | root、journal相对路径、operation、arguments | 持久合成审批—执行—回执—事件；见下表 |
| CORE-05 | rules、adaptation、as_of带时区 | 按声明的适用范围和生效区间选择，不自动核验法规真实性 |
| CORE-06 | ledger（可选）、changes(record_id/payload/dependencies)、reviews | core.VersionLedger版本与依赖失效，恢复时核对历史哈希、序号、依赖图及审核绑定；拒绝不一致记录，保留合法失效历史；不等于防篡改认证 |
| CORE-07 | root、files、context；可选ledger、rendering_evidence | 固定候选manifest、sha256、原始字节base64；内部报告排除；原MD/SVG缺渲染阻断保留；可附旁证一致性摘要 |
| REVIEW-07 | candidate/request/assessment/registry/signatures/now；旁证检查时另给rendering_evidence、authorized_root、context及必要ledger | 缺签核、隐藏信息、支持、权限、渲染等具体问题；不把机器通过变专业通过 |
| LIFE-01 | event：business/event_id/owner/rule_id及实际送达/期限依据 | 明确PROC、SW-06、STD-09/11责任；缺送达日不推日期 |
| LIFE-03 | handoff(record_id/version/recipient/purpose/owner/pending/expected_hash/record)、permissions、reviewers、now | 接收权限、内容绑定和独立合成审阅记录检查；不推定保密特权 |
| LIFE-04 | combinations(capability/adaptation/dependencies/checks)、changed_dependencies；可选CORE-06导出的ledger | 直接或传递变更影响、失效依赖、任务/适配/版本绑定、逐检查缺口与83项覆盖表；外部传入检查记录不冒充本工具实跑 |

### LIFE-04版本影响与覆盖表

仍用`python -m tools run LIFE-04 --synthetic --root ROOT --input regression.json --output support.json`。输入组合的capability必须属于现有83项，adaptation为非空对象；dependencies与changed_dependencies为不重复的非空字符串数组（数组本身可以为空），checks为对象数组。不执行测试命令、不读取evidence所指文件、不连接专业或外部服务。

- 不传ledger时保留原直接依赖比较，标`dependency_verification=declared_dependencies_only`，binding为null；不能宣称已经追踪传递版本。
- 传ledger时复用CORE-06历史校验及当前版本图，检查组合直接依赖和传递上游。缺节点、历史哈希损坏等拒绝处理；来源/模型/适配器都以调用者已有record_id表示，不虚构新规则。
- 输出每个组合的`dependency_scope,dependency_bindings,dependency_versions,binding,stale_dependencies,validation_gaps`。binding绑定capability、完整adaptation和传递依赖的当前哈希与历史版本序号；内容恢复为旧字节仍是新版本，不复活旧检查。每条checks需带匹配的binding、`status=passed`和非空字符串evidence，才可标`recorded_checks_passed`。这只是调用者记录与版本一致，不是验证日志真伪、实际执行或专业支持。
- 显式changed_dependencies影响该组合，或其依赖仍失效时，保持`needs_regression`。只清空变更列表、复制新binding到旧检查不能消除失效依赖。先按CORE-06重建受影响版本，再实际重跑检查、提交新检查记录；确认本轮变更已处理后再清空对应变更清单。失败、跳过、未执行、不适用、缺证据和旧binding均不算通过。
- `support_table`逐项列出全部83个注册ID；只提供某组织的组合不会使其他组织获得支持。`combination_indexes`指向本次输入顺序，未提供组合的能力为`not_evaluated`并列入`unassessed_capabilities`；有记录仅标`recorded_combinations_only`，逐组合结果在combinations内。全部专业支持保持unverified。
- 顶层checked仅针对提供的非空组合（`assessment_scope=provided_combinations_only`），不代表全83项通过；空组合返回needs_review/combinations_missing。输出不建立第二套持久台账，当前版本与历史仍由CORE-06及用户保存的记录维护。

以下为纯内存合成记录演示，不代表实际运行了所记录的专业检查：

```python
from tools.cli import dispatch

ledger = dispatch("CORE-06", {"changes": [
    {"record_id": "rule-A", "payload": {"revision": 1}},
    {"record_id": "adapter-A", "payload": {"name": "synthetic"}, "dependencies": ["rule-A"]}
]}, synthetic=True)["artifacts"]
payload = {"ledger": ledger, "changed_dependencies": [], "combinations": [{
    "capability": "STD-04", "adaptation": {"organization": "synthetic-A"},
    "dependencies": ["adapter-A"],
    "checks": [{"status": "passed", "evidence": "synthetic-example-log"}]
}]}
first = dispatch("LIFE-04", payload, synthetic=True)
assert first["artifacts"]["combinations"][0]["status"] == "unverified"
payload["combinations"][0]["checks"][0]["binding"] = first["artifacts"]["combinations"][0]["binding"]
recorded = dispatch("LIFE-04", payload, synthetic=True)
assert recorded["status"] == "checked"
assert len(recorded["artifacts"]["unassessed_capabilities"]) == 82
payload["ledger"] = dispatch("CORE-06", {"ledger": ledger, "changes": [
    {"record_id": "rule-A", "payload": {"revision": 2}}
]}, synthetic=True)["artifacts"]
changed = dispatch("LIFE-04", payload, synthetic=True)
assert changed["artifacts"]["combinations"][0]["status"] == "needs_regression"
assert changed["external_action"] == "not_performed"
```

`context` 为 `{environment, permissions, sensitivity:"synthetic", purpose, now}`。权限条目至少包含action/purpose/recipient/decision/authority_evidence/valid_from/valid_until。读取材料要求action=local_read、recipient=local_tool。时间均须带时区；合成演练使用调用者显式提供的时间，不是可信时间戳服务。

`files` 每项含 file_id、path、version、expected_sha256、kind（external/internal_report）。external还必须有非空content_ids。内部报告只列排除ID，不读取、不进入发送字节。先计算并确认预期原始字节哈希；不同字节成为stale_source_version。所有新材料变更需重建包与重审，不能回填旧申请支持。

软件交接只导出SW-03的 `artifacts.document`；SW-02原始source、SW-03整个工件和private_audit不能当作外发正文。JSON检查按本项目结构化工件类型阻断这些误打包，不靠内容关键词作秘密识别。该检查不能识别任意改名或非结构化内部报告，仍须材料清单与完整内容审阅。`CORE-07`可带 `ledger`，文件的 `dependency_ids` 关联scope/source/masked等版本节点；先用VersionLedger检查依赖最新性，再读文件；旧scope使源材料/掩码工件失效并拒绝生成候选。manifest仅保存依赖ID/哈希，不嵌入源工件。

## 固定候选预览

新入口从已校验的 `candidate.snapshots` 取固定字节，不重新读取可变源文件：

```powershell
python -m tools preview --synthetic --root D:/authorized-synthetic-root --input preview-input.json --output preview-result.json --html-output preview.html
```

输入必需 `candidate`（CORE-07结果的 **artifacts**，不是结果信封）、清单中唯一的 `file_id`、同freeze的 `context`、显式整数 `width/height`（至少320/200）。含dependency_hashes的候选必须提供当前完整 `ledger`。两项输出都须是根内新路径，父目录存在；同路径（Windows含大小写别名）及已有目标均拒绝。先写HTML后写JSON；若HTML已创建而JSON写入失败，退出3并输出 `preview_html_retained_json_failed`，保留HTML，不声称成功。先检查已留HTML，再选两个新输出名重试，不自动删除或覆盖。

输出JSON沿CORE-07信封，artifacts含渲染器字段及 `mode=synthetic/file_id/scope`。`rendering=not_executed`，状态为needs_review或blocked；生成HTML不是浏览器观察，更不是专业通过。

下列完整例可直接在包根以Python运行；只用临时合成资料，退出自动删除，不依赖evals或开发仓库路径：

```python
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.core import canonical_bytes, sha256_bytes, strict_json_loads
from tools.disclosure import check_candidate_rendering

with TemporaryDirectory(prefix='dyz-preview-example-') as directory:
    root = Path(directory)
    now = '2026-10-31T12:00:00Z'
    permission = {'action': 'local_read', 'purpose': 'synthetic-preview', 'recipient': 'local_tool',
                  'decision': 'allow', 'authority_evidence': 'synthetic-example-only',
                  'valid_from': '2026-01-01T00:00:00Z', 'valid_until': '2027-01-01T00:00:00Z'}
    context = {'sensitivity': 'synthetic', 'environment': {}, 'permissions': [permission],
               'purpose': 'synthetic-preview', 'now': now}
    source = '# 合成预览\n\n当前示例未执行浏览器，未收集截图。\n'.encode('utf-8')
    (root / 'sample.md').write_bytes(source)
    freeze_input = {'root': str(root), 'context': context, 'files': [
        {'file_id': 'f1', 'path': 'sample.md', 'version': '1', 'kind': 'external',
         'expected_sha256': sha256_bytes(source), 'content_ids': ['c1']}]}
    (root / 'freeze-input.json').write_bytes(canonical_bytes(freeze_input))
    def invoke(*args):
        result = subprocess.run([sys.executable, '-E', '-s', '-S', '-m', 'tools', *args],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == 'result_written\n'
    invoke('run', 'CORE-07', '--synthetic', '--root', directory,
           '--input', 'freeze-input.json', '--output', 'candidate-result.json')
    candidate_result = strict_json_loads((root / 'candidate-result.json').read_text(encoding='utf-8'))
    assert candidate_result['status'] == 'blocked'
    candidate = candidate_result['artifacts']
    preview_input = {'candidate': candidate, 'file_id': 'f1', 'context': context,
                     'width': 1280, 'height': 800}
    (root / 'preview-input.json').write_bytes(canonical_bytes(preview_input))
    invoke('preview', '--synthetic', '--root', directory, '--input', 'preview-input.json',
           '--output', 'preview-result.json', '--html-output', 'preview.html')
    preview = strict_json_loads((root / 'preview-result.json').read_text(encoding='utf-8'))['artifacts']
    assert preview['rendering'] == 'not_executed'
    assert sha256_bytes((root / 'preview.html').read_bytes()) == preview['rendered_artifact_hash']
    scope = preview['scope']
    record = {key: preview[key] for key in ('source_name', 'source_sha256', 'manifest_hash',
              'renderer', 'renderer_version', 'rendered_artifact_hash')}
    observation = {'status': 'not_checked', 'issues': ['not_executed'], 'scope': scope,
                   'notes': '合成示例：未执行浏览器或视觉检查。'}
    record.update(status='blocked', checked_at=now, scope=scope,
                  reviewer={'id': 'synthetic-example', 'kind': 'synthetic'},
                  evidence={'executed': False, 'browser': {}, 'artifacts': [],
                            'dom': observation, 'visual': observation})
    (root / 'record.json').write_bytes(canonical_bytes(record))
    evidence = {'f1': {'record_path': 'record.json', 'artifact_path': 'preview.html',
                       'evidence_paths': {}, 'required_scope': scope}}
    checked = check_candidate_rendering(candidate, evidence, authorized_root=root,
                                        context=context, now=now)
    assert checked['f1']['status'] == 'blocked'
    assert 'screen_screenshot_required' in checked['f1']['issues']
    print('preview_created; rendering not_executed; candidate/evidence blocked; no screenshot')
```

`rendering_evidence` 按file_id映射 `{record_path, artifact_path, evidence_paths, required_scope}`；record_path指严格JSON记录文件，artifact_path指本次HTML，evidence_paths是证据ID到根内文件相对路径的映射，required_scope由审查要求独立给定。记录字段及真实截图/DOM/视觉观察步骤见 [渲染技能](../../dyz-rendering/resources/tools.md)。示例没有真实截图，不能把not_checked改成passed冒充执行。取得真实PNG后须在record.evidence.artifacts登记对应id/kind=screenshot_png/sha256，并保留实际观察范围。

读取旁证前先验证授权、当前依赖及完整快照，再预检全部路径。拒绝根外/链接路径、未知file_id、证据ID缺失/多余/重复、旧源/包/HTML/renderer/scope、未来时间和失败观察；缺文件返回该文件blocked/rendering_evidence_unreadable。record使用strict_json_loads，重复键、NaN、非有限溢出都拒绝。`consistent`仅表示字节和声明一致，不认证身份、截图真实性、专业审批、隐藏信息或联合语义。未提供旁证时原输出形状不变；MD/SVG既有rendering_not_checked仍保留。

CORE-07的旁证摘要不是可复用签核。加载带摘要的candidate须显式提交原旁证重新检查，否则REVIEW-07/journal返回rendering_evidence_recheck_required；不允许只复验部分file_id丢掉旧失败。journal不自动从摘要读取文件，也不会因摘要新增发布权限。

## 持久披露演练

`CORE-04` 的 `journal` 是相对root的SQLite持久工作文件，与不可覆盖的JSON结果文件不同：journal按状态操作更新且保留历史。数据库必须用于合成资料；不接入数据库面板，不是加密、防篡改或真实审签系统。要跨多次CLI调用保留状态，请使用同一journal路径与release_id。

| operation | arguments | 行为 |
| --- | --- | --- |
| create | candidate、request、assessment、registry | 固定快照并返回binding；重复release拒绝，不覆盖原记录 |
| sign | release_id、role、actor_id、evidence、binding、now | 验证合成角色/范围/有效期，绑定整个请求、包、规则、申请事实及权限；机器不代签 |
| review | release_id、now | 返回候选清单及所有缺口；不自动补签核 |
| execute | release_id、current、now、outcome（可选） | 默认confirmed；也可timeout/not_sent/crash_before_transport模拟故障；只内建SQLite收件替身 |
| receipt | execution_id | 查询本地替身收件回执，不是外部服务查询 |
| verify_receipt | release_id、receipt、evidence、now | 与替身原始回执及execution_id/manifest/对象/binding逐字节对应，错回执拒绝 |
| invalidate | release_id、current、now | 当前版本变化持久失效；不覆盖旧对象，恢复原值不会自动恢复签核 |
| revoke | release_id、evidence、now | 保守停止该release；不是实际平台撤回 |
| incident | release_id、facts、now | 保全记录，停止同项目既有与后续release；不删除证据，不声称恢复新颖性 |
| status | release_id | 审批、执行、尝试数、官方状态分别呈现 |

`current` **必须含** `{manifest_hash,request,assessment,registry}`。包有dependency_ids时还必须提交与全部候选文件依赖对应的 `dependency_hashes`；缺失或变化会使审批失效。它代表调用者提供的最新合成事实，不是本工具联网发现的最新事实。新收件人、动作、用途、渠道、访问设置、规则、申请事实、材料权限或角色权限任一变化都会失效。包固定后不重读源文件；源文件后来被替换也只可能发送旧的、已签核固定字节，不发送新内容。若请求要发送新版，须提供新版manifest_hash并新建审批。

`request`：release_id/project_id/businesses/purpose/action/recipient/channel/access/targets/valid_from/valid_until/max_uses/conditions。channel只能synthetic，max_uses只能1。action支持controlled_share/public_disclosure/service_processing/formal_submission的**合成模拟**。access必须明确audience/download/forward/archive/retention，所有值纳入binding，模型处理许可不外溢为公开许可。

`assessment`：

- strategy 为 protect、already_public 或 defensive。protect须有已核验合成application(version/status/application_id/receipt_evidence/files/date_evidence)；仅申请号不能通过。
- support对每个content_id和combination_id、每个目标地区独立记录status=confirmed、original_locator、evidence、date_evidence、application_version、document_sha256，后两项须匹配application；缺一个目标地区仍阻断。
- combinations列完整组合ID；joint_review要覆盖当前manifest_hash、file_ids、content_ids、combination_ids，明确inventory_complete/status/evidence。此声明由合成技术/专业审阅承担，工具不靠关键词推导联合语义，也不自动发现遗漏的发明点。
- hidden_review绑定manifest_hash与完整内容审阅证据。rules记录version/status/evidence；policy记录status/evidence/conflicts/license_status/fto_status。只存在SEP声明不能推导许可或FTO，冲突须专业解决。
- rights逐file_id记录source_evidence/contribution_evidence/restrictions/permissions，具体action/purpose/recipient和有效期逐项核对；有意公开仍受第三方权利限制。
- already_public和defensive均需patent_not_applicable(reason/evidence)。defensive另需opportunities_lost和strategy_authority。不适用不是跳过其他权利。
- 必需技术、材料、批准人及独立审阅角色；涉软件/标准增加对应角色，protect增加patent。其他专业角色在roles_not_applicable列理由。condition_evidence按conditions记录status=satisfied与evidence；任何unresolved阻断。

`registry`：mode=synthetic、version、actors。actor含actor_id/kind=synthetic_human/roles/active/authority_evidence/valid_from/valid_until，scope限定project_id/actions/recipients/purposes。独立审阅actor不能兼任同包其他角色。此注册表仅模拟有权角色；未验证任何真人身份、资格或委托。

`incident.facts`：observed_at、known_access、evidence、containment_authority，保留原始访问时点及范围。止损仅停止本工具相关项目后续模拟；不实际撤销链接或发送通知。无自动关闭事件接口，需要独立事实核实和专业处置，不能重新审批绕过事件。

## 支持边界与变更

- TXT：仅UTF-8完整原始文本和控制字符检查。JSON：完整UTF-8结构，拒绝重复键和非有限数，所有字段作为内容。两者不表示官方排版、字段、专业语义或格式验证完成。
- Markdown：源文本及隐藏/嵌入标记初筛；未渲染，候选阻断。SVG：XML结构及活动/隐藏内容初筛；未实际渲染，候选阻断。office/PDF/图片/其他容器：未检查，阻断。不能添加一个“rendered=true”绕过。
- 渲染证据已通过上节可选旁证契约接入；绑定source_sha256、manifest_hash、renderer/version、rendered_artifact_hash、evidence、status、reviewer、checked_at、scope。机器一致性不取代真实浏览器、截图和专业审阅，不能解除MD/SVG原有阻断。
- SQLite执行预留在替身动作前提交，进程崩溃/超时保持unknown，同release不重试；错回执不能清除unknown。confirmed_not_sent也不自动重试。成功仅synthetic_confirmed，永不宣称实际发送或官方状态改变。
- 可控出口仅为此模块的**内建SQLite合成收件箱**，没有任意callable、HTTP、邮件、上传、shell命令或服务商回退接口。无法控制宿主模型、索引、遥测、用户手工操作、其他进程或有人直接修改SQLite。外部真实受控出口未实现/未验证；本工具不是离线保证。

## 验证、许可与交接

来源读取量另见[读取范围工具](reading-scope.md)：同一装配器可从被引记录生成单篇与合计文字，严格核实际Word及内部报告；不自动解释任意自然语言或认证阅读事实。三业务沿各自专业流程使用，未知／未检／未取得不合并成0或通过。

在完整开发仓库中运行（安装包不强制附带评测数据）：

```powershell
python -m unittest evals.test_bundle evals.test_cli evals.test_rendering_integration -v
python -m py_compile tools/bundle.py tools/disclosure.py tools/cli.py tools/__main__.py evals/test_bundle.py evals/test_cli.py evals/test_rendering_integration.py
```

DG覆盖的是预设合成专业判断下的正向/阻断/不明/事件分支，含磁盘SQLite跨重启和双进程竞争，不等于现实专业审阅。AC共享分支验证了独立路由、冲突保留、证据版本、规则未知、依赖失效、内部报告隔离、缺签核、期限所有权和支持表不继承。CLI测试用真实四业务模块调用并检查payload透传；替身可用不代表真实外部服务验证。

独立包不含evals，不能在包内声称执行了完整测试集。安装验收包括新包内list、CORE-02示例、共享demo、上节预览例、专利DRAFT-02、程序PROC-02、软件八项demo、标准STD-05以及不启动服务的渲染demo。Windows/Python 3.11通过不等于其他平台或宿主发现已验证；完整回归和统一进度由开发仓库台账维护。

原创内容依项目PolyForm Noncommercial 1.0.0及单独商业授权，Source Available；无第三方代码或标准正文复用。素材权利另行核实。未执行真实外发、提交、付款、签署、发布或Git暂存/提交/推送。
