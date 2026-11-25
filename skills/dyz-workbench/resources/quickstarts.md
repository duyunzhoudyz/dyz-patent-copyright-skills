# 3 分钟开箱实操演练（专利 / 软件版权 / 技术标准 + MCP）

以下演练适用于 `0.1.1` 正式发布版（标签 `v0.1.1`，发布日期 `2026-11-25`），均使用纯 Python 标准库（纯标准库本地工具与自动化单测已在托管 GitHub Actions Windows / Linux (Ubuntu) / macOS × Python `3.11 / 3.12 / 3.13 / 3.14` 共 12 / 12 组矩阵实测通过：合并态 `main@697d8a2` 本机 Windows Python `3.14.6` 全仓 `2,145 / 2,145` 通过，托管 CI [run 45592934144](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/runs/45592934144) 12 / 12 全绿，Linux / macOS 保留 4 项预期平台跳过；`v0.1.1` 发版合并前会复跑全量测试；跨平台 Office / LibreOffice / Poppler 实页视觉与分页复核、真实外联、真实模型多轮稳定性与执业签核仍未执行），**在源码仓库与独立 309 源本地运行包内均可直接执行**，零外部依赖、零联网、不改全局宿主配置；产物均为内部候选（`needs_review`），不替代专业签核。

> 提示：演练产生的临时输出目录请及时清理或写入工作区外的独立新目录，避免污染已校验的本地包根。

## 演练 1：专利——终稿门禁拦截条件方向反转 + 合成 Word 审阅包回读

```powershell
# 1. 查看能力目录与 CLI 帮助
python -B -X utf8 -m tools help
python -B -X utf8 -m tools list

# 2. 体验专利门禁 2.1：拦截“只有…才 → 一旦…就”逻辑反转（纯标准库单行直跑）
python -B -X utf8 -c "from tools import patent_gate; from tools.core import sha256_bytes; s='只有记录已写入，才允许确认。'; orig=[{'id':'O1','version':'1','role':'original','text':s,'sha256':sha256_bytes(s.encode())}]; print('ok:', patent_gate.audit_final_text({'claims':s}, orig)['status'], 'bad:', patent_gate.audit_final_text({'claims':'一旦记录已写入，就允许确认。'}, orig)['status'])"

# 3. 生成并回读合成专利 Word 审阅包（输出目录须事先不存在，演练后可删除 quickstart-patent）
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output quickstart-patent
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output quickstart-patent --verify
```

## 演练 2：软件版权——合成全链演练（SW-01 至 SW-08）

```powershell
# 通过 runpy 从仓库或独立运行包根目录执行软件版权合成示范（确保包根位于 sys.path）
python -B -X utf8 -c "import runpy; runpy.run_path('skills/dyz-software/demo.py', run_name='__main__')"
```

## 演练 3：技术标准与 MCP / 多宿主本地接入

```powershell
# 1. 运行标准边界验证参考模型示范（全部使用包内合成向量）
python -B -X utf8 skills/dyz-standards/resources/river-demo/model.py skills/dyz-standards/resources/river-demo/vectors.json

# 2. 预览多宿主本地安装计划并打印 MCP 客户端配置片段（不改动全局宿主配置）
python -B -X utf8 -m tools.install --target ./dyz-installed-preview --host claude-code --plan
python -B -X utf8 -m tools.mcp_server --print-config --host claude-code
```

> 详细边界与完整包校验见 [package-use.md](package-use.md) 与 [host-bridge.md](host-bridge.md)。
