#!/usr/bin/env python3
import argparse
import datetime as dt
import html
import http.client
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from html import unescape
from xml.etree import ElementTree


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
REPEC_BASE_URL = "https://ideas.repec.org"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def http_get_json(url, params=None, timeout=30):
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "literature-digest-agent-mvp/0.1",
            "Accept": "application/json",
        },
    )
    context = None
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} from {url}: {body[:500]}") from e
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError) as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise RuntimeError(
                    "HTTPS certificate verification failed. Try installing certifi with "
                    "`python3 -m pip install -r requirements.txt`, or use a Python "
                    "environment with an up-to-date certificate store."
                ) from e
            if attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            raise RuntimeError(f"Network error from {url}: {e}") from e


def http_get_text(url, params=None, timeout=30):
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "literature-digest-agent-mvp/0.1",
            "Accept": "text/html,application/rss+xml,application/xml,text/xml,*/*",
        },
    )
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset()
                for enc in [charset, "utf-8", "latin-1"]:
                    if not enc:
                        continue
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError) as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise RuntimeError(
                    "HTTPS certificate verification failed. Try installing certifi with "
                    "`python3 -m pip install -r requirements.txt`, or use a Python "
                    "environment with an up-to-date certificate store."
                ) from e
            if attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            raise RuntimeError(f"Network error from {url}: {e}") from e


def http_post_json(url, payload, headers=None, timeout=60):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "User-Agent": "literature-digest-agent-mvp/0.2",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} from {url}: {body[:500]}") from e
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError) as e:
            if attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            raise RuntimeError(f"Network error from {url}: {e}") from e


