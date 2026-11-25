# 变更记录

## 0.1.0a1 — 未发布候选（2026-11-16整理）

拟发布标签为v0.1.0-alpha.1。本节记录首版整理范围，不表示已经提交、打标签或公开发布。

### 已有能力

- 六个共享完整目录的Skill入口：专利、程序与权利、软件版权、技术标准、渲染核稿及共享工作台。
- 原始支持与事实关系、软件材料及版本、标准五文书、文件装配和回查等有限本地辅助；83项目录入口仍为synthetic_helper_only。
- 纯 Python 标准库工具（已从初始 Python 3.11 基线扩展至兼容 Python 3.11—3.14）、合成用例、异常及版本失效检查、白名单完整包与包外清单哈希校验。

### 首版整理与阶段 A—F 短板迭代（2026-11-16 至 2026-11-25）

- **跨平台与标准 MCP / 多宿主接入（阶段 A）**：解除 Windows-only / Python 3.11 硬限制，完成 Python 3.11—3.14 标准库兼容与 POSIX 路径守护；新增纯标准库 JSON-RPC 2.0 MCP `stdio` 服务端（`tools/mcp_server.py`）、不写全局配置的多宿主本地安装器（`tools/install.py`）与通用宿主能力探针；CI 工作流（`.github/workflows/ci.yml`）配置为 Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 共 12 组矩阵并加并发取消控制，`release.json` 明确区分本机已实测基线（Windows Python 3.11 / 3.13 / 3.14）与待托管 CI 目标矩阵。
- **专利核心壁垒升级（阶段 B）**：新增起草前权项-事实中间表示（`tools/patent_ir.py`）、门禁 2.1（从属继承链、结构锚点、有限英文技术关系与 OA 技术修改／答复论证双轨核验 `tools/patent_gate.py`）、三轴材料接入（`tools/patent_intake.py`）以及纯标准库原生 Word OMML 数学公式生成与回读（`tools/omml.py`）。
- **低摩擦体验、软件与标准成件升级（阶段 D）**：扩展多语言技术栈与中英 README 候选发现、三批次集中采集（`software_intake.collect_batch`）、PNG 辅助块清洗与截图清单元校验（`tools/media_prep.py`）、标准 v3 排版配置（DOCX 侧支持原生 OMML 公式）、外部合规模板声明式映射器（`tools/template_mapper.py`）、六维审稿与循环定义检测、术语标准示范、CLI `help` 子命令及 3 分钟快速上手剧本。
- **可选外联只读连接器（阶段 C）**：新增默认离线、带硬预算上限与来源证据封装的 USPTO ODP / EPO OPS / 外部 MCP / SAMR / ISO 只读策略适配层（`tools/connectors/`）。
- **美欧法域、程序策略与多模态视觉台账（阶段 E）**：新增 US（112/101）与 EP（Rule 43(1)/Art. 123(2)）专项形式分析器（`tools/jurisdiction_analyzers.py`）、不建议申请分流 / FTO 四轨矩阵 / SEP 交接包工具（`tools/procedure_strategy.py`）与多模态视觉覆盖台账（`tools/visual_ledger.py`）。
- **评测与商业透明度（阶段 F）**：新增开发仓未见任务防泄漏与盲测对照框架（`evals/benchmark_harness.py`）、专业人员试审包与连续三案升级门控（`tools/trial_pack.py`），并在 `COMMERCIAL-LICENSE.md` 补充常见商用/非商用场景速览。
- **首版发布与贡献基础**：保留 6 Skill 原始身份、11 域 83 项 `synthetic_helper_only` 目录及历史包布局 pin，完整白名单更新为 309 源；真实授权主体、商业联系与私密安全联系渠道保持 `null` 待维护者填写。

### 已知限制

- 专利门禁 2.1 与美欧形式分析仍属有限规则子集，不替代执业代理师、律师或审查员的实质判断；内部工作稿不等于最终提交稿。
- 可选连接器默认离线且未执行真实外联请求；未见任务盲测框架仅完成离线夹具自检，当前本机仅实测 Windows Python 3.11 / 3.13 / 3.14，Windows Python 3.12 与托管 Ubuntu / macOS CI、多宿主真实模型往返稳定性、跨平台 Office/PDF 实页渲染及人类专业认证尚未由本版自动完成。
- 历史测试和模型结果仅对其记录的字节及环境有效；详细施工台账仅留维护者本地。当前公开范围与限制见RELEASE.md，可重复技术检查使用源码仓库的测试与合成夹具。

完整的试用范围、发布前待填信息与构建方法见[发布说明](RELEASE.md)。
