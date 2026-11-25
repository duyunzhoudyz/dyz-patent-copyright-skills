# 变更记录

## 0.1.1 — 维护正式版（2026-11-25）

维护正式发布标签为 **`v0.1.1`**，发布日期为 **`2026-11-25`**，主分支为 `main`。本版聚焦跨平台确定性修复、托管 GitHub Actions CI 12 组全绿验证及双语文档体验升级；11 个能力域、83 项能力目录的支持等级仍全部维持 `synthetic_helper_only`，6 个 Skill 入口与 309 源本地运行包白名单保持不变。

### 跨平台修复与 CI 全绿验证

- **跨平台 DOCX 确定性修复**：在 `tools/documents.py`（`_zip_docx`）中显式固定 `create_system = 0` 与 `external_attr = 0o600 << 16`，消除 Linux / macOS 与 Windows 生成 DOCX 时 ZIP 中央目录元数据的平台差异，保持既有黄金 SHA-256 零修改。
- **macOS 系统根符号链接兼容修复**：在 `tools/standard_pdf.py` 的 `_Access.pin` 中复用 `is_macos_system_root_symlink`，并在项目根与案例根独立性校验中以 `resolve` 补强判重，兼容 macOS 系统根符号链接的同时，继续严格拒绝包内真实符号链接、重解析点与硬链接。
- **跨平台回归测试与托管 CI 12 / 12 全绿验证**：补充跨平台 DOCX ZIP 字节、字段与 macOS 系统根符号链接回归测试。合并态 `main@697d8a2` 在本机 Windows（Python `3.14.6`）全仓 **`2,145 / 2,145`** 项单元测试通过（0 失败、0 错误、0 跳过），`compileall`、`validate_readme_pair.py` 与 `evals/release_check.py --publication` 均通过（此前 Windows Python `3.11 / 3.12 / 3.13 / 3.14` 本机基线均已验证）；同提交于 `2026-11-25` 在托管 GitHub Actions（[run 45592934144](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/runs/45592934144)）的 `windows-latest` / `ubuntu-latest` / `macos-latest` × Python `3.11 / 3.12 / 3.13 / 3.14` 共 **12 / 12 全部通过**（Linux / macOS 上保留 4 项预期平台跳过：2 项 Windows junction、1 项 Windows 大小写碰撞、1 项可选外部 PDF 工具测试）。`release.json` 同步升级 `verified_platforms` 与 `supported_platforms` 为 `["Windows", "Linux", "macOS"]`（纯标准库本地工具与自动化单测范围）；`v0.1.1` 发版合并前会复跑全量测试。

### 双语 README 与发布文档优化

- **双语 README 全面重写与体验优化**：重写 `README.md` 与 `README_EN.md`，突出 6 个 Skill 与零依赖 Python 本地工具解决的实际痛点与使用方式，移除空白的第三方星标/贡献者展示图与零信息量徽章，并在 CI 全绿后恢复 GitHub Actions CI 状态徽章。
- **发布文档同步至 `v0.1.1`**：同步更新 `RELEASE.md`、`SECURITY.md`、`COMMERCIAL-LICENSE.md` 及 `skills/dyz-workbench/resources/` 下运行包资源说明的版本号与跨平台 CI 实测证据，保持 `release.json` 四项维护者事实、`LICENSE` 原文权利边界及双语同步校验一致。

### 未变边界与明确未执行项

- 11 域 83 项能力目录支持等级维持 `synthetic_helper_only`，6 个 Skill 入口、10 项 `HostToolBridge` 接口、309 源本地运行包白名单（对应 415 源码候选）及四项维护者事实保持不变。
- 明确未执行项仍包括：真实外部联网请求（`tools/connectors/` 默认离线，仅在显式披露授权与硬预算上限下允许只读外联）、跨平台 Office / LibreOffice / Poppler 实页视觉与分页复核、付费模型真人盲测（`evals/benchmark_harness.py` 仅完成离线夹具协议自检）以及人类执业人员专业签核；多宿主真实模型多轮往返稳定性仍须按具体环境另验。

## 0.1.0 — 正式发布（2026-11-25）

正式发布标签为 **`v0.1.0`**，发布日期为 **`2026-11-25`**，主分支为 `main`。本节记录 `0.1.0` 正式发布的全部收敛变更、阶段能力与已知限制；11 个能力域、83 项能力目录的支持等级仍全部维持 `synthetic_helper_only`。

### 正式发布收敛与核心更新

- **维护者发布元数据补齐**：在根目录 `release.json` 填齐全部四项真实事实：`license_holder`（杭州溥源智能科技有限公司）、`repository_url`（`https://github.com/duyunzhoudyz/dyz-patent-copyright-skills`）、`commercial_contact`（`402784717@qq.com`）与 `security_contact`（`AI4anyone(wechat)`），并由 `evals/release_check.py` 在 `published_release` 状态与 `--publication` 模式下双重强制门禁校验。
- **多轮异构对抗审查收敛**：围绕路径穿越、符号链接/硬链接防护、ZIP/DOCX/PNG 结构校验、JSON-RPC 握手与帧边界、CI 工作流结构审计及跨平台差异完成多轮独立对抗审查并逐项修复收敛。
- **公共路径抽归 `tools/core.py`**：将分散在各业务工具中的公共路径校验、安全落盘与辅助校验收敛到 `tools/core.py`，减少跨模块重复逻辑与边界漂移。
- **新增并收敛 10 条本地 CLI 子命令**：在 `tools/cli.py` 统一接入 `check-patent-ir`、`build-patent-pack`、`verify-patent-pack`、`check-jurisdiction`、`check-strategy`、`check-visual-ledger`、`check-capture-manifest`、`inspect-template`、`check-trial-upgrade` 与 `connector-status`，保持输入错误脱敏与不覆盖原件约束。
- **Windows 四版本本地验证基线**：本机已验证基线同步为 Windows Python `3.11 / 3.12 / 3.13 / 3.14`；先前四版本基线全仓 `2,139` 项单元测试、`compileall` 与 `evals/release_check.py` 均已通过，发版前将对最终合并提交复跑全仓回归（最新总数以合并后实跑记录为准）。
- **全量发布文档与双语 README 同步**：同步更新 `README.md`、`README_EN.md`、`RELEASE.md`、`CHANGELOG.md`、`SECURITY.md`、`COMMERCIAL-LICENSE.md` 及运行包资源说明，保留 `LICENSE` 原文许可边界、`HostToolBridge` 与 `mcp_server` 显式启动约束，并通过双语结构与代码块校验。

