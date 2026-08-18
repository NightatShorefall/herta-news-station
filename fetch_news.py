# -*- coding: utf-8 -*-
"""
新闻聚合抓取脚本
来源：中新网(RSS) + 央视网/人民网/新华网(网页)
输出：data/news.json
"""
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 北京时间时区
CST = timezone(timedelta(hours=8))

# 输出目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def today_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def strip_html(text):
    """去除 HTML 标签，得到纯文本"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_html(url, timeout=15):
    """抓取网页，自动处理编码"""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    if r.encoding and r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r


# ============ 1. 中新网（RSS） ============
def fetch_chinanews():
    """中新网滚动新闻 RSS"""
    url = "https://www.chinanews.com/rss/scroll-news.xml"
    d = feedparser.parse(url)
    items = []
    for e in d.entries:
        title = e.get("title", "").strip()
        link = e.get("link", "").strip()
        summary = strip_html(e.get("summary", ""))[:200]
        # 用 published_parsed (struct_time) 转成 YYYY-MM-DD
        pub_parsed = e.get("published_parsed") or e.get("updated_parsed")
        if pub_parsed:
            pub = time.strftime("%Y-%m-%d", pub_parsed)
        else:
            pub = e.get("published", "") or e.get("updated", "")
        items.append({
            "title": title,
            "link": link,
            "source": "中新网",
            "time": pub,
            "summary": summary,
        })
    return items


# ============ 2. 央视网（网页） ============
def fetch_cctv():
    url = "https://news.cctv.com/"
    r = fetch_html(url)
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 匹配新闻链接 /2026/08/18/xxx.shtml
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
        items.append({
            "title": title,
            "link": href,
            "source": "央视网",
            "time": date,
            "summary": "",
        })
    return items


# ============ 3. 人民网（网页） ============
def fetch_people():
    url = "http://www.people.com.cn/"
    r = fetch_html(url)
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 匹配 /n1/2026/0818/cxxxx.html
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
        items.append({
            "title": title,
            "link": href,
            "source": "人民网",
            "time": date,
            "summary": "",
        })
    return items


# ============ 4. 新华网（网页） ============
def fetch_xinhua():
    url = "https://www.news.cn/"
    r = fetch_html(url)
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 匹配 /xxx/20260818/xxx/c.html
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
        items.append({
            "title": title,
            "link": href,
            "source": "新华网",
            "time": date,
            "summary": "",
        })
    return items


def dedupe(items):
    """按链接去重，保留首次出现的"""
    seen = set()
    result = []
    for it in items:
        link = it["link"]
        if link and link not in seen:
            seen.add(link)
            result.append(it)
    return result


def main():
    today = today_str()
    print(f"[{today}] 开始抓取新闻...")

    all_items = []
    fetchers = [
        ("中新网", fetch_chinanews),
        ("央视网", fetch_cctv),
        ("人民网", fetch_people),
        ("新华网", fetch_xinhua),
    ]

    stat = {}
    for name, func in fetchers:
        try:
            items = func()
            stat[name] = len(items)
            all_items.extend(items)
            print(f"  ✅ {name}: {len(items)} 条")
        except Exception as e:
            stat[name] = f"失败: {type(e).__name__}"
            print(f"  ❌ {name}: {type(e).__name__}: {e}")

    # 去重
    all_items = dedupe(all_items)

    # 只保留当天的新闻（网页源的 time 是 URL 日期，RSS 源是 published）
    today_items = []
    for it in all_items:
        t = it["time"]
        if today in t:
            today_items.append(it)

    print(f"\n  去重后共 {len(all_items)} 条，当天新闻 {len(today_items)} 条")

    # 生成结果
    output = {
        "date": today,
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "stat": stat,
        "total": len(today_items),
        "news": today_items,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "news.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已写入 {out_path}（{len(today_items)} 条当天新闻）")

    # 生成内嵌数据的 index.html
    generate_html(output)
    return output


def generate_html(data):
    """把 JSON 数据内嵌进 index.html 模板，生成静态页面"""
    template_path = os.path.join(BASE_DIR, "index_template.html")
    index_path = os.path.join(BASE_DIR, "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    json_str = json.dumps(data, ensure_ascii=False)
    html = template.replace("__JSON_DATA__", json_str)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 已生成 {index_path}")


if __name__ == "__main__":
    main()
