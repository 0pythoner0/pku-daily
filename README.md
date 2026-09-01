# 北大日报智能体（pku_daily）

把北大官网通知 + 公众号文章，每天早上自动整理成一份日报推送到微信。

## 文件说明

| 文件 | 作用 |
|------|------|
| `main.py` | 主脚本：抓取 → 近 N 天 + 大一相关筛选 → DeepSeek 摘要 → PushPlus 推送 |
| `sources.json` | 信息源配置（你主要改这个） |
| `requirements.txt` | Python 依赖 |
| `.github/workflows/daily.yml` | GitHub Actions 定时任务 |
| `last_run.txt` | 最近一次运行日志（自动生成，没收到推送时先看它） |

> 💡 每天早上没收到日报时，先打开仓库里的 `last_run.txt`：
> - 文件日期是昨天 → 定时任务没触发（去 Actions 页看原因）
> - 文件显示"推送失败/返回异常" → 推送环节问题（检查 token）
> - 文件显示"推送成功" → 任务没问题，去微信/ PushPlus 查收

## 快速开始（3 步）

1. 在 GitHub 新建一个**公开**仓库，把这 4 个文件传上去。
2. 在 `Settings → Secrets and variables → Actions` 添加两个密钥：
   - `DEEPSEEK_API_KEY`（platform.deepseek.com 申请）
   - `PUSHPLUS_TOKEN`（pushplus.plus 微信扫码获取）
3. 点 `Actions → PKU Daily → Run workflow` 手动测试，微信即可收到日报。

## 本地试跑（可选）

```bash
pip install -r requirements.txt
set DEEPSEEK_API_KEY=sk-xxx
set PUSHPLUS_TOKEN=xxx
python main.py
```

## 信息源与筛选说明

- **已内置官网源（自动抓取）**：教务部、学工部、北大新闻网、计算中心通知、工学院本科生通知、总务部后勤动态、力学与工程科学学院通知。
- **近两天窗口**：`sources.json` 里的 `days_lookback = 2`，只推送 **近 2 天** 发布的内容（没有日期的页面保守保留）。不做历史去重、也不限制条数——所有符合"近 2 天 + 大一相关"的文章都会推送。
- **大一新生筛选**：自动过滤研究生 / 教职工 / 毕业生 / 招标类通知，只保留本科新生可参与或需关注的内容（选课、注册、军训、社团、讲座、生活服务等）。配了 DeepSeek 后还会再做强一轮语义筛选。
- **公众号源（11 个，默认关闭）**：青春北京、未名校园集市、北大百周年纪念讲堂、北大教务部、为名小喇叭、P大CoE教务、北京大学（官微）、清北情报站、工映青春、北大新青年、北大餐饮中心官方资讯。默认 `enabled: false`，需拿到公众号 biz 后启用（见下）。
- **关于"校内信息门户"**：`portal.pku.edu.cn` 需要登录，云端无法静态抓取，因此未纳入。门户里的"校内公告"大多会同步到教务部 / 学工部 / 新闻网等公开源（已内置），建议关注这几个即可。

## 启用公众号源（把公众号文章也收进来）

1. 按教程第 7 节获取公众号的 `biz`（搜狗微信搜索，或 RSSHub / wechat2rss 公共实例）。
   - 已知微信号线索：北大教务部 = `DEANPKU`、工映青春 = `pkucoeyouth`（需再转成 biz）。
2. 打开 `sources.json`，把对应公众号的 `url` 改成你的 RSS 实例，例如：
   `"url": "https://你的RSSHub实例/wechat/mp/msgalbum/替换为biz/替换为album_id"`
3. 把 `"enabled": false` 改成 `true`。
4. 重新上传 `sources.json`，手动触发一次 `Run workflow` 验证。

完整教程见同目录《北大日报智能体教程.html》或《教程.md》。
