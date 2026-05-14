from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import akshare as ak
import pandas as pd
import logging
import concurrent.futures
import requests
import json
import re

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# 缓存最近一次成功的数据
cache_data = {"data": [], "time": None}

# 净值/限额数据缓存（该数据变化频率低，缓存 5 分钟）
purchase_cache = {"data": None, "time": None}
PURCHASE_CACHE_TTL_SECONDS = 300  # 5 分钟

# 解决跨域，让 Vue 能调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_limit(value):
    """格式化限额显示"""
    if pd.isna(value):
        return "-"
    if value == 0:
        return "-"
    if value >= 1e8:
        return "不限"
    if value < 10000:
        return f"{value:.0f}元/日"
    return f"{value / 10000:.0f}万/日"


def format_amount(value):
    """格式化金额：成交额/总市值"""
    if pd.isna(value):
        return "-"
    if value >= 1e8:
        return f"{value / 1e8:.2f}亿"
    if value >= 1e4:
        return f"{value / 1e4:.2f}万"
    return f"{value:.0f}"


def fetch_spot_data():
    """获取 LOF 实时交易数据（直接请求东方财富接口，绕过 akshare 失效域名）"""
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    base_params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f3",
        "fs": "b:MK0404,b:MK0405,b:MK0406,b:MK0407",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
    }

    # 获取第一页
    r = requests.get(url, params=base_params, timeout=30)
    r.raise_for_status()
    data_json = r.json()
    per_page_num = len(data_json["data"]["diff"])
    total_page = (data_json["data"]["total"] + per_page_num - 1) // per_page_num

    temp_list = [pd.DataFrame(data_json["data"]["diff"])]

    # 获取剩余页面
    for page in range(2, total_page + 1):
        params = base_params.copy()
        params["pn"] = str(page)
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data_json = r.json()
        temp_list.append(pd.DataFrame(data_json["data"]["diff"]))

    temp_df = pd.concat(temp_list, ignore_index=True)
    temp_df.rename(
        columns={
            "f12": "代码",
            "f14": "名称",
            "f2": "最新价",
            "f4": "涨跌额",
            "f3": "涨跌幅",
            "f5": "成交量",
            "f6": "成交额",
            "f17": "开盘价",
            "f15": "最高价",
            "f16": "最低价",
            "f18": "昨收",
            "f20": "总市值",
        },
        inplace=True,
    )
    # 数值类型转换
    numeric_cols = ["最新价", "涨跌额", "涨跌幅", "成交量", "成交额", "开盘价", "最高价", "最低价", "昨收", "总市值"]
    for col in numeric_cols:
        if col in temp_df.columns:
            temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
    return temp_df


def fetch_purchase_data():
    """获取基金净值和限额信息（直接调用东方财富 API，用 json.loads 替代 demjson 解析）"""
    global purchase_cache
    # 检查缓存是否有效
    if purchase_cache["data"] is not None and purchase_cache["time"] is not None:
        elapsed = (pd.Timestamp.now() - purchase_cache["time"]).total_seconds()
        if elapsed < PURCHASE_CACHE_TTL_SECONDS:
            logger.info("使用缓存的净值/限额数据，缓存已 %.0f 秒", elapsed)
            return purchase_cache["data"].copy()

    url = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    params = {
        "t": "8",
        "page": "1,50000",
        "js": "reData",
        "sort": "fcode,asc",
    }
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36",
        "Referer": "https://fund.eastmoney.com/",
    }

    try:
        r = requests.get(url, params=params, headers=req_headers, timeout=30)
        r.raise_for_status()
        data_text = r.text

        # 去除 JS 包装 var reData=...;  → 纯 JSON
        clean_text = data_text.strip()
        if clean_text.startswith("var reData="):
            clean_text = clean_text[len("var reData="):]
        clean_text = clean_text.rstrip(";")

        # 给无引号的 key 加双引号，变成合法 JSON，再用 json.loads（C 实现）解析
        # 比 akshare 用的 demjson.decode（纯 Python）快 ~150 倍
        valid_json = re.sub(r'([{,]\s*)(\w+)\s*:', r'\1"\2":', clean_text)
        data_json = json.loads(valid_json)

        temp_df = pd.DataFrame(data_json["datas"])
        # datas 列顺序：0基金代码 1基金简称 2基金类型 3最新净值 4净值时间 5申购状态 6赎回状态
        #              7下一开放日 8购买起点 9日累计限定金额 10- 11- 12手续费
        result = temp_df.iloc[:, [0, 3, 9, 5]].copy()
        result.columns = ["基金代码", "最新净值/万份收益", "日累计限定金额", "申购状态"]
        result["最新净值/万份收益"] = pd.to_numeric(result["最新净值/万份收益"], errors="coerce")
        result["日累计限定金额"] = pd.to_numeric(result["日累计限定金额"], errors="coerce")
    except Exception as e:
        logger.warning("直接解析净值/限额数据失败：%s，回退到 akshare", e)
        df = ak.fund_purchase_em()
        result = df[["基金代码", "最新净值/万份收益", "日累计限定金额", "申购状态"]]

    # 更新缓存
    purchase_cache = {"data": result, "time": pd.Timestamp.now()}
    return result.copy()


