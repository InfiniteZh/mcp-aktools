import os
import time
import json
import logging
import akshare as ak
import argparse
import requests
import pandas as pd
from fastmcp import FastMCP
from pydantic import Field
from datetime import datetime, timedelta
from starlette.middleware.cors import CORSMiddleware
from .cache import CacheKey
from .contracts import (
    advice_response,
    dataframe_rows,
    entity_profile_response,
    error_response,
    news_list_response,
    normalize_mapping,
    normalize_value,
    profile_from_frame,
    search_result_response,
    snapshot_response,
    table_response,
    timeseries_response,
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)

mcp = FastMCP(name="mcp-aktools", version="0.1.15")

field_symbol = Field(description="股票代码")
field_market = Field("sh", description="股票市场，仅支持: sh(上证), sz(深证), hk(港股), us(美股), 不支持加密货币")

OKX_BASE_URL = os.getenv("OKX_BASE_URL") or "https://www.okx.com"
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL") or "https://www.binance.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10) AppleWebKit/537.36 Chrome/139"


@mcp.tool(
    title="查找股票代码",
    description="根据股票名称、公司名称等关键词查找股票代码, 不支持加密货币。"
                "该工具比较耗时，当你知道股票代码或用户已指定股票代码时，建议直接通过股票代码使用其他工具",
)
def search(
    keyword: str = Field(description="搜索关键词，公司名称、股票名称、股票代码、证券简称"),
    market: str = field_market,
):
    info = ak_search(None, keyword, market)
    if info is not None:
        return search_result_response(
            keyword,
            market,
            series_payload(info, market=market),
            source="akshare",
        )
    return error_response(
        "search_result",
        "NOT_FOUND",
        f"No match found for query '{keyword}' in market '{market}'",
        source="akshare",
        meta={"query": keyword, "market": market},
    )


@mcp.tool(
    title="获取股票信息",
    description="根据股票代码和市场获取股票基本信息, 不支持加密货币",
)
def stock_info(
    symbol: str = field_symbol,
    market: str = field_market,
):
    markets = [
        ["sh", ak.stock_individual_info_em],
        ["sz", ak.stock_individual_info_em],
        ["hk", ak.stock_hk_security_profile_em],
    ]
    for m in markets:
        if m[0] != market:
            continue
        all = ak_cache(m[1], symbol=symbol, ttl=43200)
        if all is None or all.empty:
            continue
        return entity_profile_response(
            symbol,
            market,
            profile_from_frame(all),
            source="akshare",
        )

    info = ak_search(symbol=symbol, market=market)
    if info is not None:
        return entity_profile_response(
            symbol,
            market,
            series_payload(info, market=market),
            source="akshare",
            meta={"matched_by": "search_index"},
        )
    return error_response(
        "entity_profile",
        "NOT_FOUND",
        f"No profile found for symbol '{symbol}' in market '{market}'",
        source="akshare",
        meta={"symbol": symbol, "market": market},
    )


@mcp.tool(
    title="获取股票历史价格",
    description="根据股票代码和市场获取股票历史价格及技术指标, 不支持加密货币",
)
def stock_prices(
    symbol: str = field_symbol,
    market: str = field_market,
    period: str = Field("daily", description="周期，如: daily(日线), weekly(周线，不支持美股)"),
    limit: int = Field(30, description="返回数量(int)", strict=False),
):
    if period == "weekly":
        delta = {"weeks": limit + 62}
    else:
        delta = {"days": limit + 62}
    start_date = (datetime.now() - timedelta(**delta)).strftime("%Y%m%d")
    markets = [
        ["sh", ak.stock_zh_a_hist, {}],
        ["sz", ak.stock_zh_a_hist, {}],
        ["hk", ak.stock_hk_hist, {}],
        ["us", stock_us_daily, {}],
        ["sh", fund_etf_hist_sina, {"market": "sh"}],
        ["sz", fund_etf_hist_sina, {"market": "sz"}],
    ]
    for m in markets:
        if m[0] != market:
            continue
        kws = {"period": period, "start_date": start_date, **m[2]}
        dfs = ak_cache(m[1], symbol=symbol, ttl=3600, **kws)
        if dfs is None or dfs.empty:
            continue
        add_technical_indicators(dfs, dfs["收盘"], dfs["最低"], dfs["最高"])
        items = timeseries_items(
            dfs,
            {
                "日期": "time",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "换手率": "turnover_rate",
                "MACD": "macd",
                "DIF": "dif",
                "DEA": "dea",
                "KDJ.K": "kdj_k",
                "KDJ.D": "kdj_d",
                "KDJ.J": "kdj_j",
                "RSI": "rsi",
                "BOLL.U": "boll_upper",
                "BOLL.M": "boll_middle",
                "BOLL.L": "boll_lower",
            },
            limit=limit,
        )
        return timeseries_response(
            symbol,
            items,
            source="akshare",
            market=market,
            interval=period,
            meta={"requested_limit": limit},
        )
    return error_response(
        "timeseries",
        "NOT_FOUND",
        f"No price history found for symbol '{symbol}' in market '{market}'",
        source="akshare",
        meta={"symbol": symbol, "market": market, "interval": period},
    )


