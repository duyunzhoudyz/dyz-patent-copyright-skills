# 正式发布说明（v0.1.0）

当前正式发布版本为 **0.1.0**，发布标签 **v0.1.0**，发布日期 **2026-11-25**，主分支 `main`。它提供六入口的方法型工作流和有限可追溯本地工具；11 个能力域、83 项能力的目录支持等级仍全部为 `synthetic_helper_only`。正式发布仅代表本版源码与本地运行包已完成发布清单核验，不构成专业认证、法律结论或正式外发授权。

## 许可与参与

项目原创内容权利人与商业授权主体为 **杭州溥源智能科技有限公司**，采用 [PolyForm Noncommercial 1.0.0](LICENSE) 与[单独商业授权](COMMERCIAL-LICENSE.md)，属于 Source Available，仅在 LICENSE 明示范围内允许非商业使用（含无预期商业应用的个人用途及列明非商业机构按条款的使用，详见 [LICENSE](LICENSE) 原文）。商业授权联系邮箱为 `402784717@qq.com`。用户原有材料与生成结果、第三方内容分别判断；EPO 有限数据继续适用其 CC BY 4.0 说明。

欢迎外部 Issues 和 PR。按[贡献指南](CONTRIBUTING.md)提交；拟合并的原创贡献须由有权贡献者明确同意[贡献许可](CONTRIBUTOR-LICENSE.md)，保留版权并向项目授权接收主体（**杭州溥源智能科技有限公司**）授予商业再许可所需权利。未完成明确书面授权确认的外部补丁仅作讨论审阅，不先行合并。敏感报告按[安全流程](SECURITY.md)通过私密渠道 `AI4anyone(wechat)` 核实身份后提交。

## 维护者与发布元数据

唯一机器可读记录为根目录 [release.json](release.json)。四项维护者必填事实已由维护者授权确认并填齐：

| 字段 | 已确认值 | 说明 |
| --- | --- | --- |
| `license_holder` | 杭州溥源智能科技有限公司 | 有权对项目原创内容及接收贡献作出授权的真实主体 |
| `repository_url` | `https://github.com/duyunzhoudyz/dyz-patent-copyright-skills` | 公开仓库 HTTPS 地址 |
| `commercial_contact` | `402784717@qq.com` | 商业授权联系渠道 |
| `security_contact` | `AI4anyone(wechat)` | 私密安全报告渠道（公开 Issue 不满足私密要求） |

工具不把非空字符串视为第三方身份公证、权属认证或渠道可达性证明；维护者在接收外部贡献和签署商业授权时仍须按实际权属与流程核实。

## 支持环境与使用范围

本机已验证基线为 Windows 下的 Python **3.11 / 3.12 / 3.13 / 3.14** 标准库，核心工具零 pip 依赖；先前四版本基线全仓 `2,139` 项本地单元测试、`compileall` 与 `evals/release_check.py` 均已通过，发版前将对最终合并提交复跑全仓测试，最终条目数以合并后实跑记录为准。Linux（Ubuntu）与 macOS（Python 3.11–3.14）已完成跨平台代码守护与 CI 矩阵配置，但尚未在托管 GitHub Actions 中实跑，跨平台 Office / LibreOffice / Poppler 实页视觉复核仍以 Windows 实测为基线，待托管环境与目标平台另验（详见 `release.json` 中的 `verified_*` 与 `target_ci_*` 字段）。先确认 `python --version` 为 3.11–3.14。

根目录的 `README.md` 与 `skills/dyz-workbench/resources/quickstarts.md` 提供文字加载、合成演练、Word 生成与标准 MCP（`tools/mcp_server.py`）／多宿主本地安装器（`tools/install.py`）入口。六 Skill 需要保持完整共享树，不能仅复制某个 `SKILL.md`；明确文件加载、本地工具使用、MCP 接入、宿主自动发现与模型实际调用分别核验。PDF 可选，需要获准的本地工具，不自动下载或安装。

专利终稿门禁已升级至 2.1（支持有限从属继承、结构锚点、有限英文条件关系及 OA 技术修改／答复论证双轨核验），并新增起草前 IR 预检、原生 OMML 公式、三轴接入及美欧形式分析与 FTO/SEP/不建议申请策略工具；但上述仍为有限规则子集，超出子集时可被阻断，不能据此认定有无真实法律支持。保留原文和问题报告，交明确的内部工作稿及分类专业审阅；不改原文、删论证或伪造来源换通过。

