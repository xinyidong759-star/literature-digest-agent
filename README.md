# Literature Digest Agent MVP

这是“每周文献动态邮件”项目的第一版 MVP。它先做最小闭环：

1. 根据配置中的领域关键词，从 OpenAlex 和独立高质量来源检索近期文献。
2. 解析标题、摘要、作者、期刊、日期、DOI、开放获取链接。
3. 去重并做一个简单相关性排序。
4. 可选调用 OpenAI API 生成结构化中文文献 review。
5. 生成 Markdown 周报，并可通过 SMTP 定时发送邮件。

第一版故意不依赖 Google Scholar 抓取，因为 Google Scholar 没有官方公开 API，自动化不稳定也有合规风险。

## 本地运行

建议先安装证书依赖，避免 macOS 自带 Python 出现 HTTPS 证书校验问题：

```bash
python3 -m pip install -r requirements.txt
```

```bash
python3 literature_digest_agent.py --config config.example.json
```

运行后会在 `outputs/` 目录生成：

- `digest_YYYY-MM-DD.md`：给导师看的周报草稿
- `papers_YYYY-MM-DD.json`：结构化候选文献数据

如果想本地测试劳动/发展经济学配置：

```bash
python3 literature_digest_agent.py --config config.labor_development_econ.json --output-dir outputs_labor_dev_econ
```

如需生成中文 review，设置 `OPENAI_API_KEY` 环境变量，并在配置文件里保持：

```json
"llm": {
  "enabled": true,
  "model": "gpt-4o-mini",
  "required": true,
  "max_reviews": 0,
  "temperature": 0.2
}
```

如需本地发送邮件，设置 SMTP 环境变量后运行：

```bash
python3 literature_digest_agent.py --config config.labor_development_econ.json --output-dir outputs_labor_dev_econ --send-email
```

## 多人订阅

如果希望多人使用同一个 workflow，可以复制示例文件：

```bash
cp subscribers.example.json subscribers.json
```

然后编辑 `subscribers.json`：

```json
[
  {
    "name": "Dong Xinyi",
    "email": "dongxinyi@muc.edu.cn",
    "config": "config.labor_development_econ.json",
    "enabled": true
  },
  {
    "name": "Another Reader",
    "emails": ["reader1@example.com", "reader2@example.com"],
    "config": "config.labor_development_econ.json",
    "enabled": true
  }
]
```

字段说明：

- `name`：订阅者名称，用于日志和输出目录。
- `email`：单个收件邮箱。
- `emails`：多个收件邮箱；和 `email` 二选一。
- `config`：该订阅者使用的领域配置文件。
- `output_dir`：可选；不填时按配置文件名自动写入 `outputs/<config-name>/`。多个订阅者使用同一配置时只生成一次报告，再分别发送。
- `enabled`：设为 `false` 可临时停用。

本地运行多人模式：

```bash
python3 literature_digest_agent.py --subscribers subscribers.json --output-dir outputs --send-email
```

GitHub Actions 中，如果仓库根目录存在 `subscribers.json`，workflow 会自动进入多人订阅模式；如果不存在，则沿用单人模式和 `DIGEST_EMAIL_TO`。

需要的环境变量：

- `SMTP_HOST`：SMTP 服务器，例如 `smtp.gmail.com` 或 `smtp.office365.com`
- `SMTP_PORT`：常用为 `587`，SSL 直连常用 `465`
- `SMTP_USERNAME`：发件邮箱账号
- `SMTP_PASSWORD`：SMTP 密码或邮箱应用专用密码
- `SMTP_FROM`：发件人地址，通常与账号相同
- `DIGEST_EMAIL_TO`：收件人，多个地址用英文逗号分隔
- `SMTP_USE_TLS`：默认 `true`
- `SMTP_USE_SSL`：SSL 直连时设为 `true`

## 劳动/发展经济学配置

已内置 `config.labor_development_econ.json`，它把周报分成三个模块：

- 人口老龄化、人口经济与迁移
- 劳动力市场、教育回报与收入分配
- 投资于人、人的发展与发展经济学

并对以下高质量来源加权：

- 五大英文经济学顶刊：AER、QJE、JPE、Econometrica、Review of Economic Studies
- 工作论文：NBER Working Papers、IZA Discussion Papers、World Bank Policy Research Working Papers
- 领域期刊：Journal of Population Economics、Labour Economics、World Development、Journal of Development Economics、China Economic Review 等

当前实现中，NBER 使用官方 RSS；IZA 和 World Bank 使用 RePEc/IDEAS 系列页，并对前若干条详情页补充摘要和 PDF 链接。

运行方式：