def stock_us_daily(symbol, start_date="2025-01-01", period="daily"):
    dfs = ak.stock_us_daily(symbol=symbol)
    if dfs is None or dfs.empty:
        return None
    dfs.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"}, inplace=True)
    dfs["换手率"] = None
    dfs.index = pd.to_datetime(dfs["日期"], errors="coerce")
    return dfs[start_date:"2222-01-01"]

def fund_etf_hist_sina(symbol, market="sh", start_date="2025-01-01", period="daily"):
    dfs = ak.fund_etf_hist_sina(symbol=f"{market}{symbol}")
    if dfs is None or dfs.empty:
        return None
    dfs.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"}, inplace=True)
    dfs["换手率"] = None
    dfs.index = pd.to_datetime(dfs["日期"], errors="coerce")
    return dfs[start_date:"2222-01-01"]


@mcp.tool(
    title="获取股票/加密货币相关新闻",
    description="根据股票代码或加密货币符号获取近期相关新闻",
)
def stock_news(
    symbol: str = Field(description="股票代码/加密货币符号"),
    limit: int = Field(15, description="返回数量(int)", strict=False),
):
    dfs = ak_cache(stock_news_em, symbol=symbol, ttl=3600)
    items = dedupe_news_items(
        [news_item_from_row(row, symbol=symbol) for row in dataframe_rows(dfs, limit=limit)]
    )
    if items:
        return news_list_response(
            symbol,
            items,
            source="eastmoney",
            meta={"requested_limit": limit},
        )
    return error_response(
        "news_list",
        "NOT_FOUND",
        f"No news found for symbol '{symbol}'",
        source="eastmoney",
        meta={"symbol": symbol, "requested_limit": limit},
    )

def stock_news_em(symbol, limit=20):
    cbk = "jQuery351013927587392975826_1763361926020"
    resp = requests.get(
        "http://search-api-web.eastmoney.com/search/jsonp",
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://so.eastmoney.com/news/s?keyword={symbol}",
        },
        params={
            "cb": cbk,
            "param": '{"uid":"",'
                     f'"keyword":"{symbol}",'
                     '"type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr",'
                     '"param":{"cmsArticleWebOld":{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":10,'
                     '"preTag":"<em>","postTag":"</em>"}}}',
        },
    )
    text = resp.text.replace(cbk, "").strip().strip("()")
    data = json.loads(text) or {}
    dfs = pd.DataFrame(data.get("result", {}).get("cmsArticleWebOld") or [])
    if dfs.empty:
        return dfs
    dfs.sort_values("date", ascending=False, inplace=True)
    dfs = dfs.head(limit).copy()
    if "content" in dfs:
        dfs["content"] = dfs["content"].str.replace(r"</?em>", "", regex=True)
    if "title" in dfs:
        dfs["title"] = dfs["title"].str.replace(r"</?em>", "", regex=True)
    if "date" in dfs:
        dfs["published_at"] = dfs["date"]
    if "mediaName" in dfs:
        dfs["source"] = dfs["mediaName"]
    elif "media_name" in dfs:
        dfs["source"] = dfs["media_name"]
    if "articleUrl" in dfs and "url" not in dfs:
        dfs["url"] = dfs["articleUrl"]
    return dfs