可选外联数据连接器（`tools/connectors/`）默认完全离线，仅在显式披露授权（绑定主机、用途、规范化查询、分页范围与有效期）与硬预算上限下允许只读启用；未见任务盲测框架（`evals/benchmark_harness.py`）当前仅完成离线夹具协议自检。本版明确未执行项包括：托管 Linux / macOS CI 实跑、真实外部联网请求、跨平台 Office / LibreOffice / Poppler 实页视觉复核、付费模型真人盲测与人类执业人员专业签核。软件真实权利链、运行及截图、标准命题／组织要求、正式格式、专业签核、期限和真实行动均需相应证据。机器 `checked`、零 issues 或成件成功不表示专业通过。该版本不执行真实提交、自动外发、签署或付款，也不提供完整宿主或 OS 隔离。

## 源码范围与完整运行包

源码仓库保留六 Skill 及其必要资源、原创工具、获准规则与来源索引、合成夹具、可运行测试、CI、使用／许可说明，以及 `.gitignore` 白名单内的稳定规格和来源归属文档。根目录与 `docs/` 新增内容默认不进入 Git，须明确加入白名单。成套运行示例及其 Word／PDF／图像属于必要资源，与本地临时生成产物分别管理。

施工台账、迭代／修复计划、阶段评审、本地 `AGENTS.md`、整个 `竞品对比/`、`.references/`、受限标准全文、`private`、`outputs`、临时目录和 `evals/workflows` 历史模型归档保持本地。公开文档中的历史本地路径只提供来源线索，不是运行依赖，也不保证公开可下载；不得为修链接公开这些归档。可重复的技术检查使用公开测试和合成夹具，PDF／视觉及模型历史另按实际条件声明。

忽略规则不清除原件，也不证明秘密已清除；已被跟踪或强制暂存的内容仍可进入提交，推送前须核查 Git 实际清单。运行包之外的测试、CI 和维护文件按源码范围管理，不直接使用运行包白名单代替整个 Git 仓库。

完整运行包只复制 `tools/bundle.py` 的当前固定白名单（309 源）。构建和校验不提交 Git、不安装宿主、不建立远端、不公开发布。以下在可信完整根目录执行；包目标不存在且父目录存在：

```powershell
python -B -X utf8 -m tools.bundle --destination D:/dyz-review-package
$dyzManifestSha = (Get-FileHash -LiteralPath D:/dyz-review-package/bundle-manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B -X utf8 -m tools.bundle --verify D:/dyz-review-package --manifest-sha256 $dyzManifestSha
```

第一次可信构建后，把清单 SHA-256、代码来源和检查结果保存于包外；其他人下载时使用发布者提供并独立核实的依据，不能从待核包重新算“预期”证明其可信。清单内部一致不认证来源、许可或专业质量。修改包内源、说明、许可或元数据后须在新目录重建，不复用旧 pin。

## 开发仓库的发布检查

本节命令只适用于包含 `evals` 和 Git 元数据的完整源码仓库，运行包不附带开发检查器或 CI。先按贡献指南运行受影响测试，必要时使用原生 unittest 全仓入口；不要在无 main 保护的临时 Python 脚本顶层运行带 spawn 的全仓测试。

```powershell
python -B -X utf8 evals/release_check.py
python -B -X utf8 evals/release_check.py --publication
```

默认检查核对元数据结构、版本、已验证与目标平台范围、CI 工作流固定 SHA 与矩阵一致性、资源、Git 范围、Python 语法及完整包布局；它不执行模型、联网、Office 或全套测试。当 `release.json` 的 `publication_status` 为 `published_release` 时，默认 `evals/release_check.py` 也会强制校验四项维护者事实（`license_holder`、`repository_url`、`commercial_contact`、`security_contact`）全部非空且不含占位文本，无需仅靠 `--publication`；而 `--publication` 在任意发布状态下都会强制执行该四项门禁，缺项或无效时退出 2。两种检查通过都不代表已经推送远端、已打标签、已完成托管 CI 或已验证全部专业能力。

随仓 CI 定义（`.github/workflows/ci.yml`）覆盖 Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 共 12 组矩阵，执行同样三步检查及本地测试，带并发取消组，权限只读（`contents: read`），不带发布凭证（`persist-credentials: false`），不自动合并或发版。可选 PDF 工具未安装的 skip 需保留；CI 定义本身不证明托管环境、Linux / macOS 或真实 PDF／视觉已经通过。托管 Linux / macOS CI 尚未实跑，须在具体仓库配置和贡献权限条件下另核。

本版最终本地结果与包外 pin 由维护者本地台账记录，该台账不随源码分发；本页不嵌入自身包清单 hash，避免循环变化。推送远端、创建 Release 和打标签均为独立动作，须在维护者具体授权下执行。
