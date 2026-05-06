from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import akshare as ak
import pandas as pd

app = FastAPI()

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


@app.get("/api/lof")
def get_lof_data():
    """获取 LOF 实时数据 + 溢价率 + 限额"""
    try:
        # 1. 获取 LOF 实时交易数据
        spot = ak.fund_lof_spot_em()

        # 2. 获取基金净值和限额信息
        purchase = ak.fund_purchase_em()
        purchase = purchase[["基金代码", "最新净值/万份收益", "日累计限定金额", "申购状态"]]

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
        return {"code": 200, "data": data}

    except Exception as e:
        return {"code": 500, "msg": f"数据获取失败：{str(e)}"}