@mcp.tool(
    title="A股关键指标",
    description="获取中国A股市场(上证、深证)的股票财务报告关键指标",
)
def stock_indicators_a(
    symbol: str = field_symbol,
):
    dfs = ak_cache(ak.stock_financial_abstract_ths, symbol=symbol)
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No financial indicators found for symbol '{symbol}'",
            source="akshare",
            meta={"symbol": symbol},
        )
    return table_response(
        "stock_indicators_a",
        dfs.tail(15),
        source="akshare",
        meta={"symbol": symbol},
    )


@mcp.tool(
    title="港股关键指标",
    description="获取港股市场的股票财务报告关键指标",
)
def stock_indicators_hk(
    symbol: str = field_symbol,
):
    dfs = ak_cache(ak.stock_financial_hk_analysis_indicator_em, symbol=symbol, indicator="报告期")
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No financial indicators found for symbol '{symbol}'",
            source="akshare",
            meta={"symbol": symbol},
        )
    return table_response(
        "stock_indicators_hk",
        dfs.head(15),
        source="akshare",
        meta={"symbol": symbol},
    )


@mcp.tool(
    title="美股关键指标",
    description="获取美股市场的股票财务报告关键指标",
)
def stock_indicators_us(
    symbol: str = field_symbol,
):
    dfs = ak_cache(ak.stock_financial_us_analysis_indicator_em, symbol=symbol, indicator="单季报")
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No financial indicators found for symbol '{symbol}'",
            source="akshare",
            meta={"symbol": symbol},
        )
    return table_response(
        "stock_indicators_us",
        dfs.head(15),
        source="akshare",
        meta={"symbol": symbol},
    )


@mcp.tool(
    title="获取当前时间及A股交易日信息",
    description="获取当前系统时间及A股交易日信息，建议在调用其他需要日期参数的工具前使用该工具",
)
def get_current_time():
    now = datetime.now()
    week = "日一二三四五六日"[now.isoweekday()]
    snapshot = {
        "current_time": now.isoformat(),
        "weekday": f"星期{week}",
        "recent_trade_dates": [],
    }
    dfs = ak_cache(ak.tool_trade_date_hist_sina, ttl=43200)
    if dfs is not None:
        start = now.date() - timedelta(days=5)
        ended = now.date() + timedelta(days=5)
        snapshot["recent_trade_dates"] = [
            d.strftime("%Y-%m-%d")
            for d in dfs["trade_date"]
            if start <= d <= ended
        ]
    return snapshot_response(
        "current_time",
        snapshot,
        source="system",
        meta={"market_scope": "a_share"},
    )

def recent_trade_date():
    now = datetime.now().date()
    dfs = ak_cache(ak.tool_trade_date_hist_sina, ttl=43200)
    if dfs is None:
        return now
    dfs.sort_values("trade_date", ascending=False, inplace=True)
    for d in dfs["trade_date"]:
        if d <= now:
            return d
    return now


@mcp.tool(
    title="A股涨停股池",
    description="获取中国A股市场(上证、深证)的所有涨停股票",
)
def stock_zt_pool_em(
    date: str = Field("", description="交易日日期(可选)，默认为最近的交易日，格式: 20251231"),
    limit: int = Field(50, description="返回数量(int,30-100)", strict=False),
):
    if not date:
        date = recent_trade_date().strftime("%Y%m%d")
    dfs = ak_cache(ak.stock_zt_pool_em, date=date, ttl=1200)
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No limit-up pool data found for trade date '{date}'",
            source="akshare",
            meta={"trade_date": date},
        )
    cnt = len(dfs)
    try:
        dfs.drop(columns=["序号", "流通市值", "总市值"], inplace=True)
    except Exception:
        pass
    dfs.sort_values("成交额", ascending=False, inplace=True)
    dfs = dfs.head(int(limit))
    return table_response(
        "stock_zt_pool_em",
        dfs,
        source="akshare",
        meta={"trade_date": date, "total_count": cnt},
    )