def fetch_estimate_data():
    """获取基金实时估算净值（全量获取后过滤 LOF，确保不遗漏跨分类基金）"""
    try:
        url = "https://api.fund.eastmoney.com/FundGuZhi/GetFundGZList"
        params = {
            "type": "1",  # 全部类型，避免 LOF 基金被归到其他分类而遗漏
            "sort": "3",
            "orderType": "desc",
            "canbuy": "0",
            "pageIndex": "1",
            "pageSize": "50000",
            "_": str(int(pd.Timestamp.now().timestamp() * 1000)),
        }
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36",
            "Referer": "https://fund.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=req_headers, timeout=30)
        r.raise_for_status()
        json_data = r.json()

        data_list = json_data["Data"]["list"]
        if not data_list:
            logger.warning("估算净值返回空数据")
            return pd.DataFrame(columns=["基金代码", "估算净值"])

        temp_df = pd.DataFrame(data_list)
        # API 返回 30 列，只取：列0=基金代码，列20=估算净值
        result = temp_df.iloc[:, [0, 20]].copy()
        result.columns = ["基金代码", "估算净值"]
        result["估算净值"] = pd.to_numeric(result["估算净值"], errors="coerce")
        return result
    except Exception as e:
        logger.warning("获取估算净值失败：%s，回退到 akshare", e)
        try:
            df = ak.fund_value_estimation_em()
            estimate_col = [c for c in df.columns if "估算数据-估算值" in c]
            if not estimate_col:
                return pd.DataFrame(columns=["基金代码", "估算净值"])
            df = df.rename(columns={estimate_col[0]: "估算净值"})
            df["估算净值"] = pd.to_numeric(df["估算净值"], errors="coerce")
            return df[["基金代码", "估算净值"]].copy()
        except Exception as e2:
            logger.warning("akshare 估算净值也失败：%s", e2)
            return pd.DataFrame(columns=["基金代码", "估算净值"])


@app.get("/api/lof")
def get_lof_data():
    """获取 LOF 实时数据 + 溢价率 + 限额"""
    global cache_data
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
        cache_data = {"data": data, "time": pd.Timestamp.now()}
        logger.info("数据返回成功，共 %d 条", len(data))
        return {"code": 200, "data": data}

    except concurrent.futures.TimeoutError:
        logger.error("请求 akshare 数据源超时（超过 30 秒）")
        if cache_data["data"]:
            logger.info("返回缓存数据，缓存时间：%s", cache_data["time"])
            return {"code": 200, "data": cache_data["data"], "cached": True}
        return {"code": 500, "msg": "数据获取超时，请稍后重试"}

    except Exception as e:
        logger.exception("数据获取失败")
        if cache_data["data"]:
            logger.info("返回缓存数据，缓存时间：%s", cache_data["time"])
            return {"code": 200, "data": cache_data["data"], "cached": True}
        return {"code": 500, "msg": f"数据获取失败：{str(e)}"}