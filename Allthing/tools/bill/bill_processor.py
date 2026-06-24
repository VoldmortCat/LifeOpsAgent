import sys
import os
import re
import logging
import pandas as pd
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.config_loader import config

logger = logging.getLogger("lifeops.bill_processor")

SKIP_HEADER_ROWS = config.get("bill.skip_header_rows", 17)
REQUIRED_FIELDS = config.get("bill.output.required_fields", [
    "交易时间","交易类型","交易对方","商品","收/支","金额(元)",
    "支付方式","当前状态","交易单号","商户单号","备注","交易日期","交易月份"
])
COL_MAP = {
    k: config.get(f"bill.columns.{v.lower()}", v)
    for k, v in {
        "trade_time":"交易时间","trade_type":"交易类型","trade_opposite":"交易对方",
        "commodity":"商品","income_outcome":"收/支","amount":"金额(元)",
        "pay_method":"支付方式","status":"当前状态","trade_id":"交易单号",
        "merchant_id":"商户单号","note":"备注","trade_date":"交易日期","trade_month":"交易月份"
    }.items()
}
OUTPUT_FOLDER = config.get("bill.output.folder", "data/bills")

class WxBillAnalyze:
    def __init__(self, file_path):
        self.file_path = file_path
        self.output_dir = Path(OUTPUT_FOLDER)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.df = self._load_and_clean()
        self._split_by_month()

    def _load_and_clean(self):
        df = pd.read_excel(self.file_path, skiprows=SKIP_HEADER_ROWS, engine="openpyxl")
        df.columns = [c.strip() for c in df.columns]
        amt_col = COL_MAP.get("amount", "金额(元)")
        df[amt_col] = df[amt_col].astype(str).str.replace("¥", "").str.strip()
        df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce")
        time_col = COL_MAP.get("trade_time", "交易时间")
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        date_col = COL_MAP.get("trade_date", "交易日期")
        df[date_col] = df[time_col].dt.date
        month_col = COL_MAP.get("trade_month", "交易月份")
        df[month_col] = df[time_col].dt.to_period("M")
        id_col = COL_MAP.get("trade_id", "交易单号")
        mid_col = COL_MAP.get("merchant_id", "商户单号")
        df = df.dropna(subset=[amt_col, time_col])
        for f in REQUIRED_FIELDS:
            if f not in df.columns: df[f] = ""
        return df[REQUIRED_FIELDS].copy()

    def _split_by_month(self):
        month_col = COL_MAP.get("trade_month", "交易月份")
        id_col = COL_MAP.get("trade_id", "交易单号")
        mid_col = COL_MAP.get("merchant_id", "商户单号")
        amt_col = COL_MAP.get("amount", "金额(元)")
        time_col = COL_MAP.get("trade_time", "交易时间")
        for month, gdf in self.df.groupby(month_col):
            ms = str(month).replace("-", "")
            csv_path = self.output_dir / f"{ms}.csv"
            if csv_path.exists():
                existing = pd.read_csv(csv_path, encoding="utf-8-sig", parse_dates=[time_col])
                for f in REQUIRED_FIELDS:
                    if f not in existing.columns: existing[f] = ""
                existing = existing[REQUIRED_FIELDS].copy()
                combined = pd.concat([existing, gdf], ignore_index=True)
                combined = combined.drop_duplicates(
                    subset=[id_col, mid_col, time_col, amt_col], keep="last"
                )
            else:
                combined = gdf.copy()
            combined[time_col] = pd.to_datetime(combined[time_col])
            combined = combined.sort_values(by=time_col, ascending=True)
            combined.to_csv(csv_path, index=False, encoding="utf-8-sig")
            logger.info("月度数据已保存：%s", csv_path)

    def show_core_stats(self):
        io_col = COL_MAP.get("income_outcome", "收/支")
        inc = config.get("bill.values.income", "收入")
        exp = config.get("bill.values.outcome", "支出")
        amt_col = COL_MAP.get("amount", "金额(元)")
        idf = self.df[self.df[io_col] == inc]
        edf = self.df[self.df[io_col] == exp]
        logger.info("微信账单统计 | 总收入：%.2f 元（%d笔）| 总支出：%.2f 元（%d笔）| 总笔数：%d",
                    idf[amt_col].sum(), len(idf),
                    edf[amt_col].sum(), len(edf),
                    len(self.df))

    def get_standardized_df(self):
        return self.df.copy()