@mcp.tool(
    title="A股强势股池",
    description="获取中国A股市场(上证、深证)的强势股池数据",
)
def stock_zt_pool_strong_em(
    date: str = Field("", description="交易日日期(可选)，默认为最近的交易日，格式: 20251231"),
    limit: int = Field(50, description="返回数量(int,30-100)", strict=False),
):
    if not date:
        date = recent_trade_date().strftime("%Y%m%d")
    dfs = ak_cache(ak.stock_zt_pool_strong_em, date=date, ttl=1200)
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No strong stock pool data found for trade date '{date}'",
            source="akshare",
            meta={"trade_date": date},
        )
    try:
        dfs.drop(columns=["序号", "流通市值", "总市值"], inplace=True)
    except Exception:
        pass
    dfs.sort_values("成交额", ascending=False, inplace=True)
    dfs = dfs.head(int(limit))
    return table_response(
        "stock_zt_pool_strong_em",
        dfs,
        source="akshare",
        meta={"trade_date": date},
    )


@mcp.tool(
    title="A股龙虎榜统计",
    description="获取中国A股市场(上证、深证)的龙虎榜个股上榜统计数据",
)
def stock_lhb_ggtj_sina(
    days: str = Field("5", description="统计最近天数，仅支持: [5/10/30/60]"),
    limit: int = Field(50, description="返回数量(int,30-100)", strict=False),
):
    dfs = ak_cache(ak.stock_lhb_ggtj_sina, symbol=days, ttl=3600)
    if dfs is None or dfs.empty:
        return error_response(
            "table",
            "NOT_FOUND",
            f"No ranking data found for recent days '{days}'",
            source="akshare",
            meta={"days": days},
        )
    dfs = dfs.head(int(limit))
    return table_response(
        "stock_lhb_ggtj_sina",
        dfs,
        source="akshare",
        meta={"days": days},
    )


@mcp.tool(
    title="A股板块资金流",
    description="获取中国A股市场(上证、深证)的行业资金流向数据",
)
def stock_sector_fund_flow_rank(
    days: str = Field("今日", description="天数，仅支持: {'今日','5日','10日'}，如果需要获取今日数据，请确保是交易日"),
    cate: str = Field("行业资金流", description="仅支持: {'行业资金流','概念资金流','地域资金流'}"),
):
    dfs = ak_cache(ak.stock_sector_fund_flow_rank, indicator=days, sector_type=cate, ttl=1200)
    if dfs is None:
        return error_response(
            "table",
            "UPSTREAM_ERROR",
            "Failed to fetch sector fund flow data",
            source="akshare",
            meta={"indicator": days, "sector_type": cate},
        )
    try:
        dfs.sort_values("今日涨跌幅", ascending=False, inplace=True)
        dfs.drop(columns=["序号"], inplace=True)
    except Exception:
        pass
    try:
        dfs = pd.concat([dfs.head(20), dfs.tail(20)])
        return table_response(
            "stock_sector_fund_flow_rank",
            dfs,
            source="akshare",
            meta={"indicator": days, "sector_type": cate},
        )
    except Exception as exc:
        return error_response(
            "table",
            "UPSTREAM_ERROR",
            str(exc),
            source="akshare",
            meta={"indicator": days, "sector_type": cate},
        )


@mcp.tool(
    title="全球财经快讯",
    description="获取最新的全球财经快讯",
)
def stock_news_global():
    news = []
    try:
        dfs = ak.stock_info_global_sina()
        for row in dataframe_rows(dfs):
            news.append(global_news_item_from_row(row, default_source="sina"))
    except Exception:
        pass
    news.extend(newsnow_news())
    news = dedupe_news_items(news)
    if news:
        return news_list_response(
            None,
            news,
            source="aggregated",
            meta={"upstream_sources": ["sina", "newsnow"]},
        )
    return error_response(
        "news_list",
        "NOT_FOUND",
        "No global finance news found",
        source="aggregated",
        meta={"upstream_sources": ["sina", "newsnow"]},
    )


