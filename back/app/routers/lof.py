"""LOF 基金相关 API 路由"""
import concurrent.futures
import logging

import pandas as pd
import requests
from fastapi import APIRouter, Query

from app.cache import update_cache_data, get_cached_lof_data
from app.services.fetcher import (
    fetch_spot_data,
    fetch_purchase_data,
    fetch_estimate_data,
    fetch_ths_kline,
    fetch_em_kline,
)
from app.utils.formatters import format_limit, format_amount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lof", tags=["LOF"])


@router.get("/history")
def get_lof_history(
    fund_code: str = Query(..., description="基金代码"),
    fund_name: str = Query("", description="基金名称"),
):
    """获取 LOF 基金历史数据（价格 + 净值 + 溢价率 + 成交额 + 场内份额）
    主数据源：同花顺 K-line（换手率基于场内份额，可直接算出场内份额）
    备用数据源：东方财富 K-line
    净值数据：东方财富 lsjz 接口
    """
    try:
        logger.info("获取基金 %s 历史数据...", fund_code)

        # 1. 获取历史行情（优先同花顺，备用东方财富）
        price_df = fetch_ths_kline(fund_code)
        source = "ths"
        secid = None
        if price_df is None:
            logger.warning("同花顺获取失败，尝试东方财富备用...")
            secid_prefix = "1" if fund_code.startswith(("5", "6", "9")) else "0"
            secid = f"{secid_prefix}.{fund_code}"
            price_df = fetch_em_kline(fund_code, secid)
            source = "em"
            if price_df is None:
                return {"code": 404, "msg": f"未找到基金 {fund_code} 的历史价格数据"}

        # 如果是东方财富数据源，用 f84 校准最新一天份额（同花顺不需要）
        if source == "em":
            try:
                qt_url = "https://push2.eastmoney.com/api/qt/stock/get"
                qt_params = {"secid": secid, "fields": "f84"}
                qt_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                }
                r = requests.get(qt_url, params=qt_params, headers=qt_headers, timeout=10)
                r.raise_for_status()
                qt_data = r.json()
                f84 = qt_data.get("data", {}).get("f84")
                if f84 is not None:
                    real_time_share = round(float(f84) / 10000, 2)
                    if not price_df.empty and price_df.loc[price_df.index[-1], "share_volume"] is not None:
                        old_val = price_df.loc[price_df.index[-1], "share_volume"]
                        price_df.loc[price_df.index[-1], "share_volume"] = real_time_share
                        logger.info("基金 %s 份额校准：%s -> %s (万份)", fund_code, old_val, real_time_share)
            except Exception as e:
                logger.warning("实时份额校准失败：%s", e)

        # 份额数据与日终结算一致，延后一天显示（T日收盘后结算，T+1日公布）
        price_df["share_volume"] = price_df["share_volume"].shift(1)

        # 计算场内新增和份额涨幅
        price_df["change_amount"] = (price_df["share_volume"] - price_df["share_volume"].shift(1)).round(2)
        price_df["change_pct"] = ((price_df["change_amount"] / price_df["share_volume"].shift(1)) * 100).round(3)

        # 2. 获取历史净值（东方财富 lsjz 接口）
        nav_url = "https://api.fund.eastmoney.com/f10/lsjz"
        nav_params = {
            "fundCode": fund_code,
            "pageIndex": "1",
            "pageSize": "120",
            "startDate": price_df["date"].min().strftime("%Y-%m-%d"),
            "endDate": price_df["date"].max().strftime("%Y-%m-%d"),
        }
        nav_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36",
            "Referer": "https://fund.eastmoney.com/",
        }

        nav_rows = []
        total_count = 0
        page = 1
        while True:
            nav_params["pageIndex"] = str(page)
            r = requests.get(nav_url, params=nav_params, headers=nav_headers, timeout=30)
            r.raise_for_status()
            nav_json = r.json()
            if page == 1:
                total_count = nav_json.get("TotalCount", 0)
            nav_list = nav_json.get("Data", {}).get("LSJZList", [])
            if not nav_list:
                break
            for item in nav_list:
                dwjz = item.get("DWJZ", "")
                nav_rows.append({
                    "nav_date": item["FSRQ"],
                    "nav": float(dwjz) if dwjz else None,
                })
            page += 1
            if len(nav_rows) >= total_count:
                break

        nav_df = pd.DataFrame(nav_rows) if nav_rows else pd.DataFrame(columns=["nav_date", "nav"])
        nav_df["nav_date"] = pd.to_datetime(nav_df["nav_date"])

        # 3. 合并价格和净值（每个交易日只使用上一个交易日的净值，与集思录保持一致）
        nav_df = nav_df.sort_values("nav_date").dropna(subset=["nav"])

        # 获取上一个交易日的日期（price_df 已按日期升序排列）
        price_df["prev_date"] = price_df["date"].shift(1)

        # 合并上一个交易日的净值
        merged = price_df.merge(
            nav_df[["nav_date", "nav"]],
            left_on="prev_date",
            right_on="nav_date",
            how="left"
        )

        # 4. 计算溢价率
        merged["premium_rate"] = (
            (merged["price"] - merged["nav"]) / merged["nav"] * 100
        ).round(2)

        # 5. 格式化输出
        merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
        merged["nav_date"] = merged["prev_date"].apply(
            lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else None
        )

        result = merged[["date", "price", "nav_date", "nav", "premium_rate",
                         "turnover", "share_volume", "change_amount", "change_pct"]].copy()
        result.columns = ["date", "price", "navDate", "nav", "premiumRate",
                          "turnover", "shareVolume", "changeAmount", "changePct"]

        # 处理 NaN（确保 float NaN 也被替换为 None，避免 JSON 序列化失败）
        result = result.where(pd.notnull(result), None)
        result = result.replace({pd.NA: None, float('nan'): None})
        # 逐行逐列确保彻底清除 NaN
        data = []
        for record in result.to_dict(orient="records"):
            clean = {}
            for k, v in record.items():
                if isinstance(v, float) and (v != v):  # NaN check
                    clean[k] = None
                else:
                    clean[k] = v
            data.append(clean)
        data.reverse()  # 最新的在前

        logger.info("基金 %s 历史数据返回成功，共 %d 条", fund_code, len(data))
        return {"code": 200, "data": data, "fundCode": fund_code, "fundName": fund_name}

    except Exception as e:
        logger.exception("获取历史数据失败")
        return {"code": 500, "msg": f"获取历史数据失败：{str(e)}"}


