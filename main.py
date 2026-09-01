# -*- coding: utf-8 -*-
"""
北大日报智能体 —— 主脚本
================================
功能：
  1. 从北大官网通知页（HTML 列表）和公众号/新闻（RSS）抓取近期内容
  2. 与 history.json 里的历史链接比对，只保留"没推过的新内容"
  3. 交给 DeepSeek 生成一份结构化的「今日北大日报」
  4. 通过 PushPlus 推送到你的手机微信

这套代码零基础也能看懂：每个函数上方都写了它在做什么。
你只需要改两个地方：sources.json（信息源）和 GitHub 上的密钥（Secrets）。
"""

import os
import re
import json
import datetime

import requests
import feedparser
from bs4 import BeautifulSoup

# ---------------------------- 基础配置 ----------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(BASE_DIR, "sources.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")

# 只报"最近 N 天"的内容（防旧文章刷屏）
DAYS_LOOKBACK = 1

# 每个源最多取前几条（避免某一天集中爆发刷爆日报）
MAX_PER_SOURCE = 6

HEADERS = {
    # 伪装成普通浏览器，有些网站会拦截脚本请求
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


# ---------------------------- 读取信息源 ----------------------------

def load_sources():
    """读取 sources.json，返回信息源列表。文件不存在或格式错误时给出友好提示。"""
    if not os.path.exists(SOURCES_FILE):
        print("❌ 找不到 sources.json，请先创建它（教程里有模板）。")
        return []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sources", [])


# ---------------------------- 抓取 HTML 类型的源 ----------------------------

def extract_date(text):
    """从一段文本里抠出日期，支持 2026-07-16 / 2026.7.16 / 07-16 2026 / 2026年7月16日 等写法。"""
    if not text:
        return ""
    text = text.replace(" ", "")
    # 优先匹配 2026-07-16 或 2026/07/16 或 2026年7月16日
    m = re.search(r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})", text)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    # 再匹配 07-16 2026 这种"月-日 年"的写法
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[^0-9]{0,3}(20\d{2})", text)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2)))
    return ""


def fetch_html_source(src):
    """抓一个 HTML 列表页，把里面的标题+链接+日期抠出来。
    核心思路：找出页面上所有 <a> 链接，取它的文字当标题，
    再从链接附近找日期。对绝大多数"通知公告"列表页都适用。"""
    name = src.get("name", "未命名源")
    url = src["url"]
    base = src.get("base_url", url)
    min_len = src.get("title_min_len", 8)          # 标题至少几个字，太短的可能是导航
    must_contain = src.get("url_contains", "")      # 可选：链接里必须包含的关键词
    exclude = src.get("exclude", "")                # 可选：链接里不能包含的关键词

    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        # 很多中文网站不写编码，这里用推测的编码，防止乱码
        if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️  抓取失败 [{name}]：{e}")
        return items

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) < min_len or not href:
            continue
        if href.startswith("#") or href.startswith("javascript"):
            continue
        if must_contain and must_contain not in href:
            continue
        if exclude and exclude in href:
            continue

        # 完整链接：相对路径补全成绝对路径
        if href.startswith("http"):
            full = href
        else:
            from urllib.parse import urljoin
            full = urljoin(base, href)

        # 日期优先从链接文字里找，找不到就向上找最多 3 级父节点
        # （有些网站把日期放在标题外面好几层，只找一层会漏掉）
        date_text = extract_date(title)
        if not date_text:
            node = a.parent
            for _ in range(3):
                if node is None:
                    break
                date_text = extract_date(node.get_text(" ", strip=True))
                if date_text:
                    break
                node = node.parent

        items.append({"title": title, "url": full, "date": date_text, "source": name})

    # 按页面出现顺序，最新的通常在最前面，只保留前 N 条
    items = items[: src.get("max_items", MAX_PER_SOURCE)]
    print(f"✅ [{name}] 抓到 {len(items)} 条")
    return items


# ---------------------------- 抓取 RSS 类型的源 ----------------------------

def fetch_rss_source(src):
    """抓一个 RSS 源（公众号转 RSS 后得到的链接），feedparser 会自动解析。"""
    name = src.get("name", "未命名源")
    url = src["url"]
    items = []
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            print(f"⚠️  RSS 解析异常 [{name}]：{feed.bozo_exception}")
            return items
        for e in feed.entries[: src.get("max_items", MAX_PER_SOURCE)]:
            title = e.get("title", "").strip()
            link = e.get("link", "")
            if not title or not link:
                continue
            # 很多 RSS 里带发布时间的结构
            dt = ""
            for key in ("published", "updated"):
                if e.get(key):
                    dt = extract_date(str(e.get(key)))
                    if dt:
                        break
            items.append({"title": title, "url": link, "date": dt, "source": name})
        print(f"✅ [{name}] 抓到 {len(items)} 条")
    except Exception as e:
        print(f"⚠️  RSS 抓取失败 [{name}]：{e}")
    return items


# ---------------------------- 天气（免费，无需 key） ----------------------------

def fetch_weather(city="Beijing"):
    """用 wttr.in 拿北京天气，完全免费、不用注册、不用 key。"""
    try:
        r = requests.get(
            f"https://wttr.in/{city}?format=j1", headers=HEADERS, timeout=15
        )
        data = r.json()
        cur = data["current_condition"][0]
        desc = cur["lang_zh"][0]["value"] if cur.get("lang_zh") else cur.get("weatherDesc", [{}])[0].get("value", "")
        temp = cur.get("temp_C", "")
        feels = cur.get("FeelsLikeC", "")
        humidity = cur.get("humidity", "")
        return f"{desc}，气温 {temp}°C（体感 {feels}°C），湿度 {humidity}%"
    except Exception as e:
        print(f"⚠️  天气获取失败：{e}")
        return ""


