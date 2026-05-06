from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import akshare as ak
import pandas as pd
import logging
import concurrent.futures
import requests

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# 缓存最近一次成功的数据
cache_data = {"data": [], "time": None}

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
        "pz": "100",
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
    """获取基金净值和限额信息"""
    df = ak.fund_purchase_em()
    return df[["基金代码", "最新净值/万份收益", "日累计限定金额", "申购状态"]]


@app.get("/api/lof")
def get_lof_data():
    """获取 LOF 实时数据 + 溢价率 + 限额"""
    global cache_data
    try:
        logger.info("开始获取 LOF 数据...")

        # 1. 获取 LOF 实时交易数据（带 30 秒超时）
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fetch_spot_data)
            spot = future.result(timeout=30)
        logger.info("LOF 实时数据获取成功，共 %d 条", len(spot))

        # 2. 获取基金净值和限额信息（带 30 秒超时）
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fetch_purchase_data)
            purchase = future.result(timeout=30)
        logger.info("基金净值/限额数据获取成功，共 %d 条", len(purchase))

        # 3. 合并数据
        df = spot.merge(
            purchase,
            left_on="代码",
            right_on="基金代码",
            how="left"
        )

        # 4. 计算溢价率
        df["溢价率"] = (
            (df["最新价"] - df["最新净值/万份收益"])
            / df["最新净值/万份收益"]
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
            "最新净值/万份收益", "溢价率", "限额", "申购状态",
            "总市值_格式化", "成交量", "成交额_格式化"
        ]]

        # 8. 格式化字段名（给前端用）
        df.columns = [
            "fundCode",
            "fundName",
            "tradePrice",
            "increaseRate",
            "netValue",
            "premiumRate",
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