@router.get("")
def get_lof_data():
    """获取 LOF 实时数据 + 溢价率 + 限额"""
    try:
        logger.info("开始获取 LOF 数据...")

        # 1. 并行获取三个数据源（串行→并行，总耗时从 ~9s 降至 ~3-4s）
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_spot = executor.submit(fetch_spot_data)
            future_purchase = executor.submit(fetch_purchase_data)
            future_estimate = executor.submit(fetch_estimate_data)

            spot = future_spot.result(timeout=30)
            logger.info("LOF 实时数据获取成功，共 %d 条", len(spot))

            purchase = future_purchase.result(timeout=30)
            logger.info("基金净值/限额数据获取成功，共 %d 条", len(purchase))

            estimate = future_estimate.result(timeout=30)
            logger.info("基金估算净值获取成功（仅LOF），共 %d 条", len(estimate))

        # 1.5 提取 LOF 代码列表，提前过滤以减少后续合并计算量
        lof_codes = set(spot["代码"].astype(str).tolist())
        purchase = purchase[purchase["基金代码"].astype(str).isin(lof_codes)]
        estimate = estimate[estimate["基金代码"].astype(str).isin(lof_codes)]
        logger.info("过滤后：净值/限额 %d 条，估算净值 %d 条", len(purchase), len(estimate))

        # 3. 合并数据
        df = spot.merge(
            purchase,
            left_on="代码",
            right_on="基金代码",
            how="left"
        ).merge(
            estimate,
            left_on="代码",
            right_on="基金代码",
            how="left"
        )

        # 4. 计算溢价率
        # 静态溢价率：基于最新公布的收盘净值（通常是昨日）
        df["溢价率"] = (
            (df["最新价"] - df["最新净值/万份收益"])
            / df["最新净值/万份收益"]
            * 100
        ).round(2)

        # 动态溢价率（估算溢价率）：基于实时估算净值，交易时间内更真实
        df["估算溢价率"] = (
            (df["最新价"] - df["估算净值"])
            / df["估算净值"]
            * 100
        ).round(2)

        # 5. 格式化限额
        df["限额"] = df["日累计限定金额"].apply(format_limit)

        # 6. 格式化总市值和成交额
        df["总市值_格式化"] = df["总市值"].apply(format_amount)
        df["成交额_格式化"] = df["成交额"].apply(format_amount)

        # 7. 只保留需要的字段
        df = df[[
            "代码", "名称", "最新价", "涨跌幅",
            "最新净值/万份收益", "估算净值", "溢价率", "估算溢价率",
            "限额", "申购状态",
            "总市值_格式化", "成交量", "成交额_格式化"
        ]]

        # 8. 格式化字段名（给前端用）
        df.columns = [
            "fundCode",
            "fundName",
            "tradePrice",
            "increaseRate",
            "netValue",
            "estimateValue",
            "premiumRate",
            "estimatePremiumRate",
            "purchaseLimit",
            "purchaseStatus",
            "fundSize",
            "volume",
            "turnover"
        ]

        # 8. 处理 NaN 值，避免 JSON 序列化失败
        df = df.replace({pd.NA: "-"})
        df = df.where(pd.notnull(df), "-")

        # 9. 转成 JSON 格式
        data = df.to_dict(orient="records")
        update_cache_data(data)
        logger.info("数据返回成功，共 %d 条", len(data))
        return {"code": 200, "data": data}

    except concurrent.futures.TimeoutError:
        logger.error("请求 akshare 数据源超时（超过 30 秒）")
        cached = get_cached_lof_data()
        if cached:
            logger.info("返回缓存数据，缓存时间：%s", cached["time"])
            return {"code": 200, "data": cached["data"], "cached": True}
        return {"code": 500, "msg": "数据获取超时，请稍后重试"}

    except Exception as e:
        logger.exception("数据获取失败")
        cached = get_cached_lof_data()
        if cached:
            logger.info("返回缓存数据，缓存时间：%s", cached["time"])
            return {"code": 200, "data": cached["data"], "cached": True}
        return {"code": 500, "msg": f"数据获取失败：{str(e)}"}