# ---------------------------- 历史去重 ----------------------------

def load_history():
    """读取已经推过的链接集合，用于去重。"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_history(urls):
    """把本次新链接追加进历史，最多保留 3000 条防止文件无限膨胀。"""
    history = load_history()
    history.update(urls)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history)[-3000:], f, ensure_ascii=False, indent=2)


# ---------------------------- 组装日报（无 AI 兜底版） ----------------------------

def build_raw_digest(items, weather, today):
    """在没有 AI 的情况下，先把抓到的内容拼成一份朴素的列表，作为兜底。"""
    lines = [f"# 📰 北大日报 · {today}", ""]
    if weather:
        lines += [f"🌤️ **今日天气**：{weather}", ""]

    if not items:
        lines.append("今天各信息源暂无新内容，安心上课~")
        return "\n".join(lines)

    # 按来源分组，读起来更清爽
    by_source = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)

    for source, arr in by_source.items():
        lines.append(f"## {source}")
        for it in arr:
            date_part = f"（{it['date']}）" if it.get("date") else ""
            lines.append(f"- [{it['title']}]({it['url']}) {date_part}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------- DeepSeek 生成日报 ----------------------------

SYSTEM_PROMPT = (
    "你是一名贴心的校园信息助理，负责把北京大学各个官网和公众号的通知整理成一份"
    "「每日简报」，推送给大一新生。要求：\n"
    "1. 用简体中文，语气亲切但不啰嗦；\n"
    "2. 把内容按板块归类，例如【重要通知】【课程与考试】【讲座与活动】【就业与实习】【其他】；\n"
    "3. 每条用一句话概括要点，并在后面保留原文链接（markdown 链接格式）；\n"
    "4. 如果某条明显是旧的或无关的（如往年的公示），可以忽略；\n"
    "5. 结尾用一两句话给新生一个贴心小提示（比如注意截止时间）。\n"
    "直接输出 markdown 格式的简报正文，不要输出多余的解释。"
)


def summarize_with_ai(raw_digest, today):
    """把抓到的原始列表交给 DeepSeek，让它整理成一份好看的日报。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ℹ️  未配置 DEEPSEEK_API_KEY，使用无 AI 的朴素版。")
        return raw_digest

    payload = {
        "model": "deepseek-chat",  # DeepSeek 的通用对话模型，OpenAI 兼容
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"今天是 {today}。以下是我抓到的近期内容：\n\n{raw_digest}"},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  AI 调用失败（回退到朴素版）：{e}")
        return raw_digest


# ---------------------------- PushPlus 推送 ----------------------------

def push_wechat(title, content):
    """通过 PushPlus 把内容推到微信。token 存在 GitHub Secrets 里。
    返回一个结果字符串，会写进 last_run.txt，方便第二天排查推送有没有成功。"""
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        print("ℹ️  未配置 PUSHPLUS_TOKEN，跳过推送（内容已打印在上方）。")
        print("-" * 60)
        print(content)
        print("-" * 60)
        return "未配置 PUSHPLUS_TOKEN（推送被跳过）"

    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content, "template": "markdown"},
            timeout=30,
        )
        result = r.json()
        if result.get("code") == 200:
            print("✅ 已推送到微信！")
            return "推送成功 ✅"
        else:
            print(f"⚠️  推送返回异常：{result}")
            return f"推送返回异常：{result}"
    except Exception as e:
        print(f"⚠️  推送失败：{e}")
        return f"推送失败：{e}"


# ---------------------------- 主流程 ----------------------------

def main():
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    print(f"===== 北大日报 · {today} 开始生成（{now:%H:%M:%S}）=====")

    # 运行日志：每天把运行结果写进 last_run.txt 并提交回仓库，
    # 第二天没收到推送时，打开仓库里的这个文件就知道任务到底跑没跑、卡在哪一步。
    log_lines = [f"运行时间（北京时间）：{now:%Y-%m-%d %H:%M:%S}"]

    history = load_history()
    all_items = []

    for src in load_sources():
        if not src.get("enabled", True):
            continue
        src_type = src.get("type", "html")
        if src_type == "rss":
            got = fetch_rss_source(src)
        else:
            got = fetch_html_source(src)
        log_lines.append(f"信息源 [{src['name']}]：抓到 {len(got)} 条")
        for it in got:
            # 去重：历史里出现过的链接不再报
            if it["url"] not in history:
                all_items.append(it)

    # 只保留"今天新增"的那批链接，稍后写回历史
    new_urls = [it["url"] for it in all_items]
    log_lines.append(f"去重后新增：{len(all_items)} 条")

    weather = fetch_weather()
    log_lines.append(f"天气：{weather or '获取失败'}")

    raw = build_raw_digest(all_items, weather, today)
    digest = summarize_with_ai(raw, today)

    push_result = push_wechat(f"📰 北大日报 · {today}（{now:%H:%M} 生成）", digest)
    log_lines.append(f"推送结果：{push_result}")

    # 把本次推过的链接记下来，下次不再重复
    save_history(new_urls)

    try:
        with open(os.path.join(BASE_DIR, "last_run.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")
    except Exception as e:
        print(f"⚠️  写入 last_run.txt 失败：{e}")
    print(f"===== 完成：本次新增 {len(all_items)} 条 =====")


if __name__ == "__main__":
    main()