def newsnow_news(channels=None):
    base = os.getenv("NEWSNOW_BASE_URL")
    if not base:
        return []
    if not channels:
        channels = os.getenv("NEWSNOW_CHANNELS") or "wallstreetcn-quick,cls-telegraph,jin10"
    if isinstance(channels, str):
        channels = channels.split(",")
    all = []
    try:
        res = requests.post(
            f"{base}/api/s/entire",
            json={"sources": channels},
            headers={
                "User-Agent": USER_AGENT,
                "Referer": base,
            },
            timeout=60,
        )
        lst = res.json() or []
        for item in lst:
            for v in item.get("items", [])[0:15]:
                title = v.get("title", "")
                extra = v.get("extra") or {}
                hover = extra.get("hover") or title
                info = extra.get("info") or ""
                all.append(
                    {
                        "title": sanitize_text(title or hover),
                        "content": sanitize_text(hover if hover != title else info),
                        "source": item.get("source") or item.get("name") or "newsnow",
                        "published_at": v.get("time") or v.get("published_at"),
                        "url": v.get("url") or extra.get("url"),
                        "channel": item.get("source") or item.get("name"),
                        "info": sanitize_text(info),
                    }
                )
    except Exception:
        pass
    return all


@mcp.tool(
    title="获取加密货币历史价格",
    description="获取OKX加密货币的历史K线数据，包括价格、交易量和技术指标",
)
def okx_prices(
    instId: str = Field("BTC-USDT", description="产品ID，格式: BTC-USDT"),
    bar: str = Field("1H", description="K线时间粒度，仅支持: [1m/3m/5m/15m/30m/1H/2H/4H/6H/12H/1D/2D/3D/1W/1M/3M] 除分钟为小写m外,其余均为大写"),
    limit: int = Field(100, description="返回数量(int)，最大300，最小建议30", strict=False),
):
    if not bar.endswith("m"):
        bar = bar.upper()
    res = requests.get(
        f"{OKX_BASE_URL}/api/v5/market/candles",
        params={
            "instId": instId,
            "bar": bar,
            "limit": min(300, limit + 62),
        },
        timeout=20,
    )
    data = res.json() or {}
    dfs = pd.DataFrame(data.get("data", []))
    if dfs.empty:
        return error_response(
            "timeseries",
            "NOT_FOUND",
            f"No OKX candle data found for instrument '{instId}'",
            source="okx",
            meta={"symbol": instId, "interval": bar},
        )
    dfs.columns = ["时间", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "成交额USDT", "K线已完结"]
    dfs.sort_values("时间", inplace=True)
    dfs["时间"] = pd.to_datetime(dfs["时间"], errors="coerce", unit="ms")
    dfs["开盘"] = pd.to_numeric(dfs["开盘"], errors="coerce")
    dfs["最高"] = pd.to_numeric(dfs["最高"], errors="coerce")
    dfs["最低"] = pd.to_numeric(dfs["最低"], errors="coerce")
    dfs["收盘"] = pd.to_numeric(dfs["收盘"], errors="coerce")
    dfs["成交量"] = pd.to_numeric(dfs["成交量"], errors="coerce")
    dfs["成交额"] = pd.to_numeric(dfs["成交额"], errors="coerce")
    add_technical_indicators(dfs, dfs["收盘"], dfs["最低"], dfs["最高"])
    columns = [
        "时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
        "MACD", "DIF", "DEA", "KDJ.K", "KDJ.D", "KDJ.J", "RSI", "BOLL.U", "BOLL.M", "BOLL.L",
    ]
    items = timeseries_items(
        dfs[columns],
        {
            "时间": "time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "MACD": "macd",
            "DIF": "dif",
            "DEA": "dea",
            "KDJ.K": "kdj_k",
            "KDJ.D": "kdj_d",
            "KDJ.J": "kdj_j",
            "RSI": "rsi",
            "BOLL.U": "boll_upper",
            "BOLL.M": "boll_middle",
            "BOLL.L": "boll_lower",
        },
        limit=limit,
    )
    return timeseries_response(
        instId,
        items,
        source="okx",
        market="crypto",
        interval=bar,
        meta={"requested_limit": limit},
    )