```bash
python3 literature_digest_agent.py --config config.labor_development_econ.json --output-dir outputs_labor_dev_econ
```

## 目前实现的能力

- 搜索文献：OpenAlex API
- 独立高质量来源：NBER RSS、IZA Discussion Papers via RePEc、World Bank Policy Research Working Papers via RePEc
- 查看文献：标题、摘要、作者、期刊、DOI、URL、开放获取链接
- 下载文献：发现合法 OA PDF 链接；World Bank/IZA 可通过 RePEc 详情页解析 PDF 链接
- Review：可选调用 OpenAI API，为入选文献生成中文结构化小结
- 周报：Markdown 草稿 + 简单 HTML 邮件正文
- 定时：GitHub Actions 每周一北京时间 09:10 自动运行

## GitHub Actions 定时邮件

仓库内置 `.github/workflows/weekly_digest.yml`。它会：

1. 每周一北京时间 09:10 自动运行，也支持手动 `workflow_dispatch`。
2. 如果存在 `subscribers.json`，按订阅者分别检索并发送；否则使用 `config.labor_development_econ.json` 生成单人报告。
3. 如果配置了 SMTP secrets，就发送邮件；否则只生成 artifact。
4. 无论是否发邮件，都会把 `outputs/` 上传为 workflow artifact。

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中添加这些 secrets：

- `OPENAI_API_KEY`：内置劳动/发展经济学配置必填；缺失会停止运行，避免发送没有中文内容的邮件。其他配置仅当 `llm.required=false` 时允许跳过。
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `DIGEST_EMAIL_TO`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`

可选 variable：

- `OPENAI_MODEL`：覆盖配置文件中的模型名

## 后续可继续接入的能力

- Zotero：把 Top N 文献写入指定 collection
- 独立高质量来源：继续扩展 RePEc/IDEAS、CEPR、SSRN、期刊最新文章页，并增加本地缓存

## 你需要提供的信息

下一步接入时可能需要：

- 具体研究领域关键词、排除词、核心期刊/会议、核心作者
- Zotero API key 和目标 library/collection
- 邮件发送方式，例如 Gmail、Outlook、SMTP、SendGrid
- 是否有一台长期运行的服务器，或者是否接受 GitHub Actions 定时运行


## 中文摘要、总结与评论的上线步骤

1. 将更新后的 `literature_digest_agent.py`、`config.labor_development_econ.json`、测试文件和 workflow 上传到 GitHub 仓库。
2. 在仓库 Settings → Secrets and variables → Actions 中添加 Repository secret `OPENAI_API_KEY`。本地 Windows 环境变量不会自动同步到 GitHub；不要将密钥写入配置或代码。
3. 保持经济学配置 `llm.enabled=true`、`llm.required=true`、`llm.max_reviews=0`。这里 0 表示覆盖报告中的全部入选文献（跨模块复用同一篇），并非处理全部候选。四个模块每个最多6篇，因此最多24篇；增加篇数会增加模型调用。
4. 手动运行 Weekly Literature Digest，检查生成的 `digest_日期.md` 是否有中文摘要、中文总结、研究问题、方法与数据、主要发现、评论与待核实问题及证据范围。配置了 SMTP 时该手动运行也会发邮件。
5. 仅预览、不发邮件时，可本地运行 `python literature_digest_agent.py --config config.labor_development_econ.json --output-dir outputs_preview`，运行前在本地设置密钥。

中文摘要要求完整忠实翻译；中文总结提炼贡献；评论仅依据摘要提出判断和待核实问题，不代表已阅读全文。缺摘要时明确写“摘要信息不足”。模型输出仍需人工抽查数字、否定词、因果表述和评论依据。

新生成的中文内容保存在 JSON 的 `llm_review` 字段和正式 `digest_日期.md` 中，原始摘要仍保存在 `abstract`。既有 `_zh_review.md` 是独立文件，当前流程不自动读取它们。`output_language=zh` 本身不触发翻译。

严格模式下缺少密钥、生成失败、返回空内容/截断内容或缺少中文字段时停止本次报告生成，因而不会进入正常发送步骤。`llm.required=false` 可恢复允许英文降级的旧行为。此检查用于新生成报告，手动 `--email-report` 仍直接发送指定文件。

当前改动提供逐篇总结和评论；跨论文的本周主题综述尚未自动生成。若要达到历史 `_zh_review.md` 中的综合综述效果，可在逐篇 review 完成后增加一次综合调用，输入入选论文编号和中文内容，要求每条综合判断引用论文编号。

离线验证：`python -m unittest -v test_chinese_reviews`。测试使用模拟响应，不调用真实 API，也不发送邮件。