def clean_text(text):
    text = unescape(text or "")
    if "â" in text or "Ã" in text:
        for enc in ["cp1252", "latin-1"]:
            try:
                text = text.encode(enc).decode("utf-8")
                break
            except UnicodeError:
                pass
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def reconstruct_abstract(index):
    if not index:
        return ""
    positions = []
    for word, indexes in index.items():
        for i in indexes:
            positions.append((i, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def normalize_doi(doi):
    if not doi:
        return ""
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi


def normalize_title(title):
    title = title or ""
    title = re.sub(r"\s+", " ", title).strip().lower()
    title = re.sub(r"[^\w\s\u4e00-\u9fff]", "", title)
    return title


def author_names(work, max_authors=6):
    names = []
    for authorship in work.get("authorships", [])[:max_authors]:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    if len(work.get("authorships", [])) > max_authors:
        names.append("et al.")
    return ", ".join(names)


def source_name(work):
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    return source.get("display_name") or ""


def best_open_access_url(work):
    open_access = work.get("open_access") or {}
    if open_access.get("oa_url"):
        return open_access.get("oa_url")
    primary = work.get("primary_location") or {}
    if primary.get("landing_page_url"):
        return primary.get("landing_page_url")
    return work.get("doi") or work.get("id") or ""


def work_to_paper(work, query):
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    doi = normalize_doi(work.get("doi"))
    return {
        "title": work.get("display_name") or "",
        "authors": author_names(work),
        "source": source_name(work),
        "publication_date": work.get("publication_date") or "",
        "year": work.get("publication_year"),
        "doi": doi,
        "url": best_open_access_url(work),
        "openalex_id": work.get("id") or "",
        "cited_by_count": work.get("cited_by_count") or 0,
        "is_oa": bool((work.get("open_access") or {}).get("is_oa")),
        "oa_status": (work.get("open_access") or {}).get("oa_status") or "",
        "abstract": abstract,
        "matched_query": query,
        "module": "",
        "pdf_url": "",
        "relevance_score": 0,
        "source_quality_score": 0,
        "source_type": "openalex",
    }


def make_external_paper(title, authors="", source="", url="", abstract="", publication_date="", matched_query="", source_type="external"):
    return {
        "title": clean_text(title),
        "authors": clean_text(authors),
        "source": source,
        "publication_date": publication_date,
        "year": None,
        "doi": "",
        "url": url,
        "openalex_id": "",
        "cited_by_count": 0,
        "is_oa": True,
        "oa_status": "external",
        "abstract": clean_text(abstract),
        "matched_query": matched_query,
        "module": "",
        "pdf_url": "",
        "relevance_score": 0,
        "source_quality_score": 0,
        "source_type": source_type,
    }


def search_openalex(query, from_date, to_date, per_page, mailto="", extra_filter="", timeout=20):
    filters = [f"from_publication_date:{from_date}", f"to_publication_date:{to_date}", "type:article"]
    if extra_filter:
        filters.append(extra_filter)
    params = {
        "search": query,
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per-page": per_page,
        "select": ",".join(
            [
                "id",
                "doi",
                "display_name",
                "publication_year",
                "publication_date",
                "authorships",
                "primary_location",
                "open_access",
                "abstract_inverted_index",
                "cited_by_count",
            ]
        ),
    }
    if mailto:
        params["mailto"] = mailto
    data = http_get_json(OPENALEX_WORKS_URL, params=params, timeout=timeout)
    return [work_to_paper(work, query) for work in data.get("results", [])]


def fetch_nber_rss(source_config):
    url = source_config.get("url", "https://www.nber.org/rss/new.xml")
    source_name = source_config.get("name", "NBER Working Paper")
    limit = int(source_config.get("limit", 25))
    xml_text = http_get_text(url)
    root = ElementTree.fromstring(xml_text)
    papers = []
    for item in root.findall("./channel/item")[:limit]:
        raw_title = item.findtext("title") or ""
        title = raw_title
        authors = ""
        if " -- by " in raw_title:
            title, authors = raw_title.split(" -- by ", 1)
        link = item.findtext("link") or ""
        description = item.findtext("description") or ""
        papers.append(
            make_external_paper(
                title=title,
                authors=authors,
                source=source_name,
                url=link,
                abstract=description,
                publication_date=dt.date.today().isoformat(),
                matched_query=source_name,
                source_type="nber_rss",
            )
        )
    return papers


def parse_repec_series_items(html, source_config):
    source_name = source_config.get("name", "RePEc series")
    limit = int(source_config.get("limit", 30))
    pattern = re.compile(
        r'<LI[^>]*>\s*<B>\s*([^<]+)\s*<A HREF="([^"]+)">(.+?)</A></B><BR><I>by</I>\s*(.*?)(?=<LI|\Z)',
        re.IGNORECASE | re.DOTALL,
    )
    papers = []
    for match in pattern.finditer(html):
        number = clean_text(match.group(1))
        href = match.group(2)
        title = clean_text(match.group(3))
        authors = clean_text(match.group(4))
        url = urllib.parse.urljoin(REPEC_BASE_URL, href)
        papers.append(
            make_external_paper(
                title=title,
                authors=authors,
                source=source_name,
                url=url,
                abstract=f"{source_name} No. {number}",
                publication_date=dt.date.today().isoformat(),
                matched_query=source_name,
                source_type="repec_series",
            )
        )
        if len(papers) >= limit:
            break
    return papers


def enrich_repec_paper_detail(paper):
    html = http_get_text(paper["url"])
    abstract_match = re.search(r'<div id="abstract-body">(.*?)</div>', html, flags=re.IGNORECASE | re.DOTALL)
    if abstract_match:
        paper["abstract"] = clean_text(abstract_match.group(1))
    pdf_match = re.search(r'<B>File URL:</B>\s*<span[^>]*>(.*?)</span>', html, flags=re.IGNORECASE | re.DOTALL)
    if pdf_match:
        paper["pdf_url"] = clean_text(pdf_match.group(1))
    return paper


def fetch_repec_series(source_config):
    html = http_get_text(source_config["url"])
    papers = parse_repec_series_items(html, source_config)
    if source_config.get("fetch_details", True):
        max_details = int(source_config.get("max_detail_fetch", 20))
        for paper in papers[:max_details]:
            try:
                enrich_repec_paper_detail(paper)
            except Exception as e:
                print(f"Warning: failed to enrich RePEc paper {paper.get('url')}: {e}", file=sys.stderr)
            time.sleep(0.1)
    return papers


def fetch_independent_source(source_config):
    source_type = source_config.get("type")
    if source_type == "nber_rss":
        return fetch_nber_rss(source_config)
    if source_type == "repec_series":
        return fetch_repec_series(source_config)
    print(f"Skipping unknown independent source type: {source_type}", file=sys.stderr)
    return []


def enrich_with_unpaywall(paper, email):
    if not email or not paper.get("doi"):
        return paper
    params = {"email": email}
    try:
        data = http_get_json(UNPAYWALL_URL.format(doi=urllib.parse.quote(paper["doi"])), params=params)
    except RuntimeError:
        return paper
    best = data.get("best_oa_location") or {}
    paper["pdf_url"] = best.get("url_for_pdf") or ""
    if not paper["url"]:
        paper["url"] = best.get("url") or data.get("doi_url") or ""
    return paper


def dedupe_papers(papers):
    seen = set()
    deduped = []
    for paper in papers:
        key = paper.get("doi") or normalize_title(paper.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def merge_duplicate_papers(papers):
    merged = {}
    for paper in papers:
        key = paper.get("doi") or normalize_title(paper.get("title"))
        if not key:
            continue
        if key not in merged:
            paper["modules"] = [paper["module"]] if paper.get("module") else []
            paper["matched_queries"] = [paper["matched_query"]] if paper.get("matched_query") else []
            merged[key] = paper
            continue
        existing = merged[key]
        if paper.get("module") and paper["module"] not in existing["modules"]:
            existing["modules"].append(paper["module"])
        if paper.get("matched_query") and paper["matched_query"] not in existing["matched_queries"]:
            existing["matched_queries"].append(paper["matched_query"])
        if paper.get("publication_date", "") > existing.get("publication_date", ""):
            existing["publication_date"] = paper["publication_date"]
        if paper.get("cited_by_count", 0) > existing.get("cited_by_count", 0):
            existing["cited_by_count"] = paper["cited_by_count"]
        if not existing.get("abstract") and paper.get("abstract"):
            existing["abstract"] = paper["abstract"]
        if not existing.get("url") and paper.get("url"):
            existing["url"] = paper["url"]
    return list(merged.values())


def excluded(paper, exclude_terms):
    text = " ".join([paper.get("title", ""), paper.get("abstract", ""), paper.get("source", "")]).lower()
    return any(term.lower() in text for term in exclude_terms)


def tokenize(text):
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (text or "").lower()))


def count_term_hits(text, terms):
    text = (text or "").lower()
    hits = 0
    for term in terms:
        term = term.lower().strip()
        if term and term in text:
            hits += 1
    return hits


def normalize_source_text(text):
    text = (text or "").lower()
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quality_alias_matches(source, title, alias):
    alias = alias.lower().strip()
    if not alias:
        return False
    combined = f"{source} {title}"
    source_norm = normalize_source_text(source)
    alias_norm = normalize_source_text(alias)
    working_paper_terms = ["nber", "iza", "world bank", "working paper", "policy research working paper"]
    if any(term in alias_norm for term in working_paper_terms):
        if len(alias_norm) <= 5:
            return bool(re.search(rf"\b{re.escape(alias_norm)}\b", combined))
        return alias_norm in normalize_source_text(combined)
    return source_norm == alias_norm


def source_quality_score(paper, config):
    source = (paper.get("source") or "").lower()
    title = (paper.get("title") or "").lower()
    score = 0
    for item in config.get("quality_sources", []):
        name = item.get("name", "").lower()
        weight = float(item.get("weight", 0))
        aliases = [name] + [alias.lower() for alias in item.get("aliases", [])]
        if any(quality_alias_matches(source, title, alias) for alias in aliases):
            score += weight
    return round(score, 2)


def score_paper(paper, config):
    queries = config.get("queries", [])
    title_tokens = tokenize(paper.get("title"))
    abstract_tokens = tokenize(paper.get("abstract"))
    query_tokens = set()
    for query in queries:
        query_tokens |= tokenize(query)
    title_hits = len(title_tokens & query_tokens)
    abstract_hits = len(abstract_tokens & query_tokens)
    score = title_hits * 3 + abstract_hits
    if paper.get("is_oa"):
        score += 1
    if paper.get("doi"):
        score += 1
    score += min(int(paper.get("cited_by_count") or 0), 20) / 10
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    source = paper.get("source", "")
    combined = " ".join([title, abstract, source])
    score += count_term_hits(title, config.get("priority_terms", [])) * 2
    score += count_term_hits(abstract, config.get("priority_terms", []))
    score -= count_term_hits(combined, config.get("penalty_terms", [])) * 2
    q_score = source_quality_score(paper, config)
    paper["source_quality_score"] = q_score
    score += q_score
    return round(score, 2)


def sentence_summary(abstract, max_chars=260):
    abstract = re.sub(r"\s+", " ", abstract or "").strip()
    if not abstract:
        return "暂无摘要。"
    if len(abstract) <= max_chars:
        return abstract
    cut = abstract[:max_chars]
    last_period = max(cut.rfind("."), cut.rfind("。"))
    if last_period > 80:
        return cut[: last_period + 1]
    return cut.rstrip() + "..."


def llm_config(config):
    raw = config.get("llm") or {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "model": os.environ.get("OPENAI_MODEL") or raw.get("model", "gpt-4o-mini"),
        "max_reviews": int(raw.get("max_reviews", config.get("max_items_in_report", 8))),
        "temperature": float(raw.get("temperature", 0.2)),
    }


def paper_review_prompt(paper, topic_name):
    abstract = paper.get("abstract") or "No abstract available."
    return f"""请基于以下论文元数据，为研究者写一段中文文献 review，并补充中文题名和中文摘要。只根据给定信息判断，不要编造摘要中没有的信息。

研究领域：{topic_name}
英文题目：{paper.get('title', '')}
作者：{paper.get('authors', '')}
来源：{paper.get('source', '')}
日期：{paper.get('publication_date', '')}
英文摘要：{abstract}

请用 Markdown 输出以下 6 个短项目：
- 中文题目：
- 中文摘要：
- 研究问题：
- 方法与数据：
- 主要发现：
- 值得关注/可批判之处：
中文摘要应忠实概括英文摘要，不要超过 180 字。如果摘要不足以判断某一项，请明确写“摘要信息不足”。"""


def generate_llm_review(paper, config):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""
    options = llm_config(config)
    payload = {
        "model": options["model"],
        "temperature": options["temperature"],
        "messages": [
            {
                "role": "system",
                "content": "你是一名严谨的经济学文献助理，擅长把论文摘要转写为简洁、可信、可批判的中文研究综述。",
            },
            {"role": "user", "content": paper_review_prompt(paper, config.get("topic_name", "Literature Digest"))},
        ],
    }
    data = http_post_json(
        OPENAI_CHAT_COMPLETIONS_URL,
        payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=90,
    )
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content", "")
    return re.sub(r"\n{3,}", "\n\n", content).strip()


def collect_review_targets(config, papers):
    options = llm_config(config)
    if not options["enabled"]:
        return []
    modules = config.get("modules", [])
    if not modules:
        return papers[: options["max_reviews"]]
    targets = []
    seen = set()
    for module in modules:
        name = module.get("name", "")
        max_items = int(module.get("max_items", config.get("max_items_in_report", options["max_reviews"])))
        module_papers = [p for p in papers if name in p.get("modules", []) or p.get("module") == name]
        for paper in module_papers[:max_items]:
            key = paper.get("doi") or normalize_title(paper.get("title"))
            if key and key not in seen:
                seen.add(key)
                targets.append(paper)
            if len(targets) >= options["max_reviews"]:
                return targets
    return targets


def add_llm_reviews(config, papers):
    targets = collect_review_targets(config, papers)
    if not targets:
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Warning: llm.enabled is true but OPENAI_API_KEY is not set; skipping LLM reviews.", file=sys.stderr)
        return
    for i, paper in enumerate(targets, 1):
        try:
            print(f"Generating LLM review {i}/{len(targets)}: {paper.get('title', '')[:80]}", file=sys.stderr)
            paper["llm_review"] = generate_llm_review(paper, config)
        except Exception as e:
            print(f"Warning: failed to generate LLM review for {paper.get('title')}: {e}", file=sys.stderr)
            paper["llm_review"] = ""
        time.sleep(0.2)


def format_paper_markdown(paper, index):
    lines = []
    lines.append(f"### {index}. {paper['title']}")
    meta = []
    if paper.get("authors"):
        meta.append(paper["authors"])
    if paper.get("source"):
        meta.append(paper["source"])
    if paper.get("publication_date"):
        meta.append(paper["publication_date"])
    if paper.get("doi"):
        meta.append(f"DOI: {paper['doi']}")
    lines.append("")
    lines.append("；".join(meta) if meta else "元数据不足")
    lines.append("")
    lines.append(f"- 英文题目：{paper.get('title', '')}")
    lines.append(f"- 相关性分数：{paper.get('relevance_score')}")
    if paper.get("source_quality_score"):
        lines.append(f"- 高质量来源加权：+{paper.get('source_quality_score')}")
    if paper.get("matched_queries"):
        lines.append(f"- 检索命中：`{'; '.join(paper.get('matched_queries'))}`")
    else:
        lines.append(f"- 检索命中：`{paper.get('matched_query')}`")
    if paper.get("llm_review"):
        lines.append("")
        lines.append("**中文 review**")
        lines.append("")
        lines.append(paper["llm_review"])
    else:
        lines.append(f"- 摘要速览：{sentence_summary(paper.get('abstract'))}")
    if paper.get("url"):
        lines.append(f"- 原文/详情：{paper['url']}")
    if paper.get("pdf_url"):
        lines.append(f"- OA PDF：{paper['pdf_url']}")
    elif paper.get("is_oa"):
        lines.append("- 开放获取：是，但暂未解析到直接 PDF 链接")
    else:
        lines.append("- 开放获取：未确认，可能需要学校订阅或人工获取")
    return "\n".join(lines)


def module_config(global_config, module):
    merged = dict(global_config)
    merged["queries"] = module.get("queries", [])
    merged["priority_terms"] = list(global_config.get("priority_terms", [])) + list(module.get("priority_terms", []))
    merged["penalty_terms"] = list(global_config.get("penalty_terms", [])) + list(module.get("penalty_terms", []))
    merged["module_name"] = module.get("name", "")
    return merged


def module_match_score(paper, module):
    text = " ".join([paper.get("title", ""), paper.get("abstract", ""), paper.get("source", "")]).lower()
    score = 0
    for query in module.get("queries", []):
        score += len(tokenize(query) & tokenize(text))
    score += count_term_hits(text, module.get("priority_terms", [])) * 3
    score -= count_term_hits(text, module.get("penalty_terms", [])) * 2
    return score


def assign_modules_to_external_papers(papers, modules):
    for paper in papers:
        matches = []
        for module in modules:
            score = module_match_score(paper, module)
            if score > 0:
                matches.append((score, module.get("name", "")))
        matches.sort(reverse=True)
        if matches:
            paper["modules"] = [name for _, name in matches[:2]]
            paper["module"] = matches[0][1]
        else:
            paper["modules"] = []
            paper["module"] = ""
    return papers


def build_report(config, papers, from_date, generated_at):
    topic = config.get("topic_name", "Literature Digest")
    max_items = int(config.get("max_items_in_report", 12))
    selected = papers[:max_items]
    lines = [
        f"# {topic}：每周文献动态",
        "",
        f"- 生成时间：{generated_at}",
        f"- 检索时间窗：{from_date} 至 {generated_at[:10]}",
        f"- 检索式：{'; '.join(config.get('queries', []))}",
        f"- 候选文献数：{len(papers)}",
        f"- 本期列出：{len(selected)}",
        "",
        "## 本周建议优先查看",
        "",
    ]
    if not selected:
        lines.append("本期未检索到符合条件的候选文献。可以放宽关键词、扩大时间窗，或增加数据源。")
    for i, paper in enumerate(selected, 1):
        lines.append(format_paper_markdown(paper, i))
        lines.append("")
    lines.extend(
        [
            "## 备注",
            "",
            "- 第一版 MVP 使用 OpenAlex 检索元数据，并用规则进行粗排序。",
            "- 后续可接入 LLM，把“摘要速览”改成结构化中文总结：研究问题、方法、数据、发现、局限、为什么值得关注。",
            "- 付费墙论文不会自动绕过权限；系统只记录 DOI/链接，或下载合法开放获取 PDF。",
        ]
    )
    return "\n".join(lines)


def build_modular_report(config, module_results, from_date, generated_at):
    topic = config.get("topic_name", "Literature Digest")
    modules = config.get("modules", [])
    total_candidates = sum(len(items) for items in module_results.values())
    lines = [
        f"# {topic}：模块化每周文献动态",
        "",
        f"- 生成时间：{generated_at}",
        f"- 检索时间窗：{from_date} 至 {generated_at[:10]}",
        f"- 模块数：{len(modules)}",
        f"- 候选文献数：{total_candidates}",
        f"- 独立高质量来源：{len(config.get('independent_sources', []))} 个",
        "",
        "## 本周概览",
        "",
    ]
    for module in modules:
        name = module.get("name", "未命名模块")
        papers = module_results.get(name, [])
        lines.append(f"- {name}：{len(papers)} 篇候选，列出前 {min(len(papers), int(module.get('max_items', config.get('max_items_in_report', 8))))} 篇")
    lines.append("")

    for module in modules:
        name = module.get("name", "未命名模块")
        description = module.get("description", "")
        papers = module_results.get(name, [])
        max_items = int(module.get("max_items", config.get("max_items_in_report", 8)))
        lines.append(f"## {name}")
        lines.append("")
        if description:
            lines.append(description)
            lines.append("")
        if not papers:
            lines.append("本模块本期未检索到符合条件的候选文献。")
            lines.append("")
            continue
        for i, paper in enumerate(papers[:max_items], 1):
            lines.append(format_paper_markdown(paper, i))
            lines.append("")

    lines.extend(
        [
            "## 备注",
            "",
            "- 本版 MVP 使用 OpenAlex 作为统一元数据入口，并按模块关键词、高质量来源、排除词进行规则排序。",
            "- NBER、IZA、World Bank 等来源已作为独立入口接入；部分 RePEc 条目第一版只抓标题、作者和链接，摘要可后续深抓详情页补充。",
            "- 付费墙论文不会自动绕过权限；系统只记录 DOI/链接，或下载合法开放获取 PDF。",
        ]
    )
    return "\n".join(lines)


def markdown_to_simple_html(markdown_text):
    escaped_lines = []
    for line in markdown_text.splitlines():
        safe = html.escape(line)
        safe = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', safe)
        if line.startswith("# "):
            escaped_lines.append(f"<h1>{safe[2:]}</h1>")
        elif line.startswith("## "):
            escaped_lines.append(f"<h2>{safe[3:]}</h2>")
        elif line.startswith("### "):
            escaped_lines.append(f"<h3>{safe[4:]}</h3>")
        elif line.startswith("- "):
            escaped_lines.append(f"<p>{safe}</p>")
        elif not line.strip():
            escaped_lines.append("")
        else:
            escaped_lines.append(f"<p>{safe}</p>")
    body = "\n".join(escaped_lines)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.55; color: #172033; }}
    h1, h2, h3 {{ line-height: 1.25; }}
    h1 {{ font-size: 24px; }}
    h2 {{ font-size: 20px; margin-top: 28px; border-bottom: 1px solid #d8dee8; padding-bottom: 6px; }}
    h3 {{ font-size: 17px; margin-top: 22px; }}
    p {{ margin: 7px 0; }}
    a {{ color: #0b57d0; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def split_recipients(value):
    return [item.strip() for item in re.split(r"[,;]", value or "") if item.strip()]


def send_digest_email(config, report_path):
    smtp_host = os.environ.get("SMTP_HOST")
    recipients = split_recipients(os.environ.get("DIGEST_EMAIL_TO") or os.environ.get("SMTP_TO"))
    if not smtp_host or not recipients:
        raise RuntimeError("SMTP_HOST and DIGEST_EMAIL_TO must be set before sending email.")

    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    smtp_username = os.environ.get("SMTP_USERNAME", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM") or smtp_username
    if not sender:
        raise RuntimeError("SMTP_FROM or SMTP_USERNAME must be set before sending email.")

    markdown_text = report_path.read_text(encoding="utf-8")
    subject_template = (config.get("email") or {}).get("subject", "{topic_name} 每周文献动态")
    subject = subject_template.format(
        topic_name=config.get("topic_name", "Literature Digest"),
        date=dt.date.today().isoformat(),
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(markdown_text, subtype="plain", charset="utf-8")
    message.add_alternative(markdown_to_simple_html(markdown_text), subtype="html", charset="utf-8")
    message.add_attachment(
        markdown_text.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=report_path.name,
    )

    use_ssl = os.environ.get("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
            if smtp_username or smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if smtp_username or smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)


def run(config, output_dir):
    today = dt.date.today()
    from_days = int(config.get("from_days", 7))
    from_date = (today - dt.timedelta(days=from_days)).isoformat()
    modules = config.get("modules", [])
    all_papers = []
    search_jobs = []
    if modules:
        for module in modules:
            mod_config = module_config(config, module)
            for query in module.get("queries", []):
                search_jobs.append((module.get("name", ""), query, mod_config))
    else:
        for query in config.get("queries", []):
            search_jobs.append(("", query, config))

    for module_name, query, active_config in search_jobs:
        print(f"Searching OpenAlex: {query}", file=sys.stderr)
        try:
            found = (
                search_openalex(
                    query=query,
                    from_date=from_date,
                    to_date=today.isoformat(),
                    per_page=int(active_config.get("per_query_limit", 25)),
                    mailto=active_config.get("openalex_mailto", ""),
                    extra_filter=active_config.get("openalex_extra_filter", ""),
                    timeout=int(active_config.get("openalex_timeout", 20)),
                )
            )
        except Exception as e:
            print(f"Warning: failed to search OpenAlex for {query}: {e}", file=sys.stderr)
            found = []
        for paper in found:
            paper["module"] = module_name
        all_papers.extend(found)
        time.sleep(0.2)

    external_papers = []
    for source_config in config.get("independent_sources", []):
        print(f"Fetching independent source: {source_config.get('name', source_config.get('url'))}", file=sys.stderr)
        try:
            external_papers.extend(fetch_independent_source(source_config))
        except Exception as e:
            print(f"Warning: failed to fetch {source_config.get('name')}: {e}", file=sys.stderr)
        time.sleep(0.2)
    if modules and external_papers:
        external_papers = assign_modules_to_external_papers(external_papers, modules)
    all_papers.extend(external_papers)

    papers = merge_duplicate_papers(all_papers) if modules else dedupe_papers(all_papers)
    papers = [p for p in papers if not excluded(p, config.get("exclude_terms", []))]

    for paper in papers:
        paper["relevance_score"] = score_paper(paper, config)
        enrich_with_unpaywall(paper, config.get("unpaywall_email", ""))

    minimum_score = float(config.get("minimum_relevance_score", 0))
    if minimum_score:
        papers = [p for p in papers if p.get("relevance_score", 0) >= minimum_score]

    papers.sort(
        key=lambda p: (
            p.get("relevance_score", 0),
            p.get("publication_date") or "",
            p.get("cited_by_count") or 0,
        ),
        reverse=True,
    )
    add_llm_reviews(config, papers)

    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    date_slug = today.isoformat()
    json_path = output_dir / f"papers_{date_slug}.json"
    report_path = output_dir / f"digest_{date_slug}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    if modules:
        module_results = {}
        for module in modules:
            name = module.get("name", "")
            module_papers = [p for p in papers if name in p.get("modules", []) or p.get("module") == name]
            module_papers.sort(
                key=lambda p: (
                    p.get("relevance_score", 0),
                    p.get("source_quality_score", 0),
                    p.get("publication_date") or "",
                ),
                reverse=True,
            )
            module_results[name] = module_papers
        report = build_modular_report(config, module_results, from_date, generated_at)
    else:
        report = build_report(config, papers, from_date, generated_at)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report_path, json_path, len(papers)


def main():
    parser = argparse.ArgumentParser(description="Generate a weekly literature digest from open scholarly APIs.")
    parser.add_argument("--config", default="config.example.json", help="Path to JSON config file.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for report outputs.")
    parser.add_argument("--send-email", action="store_true", help="Send the generated digest via SMTP.")
    parser.add_argument("--email-report", help="Send an existing report file instead of generating a new one.")
    parser.add_argument("--dry-run-email", action="store_true", help="Validate email settings without sending.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.email_report:
        report_path = Path(args.email_report)
        if not report_path.exists():
            raise RuntimeError(f"Report file not found: {report_path}")
        json_path = None
        count = None
    else:
        report_path, json_path, count = run(config, Path(args.output_dir))
        print(f"Found {count} candidate papers")
        print(f"Report: {report_path}")
        print(f"Data: {json_path}")
    if args.dry_run_email:
        smtp_host = os.environ.get("SMTP_HOST")
        recipients = split_recipients(os.environ.get("DIGEST_EMAIL_TO") or os.environ.get("SMTP_TO"))
        sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME", "")
        print(f"Email dry run: SMTP_HOST={'set' if smtp_host else 'missing'}, sender={'set' if sender else 'missing'}, recipients={len(recipients)}")
    if args.send_email:
        send_digest_email(config, report_path)
        print("Email sent")


if __name__ == "__main__":
    main()