@mcp.tool(
    title="获取加密货币杠杆多空比",
    description="获取OKX加密货币借入计价货币与借入交易货币的累计数额比值",
)
def okx_loan_ratios(
    symbol: str = Field("BTC", description="币种，格式: BTC 或 ETH"),
    period: str = Field("1h", description="时间粒度，仅支持: [5m/1H/1D] 注意大小写，仅分钟为小写m"),
):
    res = requests.get(
        f"{OKX_BASE_URL}/api/v5/rubik/stat/margin/loan-ratio",
        params={
            "ccy": symbol,
            "period": period,
        },
        timeout=20,
    )
    data = res.json() or {}
    dfs = pd.DataFrame(data.get("data", []))
    if dfs.empty:
        return error_response(
            "timeseries",
            "NOT_FOUND",
            f"No OKX loan ratio data found for symbol '{symbol}'",
            source="okx",
            meta={"symbol": symbol, "interval": period},
        )
    dfs.columns = ["时间", "多空比"]
    dfs["时间"] = pd.to_datetime(dfs["时间"], errors="coerce", unit="ms")
    dfs["多空比"] = pd.to_numeric(dfs["多空比"], errors="coerce")
    return timeseries_response(
        symbol,
        timeseries_items(dfs, {"时间": "time", "多空比": "long_short_ratio"}),
        source="okx",
        market="crypto",
        interval=period,
    )


@mcp.tool(
    title="获取加密货币主动买卖情况",
    description="获取OKX加密货币主动买入和卖出的交易量",
)
def okx_taker_volume(
    symbol: str = Field("BTC", description="币种，格式: BTC 或 ETH"),
    period: str = Field("1h", description="时间粒度，仅支持: [5m/1H/1D] 注意大小写，仅分钟为小写m"),
    instType: str = Field("SPOT", description="产品类型 SPOT:现货 CONTRACTS:衍生品"),
):
    res = requests.get(
        f"{OKX_BASE_URL}/api/v5/rubik/stat/taker-volume",
        params={
            "ccy": symbol,
            "period": period,
            "instType": instType,
        },
        timeout=20,
    )
    data = res.json() or {}
    dfs = pd.DataFrame(data.get("data", []))
    if dfs.empty:
        return error_response(
            "timeseries",
            "NOT_FOUND",
            f"No OKX taker volume data found for symbol '{symbol}'",
            source="okx",
            meta={"symbol": symbol, "interval": period, "instrument_type": instType},
        )
    dfs.columns = ["时间", "卖出量", "买入量"]
    dfs["时间"] = pd.to_datetime(dfs["时间"], errors="coerce", unit="ms")
    dfs["卖出量"] = pd.to_numeric(dfs["卖出量"], errors="coerce")
    dfs["买入量"] = pd.to_numeric(dfs["买入量"], errors="coerce")
    return timeseries_response(
        symbol,
        timeseries_items(dfs, {"时间": "time", "卖出量": "sell_volume", "买入量": "buy_volume"}),
        source="okx",
        market="crypto",
        interval=period,
        meta={"instrument_type": instType},
    )