### 已有能力

- 六个共享完整目录的 Skill 入口：专利、程序与权利、软件版权、技术标准、渲染核稿及共享工作台。
- 原始支持与事实关系、软件材料及版本、标准五文书、文件装配和回查等有限本地辅助；83 项目录入口仍全部为 `synthetic_helper_only`。
- 纯 Python 标准库工具（适配 Python 3.11–3.14）、合成用例、异常及版本失效检查、309 源白名单完整运行包与包外清单哈希校验。

### 阶段 A—F 短板迭代（2026-11-16 至 2026-11-25）

- **跨平台与标准 MCP / 多宿主接入（阶段 A）**：解除 Windows-only / Python 3.11 硬限制，完成 Python 3.11–3.14 标准库兼容与 POSIX 路径守护；新增纯标准库 JSON-RPC 2.0 MCP `stdio` 服务端（`tools/mcp_server.py`）、不写全局配置的多宿主本地安装器（`tools/install.py`）与通用宿主能力探针；CI 工作流（`.github/workflows/ci.yml`）配置为 Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 共 12 组矩阵并加并发取消控制，`release.json` 明确区分本机已实测基线（Windows Python 3.11 / 3.12 / 3.13 / 3.14）与待托管 CI 的 Linux / macOS 目标矩阵。
- **专利核心壁垒升级（阶段 B）**：新增起草前权项-事实中间表示（`tools/patent_ir.py`）、门禁 2.1（从属继承链、结构锚点、有限英文技术关系与 OA 技术修改／答复论证双轨核验 `tools/patent_gate.py`）、三轴材料接入（`tools/patent_intake.py`）以及纯标准库原生 Word OMML 数学公式生成与回读（`tools/omml.py`）。
- **可选外联只读连接器（阶段 C）**：新增默认离线、带硬预算上限与来源证据封装的 USPTO ODP / EPO OPS / 外部 MCP / SAMR / ISO 只读策略适配层（`tools/connectors/`）。
- **低摩擦体验、软件与标准成件升级（阶段 D）**：扩展多语言技术栈与中英 README 候选发现、三批次集中采集（`software_intake.collect_batch`）、PNG 辅助块清洗与截图清单元校验（`tools/media_prep.py`）、标准 v3 排版配置（DOCX 侧支持原生 OMML 公式）、外部合规模板声明式映射器（`tools/template_mapper.py`）、六维审稿与循环定义检测、术语标准示范、CLI `help` 子命令及 3 分钟快速上手剧本。
- **美欧法域、程序策略与多模态视觉台账（阶段 E）**：新增 US（112/101）与 EP（Rule 43(1)/Art. 123(2)）专项形式分析器（`tools/jurisdiction_analyzers.py`）、不建议申请分流 / FTO 四轨矩阵 / SEP 交接包工具（`tools/procedure_strategy.py`）与多模态视觉覆盖台账（`tools/visual_ledger.py`）。
- **评测与商业透明度（阶段 F）**：新增开发仓未见任务防泄漏与盲测对照框架（`evals/benchmark_harness.py`）、专业人员试审包与连续三案升级门控（`tools/trial_pack.py`），并在 `COMMERCIAL-LICENSE.md` 补充常见商用/非商用场景速览。
- **运行包与兼容性保护**：保留 6 Skill 原始身份、10 项 `HostToolBridge` 接口、11 域 83 项 `synthetic_helper_only` 目录及历史包布局 pin，完整本地运行包白名单更新为 309 源。

### 已知限制

- 专利门禁 2.1 与美欧形式分析仍属有限规则子集，不替代执业代理师、律师或审查员的实质判断；内部工作稿不等于最终提交稿，11 域 83 项目录仍全部为 `synthetic_helper_only`。
- 明确未执行项：托管 Linux（Ubuntu）/ macOS GitHub Actions CI 实跑、真实外部联网请求（`tools/connectors/` 默认离线）、跨平台 Office / LibreOffice / Poppler 实页视觉复核、付费模型真人盲测（`evals/benchmark_harness.py` 仅完成离线夹具自检）以及人类执业人员专业签核；多宿主真实模型往返稳定性须按具体宿主与模型另验。
- 历史测试和模型结果仅对其记录的字节及环境有效；详细施工台账仅留维护者本地。当前公开范围与限制见 [RELEASE.md](RELEASE.md)，可重复技术检查使用源码仓库的测试与合成夹具。

完整的发布范围、维护者元数据与构建方法见[发布说明](RELEASE.md)。
