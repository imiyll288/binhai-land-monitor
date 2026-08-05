#!/usr/bin/env python3
"""Collect Binhai New Area land notices from official Tianjin portals."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "dashboard_data.json"
HTML_FILE = ROOT / "滨海新区土地信息.html"
INDEX_FILE = ROOT / "index.html"
USER_AGENT = "BinhaiLandMonitor/1.0 (public-government-information collector)"


def request_json(url: str, *, payload: dict | None = None) -> dict:
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def iso_date_from_ms(value: int | float) -> str:
    return dt.datetime.fromtimestamp(float(value) / 1000, tz=dt.timezone(dt.timedelta(hours=8))).date().isoformat()


def normalize_url(url: str, base: str) -> str:
    return urllib.parse.urljoin(base, url)


def land_code(title: str) -> str:
    clean = re.sub(r"\s+", "", title)
    clean = clean.replace("（", "(").replace("）", ")")
    patterns = [
        r"(津滨[^号，。；\s]{0,30}?\d{4}[-—]\d+号)",
        r"(津滨[^号，。；\s]{0,30}?G\d{4}[-—]\d+号)",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return match.group(1).replace("(", "（").replace(")", "）")
    return re.sub(r"(宗地.*|地块.*|的国有.*|土地.*|出让.*|公告.*)$", "", clean)[:60]


def collect_ggzy() -> list[dict]:
    endpoint = "https://ggzy.zwfwb.tj.gov.cn/content/pageContent"
    base = "https://ggzy.zwfwb.tj.gov.cn"
    records: list[dict] = []
    for category, channel in (("出让公告", "82326"), ("成交结果", "82327")):
        page = 1
        while page <= 10:
            payload = {
                "pageNo": page,
                "count": 100,
                "orderBy": "27",
                "isNew": True,
                "title": "",
                "projectType": "",
                "areaNo": "滨海新区",
                "inDate": "",
                "tenderProjectCode": "",
                "channelIds": [channel],
                "timeBegin": "",
                "timeEnd": "",
            }
            result = request_json(endpoint, payload=payload)
            content = result.get("content") or []
            for item in content:
                title = str(item.get("title") or "").strip()
                records.append({
                    "title": title,
                    "code": land_code(title),
                    "date": iso_date_from_ms(item["releaseTime"]),
                    "category": category,
                    "url": normalize_url(str(item.get("url") or ""), base),
                    "source": "天津市公共资源交易平台",
                })
            if not content or page * 100 >= int(result.get("totalElements") or 0):
                break
            page += 1
    return records


def collect_planning() -> list[dict]:
    endpoint = "https://ghhzrzy.tj.gov.cn/igs/front/search/list.html"
    records: list[dict] = []
    for category, channel in (("出让公告", "62577"), ("成交结果", "62578")):
        params = {
            "pageNumber": "1",
            "pageSize": "500",
            "filter[CHANNELID]": channel,
            "index": "tjsghhzrglj",
            "type": "xzxkjgcx",
            "orderProperty": "ZXSJ",
            "orderDirection": "desc",
            "filter[AVAILABLE]": "true",
        }
        result = request_json(endpoint + "?" + urllib.parse.urlencode(params))
        for item in (result.get("page") or {}).get("content") or []:
            title = str(item.get("BT") or "").strip()
            compact = re.sub(r"\s+", "", title)
            if not ("津滨" in compact or "滨海新区" in compact):
                continue
            raw_date = str(item.get("ZXSJ") or "")[:10]
            records.append({
                "title": title,
                "code": land_code(title),
                "date": raw_date,
                "category": category,
                "url": str(item.get("DOCPUBURL") or ""),
                "source": "天津市规划和自然资源局",
            })
    return records


def merge_records(current: list[dict], previous: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in previous + current:
        code = item.get("code") or land_code(item.get("title", ""))
        key = f"{item.get('category')}|{code or item.get('url')}"
        if key not in merged:
            row = dict(item)
            row["code"] = code
            row["sources"] = [item.get("source")] if item.get("source") else list(item.get("sources") or [])
            merged[key] = row
        else:
            row = merged[key]
            source_names = list(row.get("sources") or [])
            candidate_sources = [item.get("source")] if item.get("source") else list(item.get("sources") or [])
            for name in candidate_sources:
                if name and name not in source_names:
                    source_names.append(name)
            row["sources"] = source_names
            if item.get("date", "") > row.get("date", ""):
                row["date"] = item["date"]
            if item.get("source") == "天津市公共资源交易平台":
                row["url"] = item.get("url", row.get("url"))
                row["title"] = item.get("title", row.get("title"))
    return sorted(merged.values(), key=lambda x: (x.get("date", ""), x.get("code", "")), reverse=True)


def load_previous() -> dict:
    if not DATA_FILE.exists():
        return {"records": [], "source_status": {}}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"records": [], "source_status": {}}


def render_dashboard(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>滨海新区土地信息监测</title>
<style>
:root{--ink:#17201d;--muted:#68736f;--line:#dbe2df;--paper:#fff;--wash:#f4f7f5;--green:#176b50;--green2:#e6f2ed;--amber:#a96816;--amber2:#fff4df;--red:#a43d3d}*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:14px/1.55 "Microsoft YaHei","PingFang SC",Arial,sans-serif;letter-spacing:0}button,input,select{font:inherit;letter-spacing:0}.top{background:#173b31;color:#fff;border-bottom:4px solid #d0a34a}.top-inner,.main{width:min(1220px,calc(100% - 32px));margin:auto}.top-inner{padding:25px 0 21px;display:flex;justify-content:space-between;gap:24px;align-items:flex-end}.eyebrow{font-size:12px;color:#bcd2ca;margin-bottom:4px}.title{font-size:26px;font-weight:700;margin:0}.updated{text-align:right;color:#dbe9e4;font-size:13px}.statusbar{background:#fff;border-bottom:1px solid var(--line)}.status-inner{width:min(1220px,calc(100% - 32px));margin:auto;min-height:44px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}.source-status{display:flex;align-items:center;gap:7px}.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.dot.bad{background:var(--red)}.main{padding:24px 0 42px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);background:#fff;border:1px solid var(--line);margin-bottom:18px}.metric{padding:16px 18px;border-right:1px solid var(--line)}.metric:last-child{border:0}.metric strong{display:block;font-size:23px}.metric span{color:var(--muted);font-size:12px}.toolbar{background:#fff;border:1px solid var(--line);padding:14px;display:grid;grid-template-columns:minmax(220px,1fr) auto auto;gap:12px;margin-bottom:12px}.search{position:relative}.search input{width:100%;height:40px;border:1px solid #b9c5c0;padding:0 12px;background:#fff;outline:none}.search input:focus{border-color:var(--green);box-shadow:0 0 0 2px rgba(23,107,80,.12)}.segments{display:flex;border:1px solid #b9c5c0;height:40px}.segments button{border:0;border-right:1px solid #b9c5c0;background:#fff;padding:0 15px;color:#4f5c57;cursor:pointer}.segments button:last-child{border:0}.segments button.active{background:var(--green);color:#fff}.toolbar select{height:40px;border:1px solid #b9c5c0;background:#fff;padding:0 30px 0 10px}.summary{display:flex;justify-content:space-between;color:var(--muted);font-size:13px;margin:8px 2px}.table-wrap{background:#fff;border:1px solid var(--line);overflow:auto}table{width:100%;border-collapse:collapse;min-width:850px}th{text-align:left;color:#4f5c57;background:#f7f9f8;font-size:12px;font-weight:600;padding:11px 14px;border-bottom:1px solid var(--line)}td{padding:13px 14px;border-bottom:1px solid #edf1ef;vertical-align:top}tbody tr:hover{background:#fafcfb}.code{font-weight:700;color:#21312b}.tag{display:inline-block;padding:2px 7px;font-size:12px;border:1px solid #b5d7ca;background:var(--green2);color:var(--green);white-space:nowrap}.tag.result{border-color:#ead0a4;background:var(--amber2);color:var(--amber)}.source{color:var(--muted);font-size:12px}.link{color:var(--green);text-decoration:none;font-weight:600;white-space:nowrap}.link:hover{text-decoration:underline}.empty{padding:45px;text-align:center;color:var(--muted)}.notice{margin-top:14px;color:var(--muted);font-size:12px}.notice a{color:var(--green)}@media(max-width:780px){.top-inner{align-items:flex-start;flex-direction:column}.updated{text-align:left}.title{font-size:22px}.metrics{grid-template-columns:repeat(2,1fr)}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid var(--line)}.toolbar{grid-template-columns:1fr}.segments{overflow:auto}.segments button{flex:1;padding:0 10px}.status-inner{padding:8px 0}.main{padding-top:16px}}
</style>
</head>
<body>
<header class="top"><div class="top-inner"><div><div class="eyebrow">政府门户公开信息汇总</div><h1 class="title">滨海新区土地信息监测</h1></div><div class="updated">最近采集：<strong id="updatedAt"></strong><br>每日自动更新，历史记录持续保留</div></div></header>
<div class="statusbar"><div class="status-inner" id="sourceStatus"></div></div>
<main class="main">
  <section class="metrics"><div class="metric"><strong id="mTotal">0</strong><span>累计记录</span></div><div class="metric"><strong id="mNotice">0</strong><span>出让公告</span></div><div class="metric"><strong id="mResult">0</strong><span>成交结果</span></div><div class="metric"><strong id="mRecent">0</strong><span>近 30 天发布</span></div></section>
  <section class="toolbar"><label class="search"><input id="query" type="search" placeholder="搜索宗地编号或公告标题" autocomplete="off"></label><div class="segments" aria-label="信息类型"><button class="active" data-type="全部">全部</button><button data-type="出让公告">出让公告</button><button data-type="成交结果">成交结果</button></div><select id="year" aria-label="发布年份"><option value="全部">全部年份</option></select></section>
  <div class="summary"><span id="resultCount"></span><span>按发布日期倒序</span></div>
  <div class="table-wrap"><table><thead><tr><th style="width:150px">宗地编号</th><th>公告标题</th><th style="width:110px">信息类型</th><th style="width:112px">发布日期</th><th style="width:175px">政府来源</th><th style="width:80px">原文</th></tr></thead><tbody id="rows"></tbody></table><div class="empty" id="empty" hidden>没有符合当前条件的记录</div></div>
  <p class="notice">本页仅汇总政府门户公开信息，不构成法律或投资意见。最终内容以原政府网站为准；点击“查看原文”可核验公告全文。</p>
</main>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const DATA=JSON.parse(document.getElementById('payload').textContent);let type='全部';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.getElementById('updatedAt').textContent=DATA.updated_at.replace('T',' ').slice(0,16);
const statusBox=document.getElementById('sourceStatus');Object.entries(DATA.source_status).forEach(([name,s])=>{const el=document.createElement('div');el.className='source-status';el.innerHTML=`<i class="dot ${s.ok?'':'bad'}"></i><span>${esc(name)}：${s.ok?'正常':'本次失败，已保留历史数据'}</span>`;statusBox.appendChild(el)});
const records=DATA.records||[];document.getElementById('mTotal').textContent=records.length;document.getElementById('mNotice').textContent=records.filter(x=>x.category==='出让公告').length;document.getElementById('mResult').textContent=records.filter(x=>x.category==='成交结果').length;const cutoff=new Date();cutoff.setDate(cutoff.getDate()-30);document.getElementById('mRecent').textContent=records.filter(x=>new Date(x.date)>=cutoff).length;
const year=document.getElementById('year');[...new Set(records.map(x=>x.date.slice(0,4)))].sort().reverse().forEach(y=>year.insertAdjacentHTML('beforeend',`<option>${esc(y)}</option>`));
function draw(){const q=document.getElementById('query').value.trim().toLowerCase();const y=year.value;const out=records.filter(x=>(type==='全部'||x.category===type)&&(y==='全部'||x.date.startsWith(y))&&(!q||(`${x.code} ${x.title}`).toLowerCase().includes(q)));document.getElementById('resultCount').textContent=`显示 ${out.length} 条，共 ${records.length} 条`;document.getElementById('rows').innerHTML=out.map(x=>`<tr><td class="code">${esc(x.code||'未提取')}</td><td>${esc(x.title)}</td><td><span class="tag ${x.category==='成交结果'?'result':''}">${esc(x.category)}</span></td><td>${esc(x.date)}</td><td class="source">${esc((x.sources||[x.source]).join(' / '))}</td><td><a class="link" target="_blank" rel="noopener" href="${esc(x.url)}">查看原文</a></td></tr>`).join('');document.getElementById('empty').hidden=out.length>0}
document.getElementById('query').addEventListener('input',draw);year.addEventListener('change',draw);document.querySelectorAll('.segments button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.segments button').forEach(x=>x.classList.remove('active'));b.classList.add('active');type=b.dataset.type;draw()}));draw();
</script></body></html>'''
    rendered = template.replace("__PAYLOAD__", payload)
    HTML_FILE.write_text(rendered, encoding="utf-8")
    INDEX_FILE.write_text(rendered, encoding="utf-8")


def main() -> int:
    previous = load_previous()
    fresh: list[dict] = []
    statuses: dict[str, dict] = {}
    collectors = [
        ("天津市公共资源交易平台", collect_ggzy),
        ("天津市规划和自然资源局", collect_planning),
    ]
    for name, collector in collectors:
        try:
            rows = collector()
            fresh.extend(rows)
            statuses[name] = {"ok": True, "count": len(rows), "message": ""}
            print(f"[OK] {name}: {len(rows)} records")
        except Exception as exc:  # Preserve history when an official site is temporarily unavailable.
            statuses[name] = {"ok": False, "count": 0, "message": str(exc)[:180]}
            print(f"[WARN] {name}: {exc}", file=sys.stderr)
        time.sleep(0.3)
    records = merge_records(fresh, previous.get("records") or [])
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    result = {"updated_at": now, "records": records, "source_status": statuses}
    DATA_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    render_dashboard(result)
    print(f"Updated {HTML_FILE.name}: {len(records)} records")
    return 0 if any(s["ok"] for s in statuses.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
