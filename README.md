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
  "max_reviews": 12,
  "temperature": 0.2
}
```

如需本地发送邮件，设置 SMTP 环境变量后运行：

```bash
python3 literature_digest_agent.py --config config.labor_development_econ.json --output-dir outputs_labor_dev_econ --send-email
```

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
- 定时：GitHub Actions 每周一北京时间 08:00 自动运行

## GitHub Actions 定时邮件

仓库内置 `.github/workflows/weekly_digest.yml`。它会：

1. 每周一北京时间 08:00 自动运行，也支持手动 `workflow_dispatch`。
2. 使用 `config.labor_development_econ.json` 检索并生成报告。
3. 如果配置了 SMTP secrets，就发送邮件。
4. 无论是否发邮件，都会把 `outputs/` 上传为 workflow artifact。

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中添加这些 secrets：

- `OPENAI_API_KEY`：可选；不填则跳过 LLM review，只保留摘要速览
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