@mcp.tool(
    title="获取加密货币分析报告",
    description="获取币安对加密货币的AI分析报告，此工具对分析加密货币非常有用，推荐使用",
)
def binance_ai_report(
    symbol: str = Field("BTC", description="加密货币币种，格式: BTC 或 ETH"),
):
    res = requests.post(
        f"{BINANCE_BASE_URL}/bapi/bigdata/v3/friendly/bigdata/search/ai-report/report",
        json={
            'lang': 'zh-CN',
            'token': symbol,
            'symbol': f'{symbol}USDT',
            'product': 'web-spot',
            'timestamp': int(time.time() * 1000),
            'translateToken': None,
        },
        headers={
            'User-Agent': USER_AGENT,
            'Referer': f'https://www.binance.com/zh-CN/trade/{symbol}_USDT?type=spot',
            'lang': 'zh-CN',
        },
        timeout=20,
    )
    try:
        resp = res.json() or {}
    except Exception:
        try:
            resp = json.loads(res.text.strip()) or {}
        except Exception:
            txt = sanitize_text(res.text)
            if txt:
                return advice_response(
                    {"symbol": symbol, "analysis": [txt]},
                    source="binance",
                )
            return error_response(
                "advice",
                "UPSTREAM_ERROR",
                f"Failed to parse Binance AI report for symbol '{symbol}'",
                source="binance",
                meta={"symbol": symbol},
            )
    data = resp.get('data') or {}
    report = data.get('report') or {}
    translated = report.get('translated') or report.get('original') or {}
    modules = translated.get('modules') or []
    txts = []
    for module in modules:
        if tit := module.get('overview'):
            txts.append(tit)
        for point in module.get('points', []):
            txts.append(point.get('content', ''))
    txts = [sanitize_text(v) for v in txts if sanitize_text(v)]
    if txts:
        return advice_response(
            {"symbol": symbol, "analysis": txts},
            source="binance",
        )
    return error_response(
        "advice",
        "NOT_FOUND",
        f"No Binance AI report found for symbol '{symbol}'",
        source="binance",
        meta={"symbol": symbol},
    )


@mcp.tool(
    title="给出投资建议",
    description="基于AI对其他工具提供的数据分析结果给出具体投资建议",
)
def trading_suggest(
    symbol: str = Field(description="股票代码或加密币种"),
    action: str = Field(description="推荐操作: buy/sell/hold"),
    score: int = Field(description="置信度，范围: 0-100"),
    reason: str = Field(description="推荐理由"),
):
    return advice_response(
        {
            "symbol": symbol,
            "action": action,
            "score": score,
            "reason": reason,
        },
        source="user_input",
    )


def ak_search(symbol=None, keyword=None, market=None):
    markets = [
        ["sh", ak.stock_info_a_code_name, "code", "name"],
        ["sh", ak.stock_info_sh_name_code, "证券代码", "证券简称"],
        ["sz", ak.stock_info_sz_name_code, "A股代码", "A股简称"],
        ["hk", ak.stock_hk_spot, "代码", "中文名称"],
        ["hk", ak.stock_hk_spot_em, "代码", "名称"],
        ["us", ak.get_us_stock_name, "symbol", "cname"],
        ["us", ak.get_us_stock_name, "symbol", "name"],
        ["sh", ak.fund_etf_spot_ths, "基金代码", "基金名称"],
        ["sz", ak.fund_etf_spot_ths, "基金代码", "基金名称"],
        ["sh", ak.fund_info_index_em, "基金代码", "基金名称"],
        ["sz", ak.fund_info_index_em, "基金代码", "基金名称"],
        ["sh", ak.fund_etf_spot_em, "代码", "名称"],
        ["sz", ak.fund_etf_spot_em, "代码", "名称"],
    ]
    for m in markets:
        if market and market != m[0]:
            continue
        all = ak_cache(m[1], ttl=86400, ttl2=86400*7)
        if all is None or all.empty:
            continue
        for _, v in all.iterrows():
            code, name = str(v[m[2]]).upper(), str(v[m[3]]).upper()
            if symbol and symbol.upper() == code:
                return v
            if keyword and keyword.upper() in [code, name]:
                return v
        for _, v in all.iterrows() if keyword else []:
            name = str(v[m[3]])
            if len(keyword) >= 4 and keyword in name:
                return v
            if name.startswith(keyword):
                return v
    return None


def ak_cache(fun, *args, **kwargs) -> pd.DataFrame | None:
    key = kwargs.pop("key", None)
    if not key:
        key = f"{fun.__name__}-{args}-{kwargs}"
    ttl1 = kwargs.pop("ttl", 86400)
    ttl2 = kwargs.pop("ttl2", None)
    cache = CacheKey.init(key, ttl1, ttl2)
    all = cache.get()
    if all is None:
        try:
            _LOGGER.info("Request akshare: %s", [key, args, kwargs])
            all = fun(*args, **kwargs)
            cache.set(all)
        except Exception as exc:
            _LOGGER.exception(str(exc))
    return all

