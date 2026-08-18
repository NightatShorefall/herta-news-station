# -*- coding: utf-8 -*-
"""
新闻聚合抓取脚本 v2
- 抓取：中新网(RSS) + 央视网/人民网/新华网(网页)
- 处理：按链接去重 → 按标题关键词聚类话题 → 拼接摘要(约200字)
- 输出：data/news.json + index.html
"""
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests
import feedparser
import jieba
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
CST = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 停用词（精简）
STOP_WORDS = set("的 了 在 是 和 与 及 等 对 中 为 有 不 也 将 从 到 被 让 把 就 都 而 但 并 或 又 再 这 那 我 你 他 她 它 我们 你们 他们 一个 什么 如何 为什么 记者 报道 新闻 今天 昨天 可能 表示 称 说 据 新华社 人民日报 央视网 中新网 人民网 新华网 中国 国 全国 国家 国际 北京 全国 问题 工作 发展 建设 习近平 同志 强调 指出 要求 会见 举行 开展 进行 取得 积极 重要 深入 全面 进一步 着力 推动 推进 加快 实现 持续 不断 有力 扎实 稳妥 有序 有效 重大 明显 突出 显著 首 第 一 二 三 四 五 六 七 八 九 十 月 日 年".split())


def today_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_html(url, timeout=15):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    if r.encoding and r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r


# ============ 抓取：中新网（RSS） ============
def fetch_chinanews():
    url = "https://www.chinanews.com/rss/scroll-news.xml"
    d = feedparser.parse(url)
    items = []
    for e in d.entries:
        title = e.get("title", "").strip()
        link = e.get("link", "").strip()
        summary = strip_html(e.get("summary", ""))[:200]
        pub_parsed = e.get("published_parsed") or e.get("updated_parsed")
        pub = time.strftime("%Y-%m-%d", pub_parsed) if pub_parsed else (e.get("published", "") or e.get("updated", ""))
        items.append({"title": title, "link": link, "source": "中新网", "time": pub, "summary": summary})
    return items


# ============ 抓取：央视网（网页） ============
def fetch_cctv():
    r = fetch_html("https://news.cctv.com/")
    soup = BeautifulSoup(r.text, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/(20\d{2}/\d{2}/\d{2})/", href)
        if not m:
            continue
        date = m.group(1).replace("/", "-")
        title = a.get_text(strip=True)
        if len(title) < 8:
            continue
        if not href.startswith("http"):
            href = "https://news.cctv.com" + href if href.startswith("/") else href
        if href in seen:
            continue
        seen.add(href)
        items.append({"title": title, "link": href, "source": "央视网", "time": date, "summary": ""})
    return items


# ============ 抓取：人民网（网页） ============
def fetch_people():
    r = fetch_html("http://www.people.com.cn/")
    soup = BeautifulSoup(r.text, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/n1/(20\d{2})/(\d{2})(\d{2})/", href)
        if not m:
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        title = a.get_text(strip=True)
        if len(title) < 8:
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append({"title": title, "link": href, "source": "人民网", "time": date, "summary": ""})
    return items


# ============ 抓取：新华网（网页） ============
def fetch_xinhua():
    r = fetch_html("https://www.news.cn/")
    soup = BeautifulSoup(r.text, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/(20\d{2})(\d{2})(\d{2})/[^/]+/c\.html", href)
        if not m:
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        title = a.get_text(strip=True)
        if len(title) < 8:
            continue
        if href in seen:
            continue
        seen.add(href)
        items.append({"title": title, "link": href, "source": "新华网", "time": date, "summary": ""})
    return items


def dedupe(items):
    """按链接去重"""
    seen, result = set(), []
    for it in items:
        if it["link"] and it["link"] not in seen:
            seen.add(it["link"])
            result.append(it)
    return result


# ============ 话题合并 ============
def extract_keywords(title):
    """从标题提取特征词（jieba 分词，过滤停用词和短词）"""
    words = set()
    for w in jieba.cut(title):
        w = w.strip()
        if len(w) >= 2 and w not in STOP_WORDS and not w.isdigit():
            words.add(w)
    return words


def cluster_topics(items):
    """
    贪心话题聚类：
    - 每篇新闻提取标题特征词
    - 与已有话题共享 >=2 个特征词则归入该话题，否则新建话题
    """
    topics = []
    for it in items:
        kw = extract_keywords(it["title"])
        placed = False
        for tp in topics:
            if len(kw & tp["keywords"]) >= 2:
                tp["items"].append(it)
                tp["keywords"] |= kw
                placed = True
                break
        if not placed:
            topics.append({"keywords": kw, "items": [it]})
    return topics


def build_summary(topic):
    """拼接话题内新闻的标题和摘要，截断约 200 字"""
    parts = []
    for it in topic["items"]:
        parts.append(it["title"])
        if it.get("summary"):
            parts.append(it["summary"])
    text = "。".join([p for p in parts if p])
    # 去重句子
    seen, out = set(), []
    for seg in re.split(r"[。！？]", text):
        seg = seg.strip()
        if seg and seg not in seen:
            seen.add(seg)
            out.append(seg)
    joined = "。".join(out)
    if len(joined) > 220:
        joined = joined[:220] + "……"
    return joined


def main():
    today = today_str()
    print(f"[{today}] 开始抓取新闻...")
    all_items = []
    fetchers = [("中新网", fetch_chinanews), ("央视网", fetch_cctv), ("人民网", fetch_people), ("新华网", fetch_xinhua)]
    stat = {}
    for name, func in fetchers:
        try:
            items = func()
            stat[name] = len(items)
            all_items.extend(items)
            print(f"  OK {name}: {len(items)}")
        except Exception as e:
            stat[name] = f"失败: {type(e).__name__}"
            print(f"  ERR {name}: {e}")

    all_items = dedupe(all_items)
    today_items = [it for it in all_items if today in it["time"]]
    print(f"  去重后 {len(all_items)} 条，当天 {len(today_items)} 条")

    # 话题聚类
    topics = cluster_topics(today_items)
    # 按话题内新闻数排序，取主要标题
    topics_data = []
    for i, tp in enumerate(topics, 1):
        t_items = tp["items"]
        sources = []
        for it in t_items:
            if it["source"] not in sources:
                sources.append(it["source"])
        topics_data.append({
            "id": i,
            "title": t_items[0]["title"],
            "summary": build_summary(tp),
            "sources": sources,
            "count": len(t_items),
            "items": t_items,
        })
    topics_data.sort(key=lambda t: -t["count"])
    # 过滤：只保留至少 2 个不同网站报道的话题（单源话题不展示）
    before = len(topics_data)
    topics_data = [t for t in topics_data if len(t["sources"]) >= 2]
    print(f"  过滤单源话题: {before} -> {len(topics_data)}")

    output = {
        "date": today,
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "stat": stat,
        "total": len(topics_data),
        "topics": topics_data,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "news.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    generate_html(output)
    print(f"  ✅ 生成 {len(topics_data)} 个话题")


def generate_html(data):
    with open(os.path.join(BASE_DIR, "index_template.html"), "r", encoding="utf-8") as f:
        template = f.read()
    html = template.replace("__JSON_DATA__", json.dumps(data, ensure_ascii=False))
    with open(os.path.join(BASE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  ✅ index.html")


if __name__ == "__main__":
    main()