def add_technical_indicators(df, clos, lows, high):
    # 计算MACD指标
    ema12 = clos.ewm(span=12, adjust=False).mean()
    ema26 = clos.ewm(span=26, adjust=False).mean()
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2

    # 计算KDJ指标
    low_min  = lows.rolling(window=9, min_periods=1).min()
    high_max = high.rolling(window=9, min_periods=1).max()
    rsv = (clos - low_min) / (high_max - low_min) * 100
    df["KDJ.K"] = rsv.ewm(com=2, adjust=False).mean()
    df["KDJ.D"] = df["KDJ.K"].ewm(com=2, adjust=False).mean()
    df["KDJ.J"] = 3 * df["KDJ.K"] - 2 * df["KDJ.D"]

    # 计算RSI指标
    delta = clos.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # 计算布林带指标
    df["BOLL.M"] = clos.rolling(window=20).mean()
    std = clos.rolling(window=20).std()
    df["BOLL.U"] = df["BOLL.M"] + 2 * std
    df["BOLL.L"] = df["BOLL.M"] - 2 * std


def series_payload(series, market=None):
    if series is None:
        return None
    data = normalize_mapping(series.to_dict())
    if market:
        data.setdefault("market", market)
    symbol = pick_first(data, "code", "代码", "symbol", "A股代码", "证券代码", "基金代码")
    name = pick_first(data, "name", "名称", "中文名称", "证券简称", "A股简称", "基金名称", "cname")
    if symbol is not None:
        data.setdefault("symbol", symbol)
    if name is not None:
        data.setdefault("name", name)
    return data


def timeseries_items(frame, mapping, limit=None):
    if frame is None or frame.empty:
        return []
    data = frame.tail(int(limit)) if limit else frame
    items = []
    for _, row in data.iterrows():
        item = {}
        for source_key, target_key in mapping.items():
            if source_key in row:
                item[target_key] = normalize_value(row[source_key])
        items.append(item)
    return items


def sanitize_text(value):
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    return text or None


def pick_first(mapping, *keys):
    for key in keys:
        if key in mapping and mapping[key] not in [None, ""]:
            return mapping[key]
    return None


def news_item_from_row(row, symbol=None, default_source="eastmoney"):
    title = pick_first(row, "title", "标题", "新闻标题")
    content = pick_first(row, "content", "内容", "新闻内容", "summary", "摘要")
    published_at = pick_first(row, "published_at", "date", "时间", "发布时间")
    source = pick_first(row, "source", "来源", "媒体名称", "mediaName") or default_source
    url = pick_first(row, "url", "articleUrl", "链接")
    item = {
        "title": sanitize_text(title) or sanitize_text(content),
        "content": sanitize_text(content) or sanitize_text(title),
        "source": sanitize_text(source),
        "published_at": normalize_value(published_at),
        "url": sanitize_text(url),
    }
    if symbol:
        item["symbol"] = symbol
    raw = {k: v for k, v in normalize_mapping(row).items() if k not in {"title", "content", "source", "published_at", "url"}}
    if raw:
        item["raw"] = raw
    return item


def global_news_item_from_row(row, default_source="sina"):
    return news_item_from_row(row, default_source=default_source)


def dedupe_news_items(items):
    all_items = []
    seen = set()
    for item in items:
        if not item:
            continue
        title = sanitize_text(item.get("title"))
        content = sanitize_text(item.get("content"))
        if not title and not content:
            continue
        key = (title, content)
        if key in seen:
            continue
        seen.add(key)
        all_items.append(item)
    return all_items


def main():
    port = int(os.getenv("PORT", 0)) or 80
    parser = argparse.ArgumentParser(description="AkTools MCP Server")
    parser.add_argument("--http", action="store_true", help="Use streamable HTTP mode instead of stdio")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=port, help=f"Port to listen on (default: {port})")

    args = parser.parse_args()
    mode = os.getenv("TRANSPORT") or ("http" if args.http else None)
    if mode in ["http", "sse"]:
        app = mcp.http_app(transport=mode)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["mcp-session-id", "mcp-protocol-version"],
            max_age=86400,
        )
        mcp.run(transport=mode, host=args.host, port=args.port)
    else:
        mcp.run()

if __name__ == "__main__":
    main()
