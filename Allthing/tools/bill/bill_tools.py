import sys
import os
import json
import re
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.config_loader import config

IMAP_SERVER = config.get("email.imap_server", "imap.163.com")
EMAIL_USER = config.get("email.username", "")
EMAIL_PASS = config.get("email.password", "")
WATCH_FOLDER = config.get("email.watch_folder", "INBOX")
INPUT_DIR = config.get("paths.input_dir", "workspace/input")
UNZIP_DIR = config.get("paths.unzip_dir", "workspace/unzipped")
DATA_DIR = config.get("bill.output.folder", "data/bills")


def _decode_str(s):
    if not s:
        return ""
    from email.header import decode_header
    dh = decode_header(s)
    parts = [
        text.decode(enc or "utf-8", errors="ignore") if isinstance(text, bytes) else text
        for text, enc in dh
    ]
    return "".join(parts)


def _connect_email():
    import imaplib
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, port=993)
        mail.login(EMAIL_USER, EMAIL_PASS)
        imaplib.Commands["ID"] = ("AUTH",)
        args = ("name", "LifeOpsBot", "contact", EMAIL_USER, "version", "2.0.0", "vendor", "myclient")
        mail._simple_command("ID", '("' + '" "'.join(args) + '")')
        status, data = mail.select(WATCH_FOLDER)
        if status != "OK":
            return None, f"选择邮箱文件夹失败: {data[0].decode('utf-8')}"
        return mail, "连接成功"
    except Exception as e:
        return None, f"邮箱连接失败: {str(e)}"


def _process_single_email(mail, email_id):
    import imaplib, email
    from bs4 import BeautifulSoup
    try:
        status, data = mail.fetch(email_id, "(RFC822)")
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)
        from_ = _decode_str(msg.get("From", ""))
        subject = _decode_str(msg.get("Subject", ""))
        if "微信支付" not in from_ or "账单" not in subject:
            return "", "非微信支付账单邮件，跳过"
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode("utf-8")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8")
        download_link = None
        if body:
            soup = BeautifulSoup(body, "html.parser")
            for a in soup.find_all("a", href=True):
                if "download" in a["href"] or "wxpay" in a["href"]:
                    download_link = a["href"]
                    break
        if not download_link:
            mail.store(email_id, "+FLAGS", "\\Seen")
            return "", "未找到账单下载链接（纯通知邮件）"
        import requests
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(download_link, headers=headers, stream=True)
        if resp.status_code != 200:
            return None, f"下载失败（状态码：{resp.status_code}）"
        filename = subject.split(")")[0] + ").zip" if ")" in subject else f"微信账单_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
        os.makedirs(INPUT_DIR, exist_ok=True)
        filepath = os.path.join(INPUT_DIR, filename)
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return filepath, f"文件下载成功：{filepath}"
    except Exception as e:
        return "", f"处理邮件失败: {str(e)}"


@tool
def check_and_download_bill_email() -> str:
    """检查邮箱，下载微信支付账单邮件的附件。"""
    mail, msg = _connect_email()
    if not mail:
        return f"❌ {msg}"
    try:
        import imaplib
        status, data = mail.search(None, "UNSEEN")
        ids = data[0].split() if status == "OK" and data[0] else []
        results = [f"🔍 找到{len(ids)}封未读邮件"]
        if not ids:
            return "\n".join(results)
        results.append(f"📧 开始过滤{len(ids)}封邮件中的微信支付账单...")
        for eid in ids:
            _, pm = _process_single_email(mail, eid)
            results.append(f"  - 邮件ID {eid.decode()}: {pm}")
        return "\n".join(results)
    finally:
        mail.logout()


@tool
def unzip_latest_wechat_bill(password: str) -> str:
    """
    解压本地所有未处理的微信支付账单压缩文件。
    支持多密码尝试：用提供的密码 + 历史密码集合遍历所有 zip 文件。

    Args:
        password: 解压密码（必填，需要向用户询问）

    Returns:
        解压结果提示
    """
    if not password:
        return "❌ 请提供解压密码"
    import glob, zipfile, shutil
    
    zip_files = glob.glob(os.path.join(INPUT_DIR, "*.zip"))
    if not zip_files:
        return "❌ 未找到任何微信账单压缩文件"
    zip_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    password_candidates = [password]
    
    results = []
    success_count = 0
    fail_count = 0
    matched_passwords = set()
    
    for zip_file in zip_files:
        zip_success = False
        for pwd in password_candidates[:]:
            try:
                os.makedirs(UNZIP_DIR, exist_ok=True)
                
                existing_xlsx = set(f for f in os.listdir(UNZIP_DIR) 
                                   if f.lower().endswith(".xlsx") or f.lower().endswith(".xlsx.processed"))
                
                with zipfile.ZipFile(zip_file, "r") as zf:
                    zf.setpassword(pwd.encode("utf-8"))
                    zf.extractall(UNZIP_DIR)
                
                all_xlsx = [f for f in os.listdir(UNZIP_DIR) 
                           if f.lower().endswith(".xlsx") and not f.lower().endswith(".processed")]
                new_xlsx = [f for f in all_xlsx if f not in existing_xlsx]
                
                if new_xlsx:
                    from tools.bill.bill_processor import WxBillAnalyze
                    processed_count = 0
                    for xlsx_file in new_xlsx:
                        xlsx_path = os.path.join(UNZIP_DIR, xlsx_file)
                        analyzer = WxBillAnalyze(xlsx_path)
                        analyzer.show_core_stats()
                        processed_count += 1
                        processed_name = xlsx_path + ".processed"
                        if os.path.exists(processed_name):
                            os.remove(processed_name)
                        shutil.move(xlsx_path, processed_name)
                    results.append(f"✅ {os.path.basename(zip_file)}: 解压成功并已清洗数据（密码: {pwd}，处理了 {processed_count} 个 Excel 文件）")
                    results.append(f"   🏷️ 已标记 {processed_count} 个 Excel 文件为已处理")
                else:
                    results.append(f"✅ {os.path.basename(zip_file)}: 解压成功（无新 xlsx 文件，密码: {pwd}）")
                
                base_name = os.path.basename(zip_file)
                processed_name = os.path.join(os.path.dirname(zip_file), f"[{pwd}]{base_name}.processed")
                if os.path.exists(processed_name):
                    os.remove(processed_name)
                shutil.move(zip_file, processed_name)
                results.append(f"   🏷️ 已标记为已处理（密码: {pwd}）")
                success_count += 1
                matched_passwords.add(pwd)
                zip_success = True
                password_candidates.remove(pwd)
                results.append(f"   ⚡ 优化：密码 '{pwd}' 已匹配，从候选集合中剔除")
                break
                
            except Exception as e:
                if "Bad password" in str(e) or "password" in str(e).lower():
                    continue
                results.append(f"❌ {os.path.basename(zip_file)}: 解压失败 - {str(e)}")
                fail_count += 1
                break
        
        if not zip_success and (fail_count == 0 or "解压失败" not in results[-1]):
            results.append(f"❌ {os.path.basename(zip_file)}: 所有密码尝试失败（已尝试 {len(password_candidates)} 个密码）")
            fail_count += 1
    
    summary = f"📊 解压完成：共 {len(zip_files)} 个文件，成功 {success_count} 个，失败 {fail_count} 个"
    if matched_passwords:
        summary += f"\n🔑 成功使用的密码：{', '.join(matched_passwords)}"
    return summary + "\n" + "\n".join(results)


# ============================================================
# 内部函数：数据读取 & 统计
# ============================================================

def _compute_bill_stats(records: list) -> dict:
    """对账单记录做简单统计：总支出、总收入、日均支出。"""
    total_out = 0.0
    total_in = 0.0
    unique_days = set()

    for r in records:
        amt = float(r.get("金额(元)", 0) or 0)
        direction = r.get("收/支", "")
        date_str = str(r.get("交易时间", ""))[:10]

        if direction == "支出":
            total_out += amt
        else:
            total_in += amt
        if date_str:
            unique_days.add(date_str)

    days = max(len(unique_days), 1)
    count = len(records)
    return {
        "total_spending": round(total_out, 2),
        "total_income": round(total_in, 2),
        "record_count": count,
        "days_count": days,
        "daily_avg_spending": round(total_out / days, 2),
        "avg_amount": round(total_out / count, 2) if count else 0,
    }


def _read_monthly(month: str) -> pd.DataFrame:
    file_path = os.path.join(DATA_DIR, f"{month}.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"未找到月份 {month} 的数据文件")
    return pd.read_csv(file_path, encoding="utf-8-sig", parse_dates=["交易时间", "交易日期"])


def _parse_date(date_str: str) -> datetime:
    date_str = str(date_str).strip()

    patterns = [
        (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{4})/(\d{1,2})/(\d{1,2})$", lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{4})(\d{2})(\d{1,3})$", lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$", lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
    ]
    for pattern, handler in patterns:
        m = re.match(pattern, date_str)
        if m:
            return handler(m)
    raise ValueError(f"无法识别的日期格式：{date_str}，请使用 YYYY-MM-DD 格式")


def _read_date_range(start_date: str, end_date: str) -> pd.DataFrame:
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    months = []
    cur = start_dt
    while cur <= end_dt:
        m = cur.strftime("%Y%m")
        if m not in months:
            months.append(m)
        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1)
        else:
            cur = datetime(cur.year, cur.month + 1, 1)
    dfs = []
    for m in months:
        try:
            dfs.append(_read_monthly(m))
        except FileNotFoundError:
            pass
    if not dfs:
        raise ValueError("未找到任何数据文件")
    combined = pd.concat(dfs, ignore_index=True)
    combined["交易日期"] = pd.to_datetime(combined["交易日期"]).dt.date
    combined = combined[(combined["交易日期"] >= start_dt.date()) & (combined["交易日期"] <= end_dt.date())]
    combined = combined.sort_values(by="交易时间", ascending=True)
    return combined


# ============================================================
# LLM 工具：账单数据查询
# ============================================================


@tool
def get_date_range_bill_data(
    start_date: str,
    end_date: str,
    min_amount: float = None,
    max_amount: float = None,
) -> str:
    """
    获取指定日期范围内的账单数据（支持跨月自动合并、金额筛选）。

    核心能力（内部自动完成）：
    - 自动识别涉及的所有月份，逐月读取CSV并智能合并
    - 按精确日期范围过滤（精确到天，不是整月返回）
    - 按交易时间升序排列
    - 兼容多种常见日期格式输入

    Args:
        start_date: 开始日期，格式 "YYYY-MM-DD"，如 "2026-04-14"
        end_date: 结束日期，格式 "YYYY-MM-DD"，如 "2026-04-17"
        min_amount: 可选，只返回金额 ≥ 此值的记录（用于查大额支出，如高铁票/住宿）
        max_amount: 可选，只返回金额 ≤ 此值的记录（用于查日常小额消费）

    Returns:
        JSON字符串，含 __stats__ 汇总（总支出/总收入/日均/记录数）+ 筛选后的 data 记录列表

    使用示例：
    - "5月花了多少" → get_date_range_bill_data("2026-05-01", "2026-05-31")
    - "5月大额支出" → get_date_range_bill_data("2026-05-01", "2026-05-31", min_amount=50)
    - "5月超过100的" → get_date_range_bill_data("2026-05-01", "2026-05-31", min_amount=100)
    - "5月日常吃饭花了多少" → get_date_range_bill_data("2026-05-01", "2026-05-31", max_amount=30)
    """
    try:
        df = _read_date_range(start_date, end_date)
        records = df.to_dict(orient="records")
        for r in records:
            if "交易时间" in r and pd.notna(r["交易时间"]):
                if isinstance(r["交易时间"], (pd.Timestamp, datetime)):
                    r["交易时间"] = r["交易时间"].strftime("%Y-%m-%d %H:%M:%S")
            if "交易日期" in r and pd.notna(r["交易日期"]):
                r["交易日期"] = str(r["交易日期"])

        # 金额筛选
        if min_amount is not None:
            records = [r for r in records if float(r.get("金额(元)", 0) or 0) >= min_amount]
        if max_amount is not None:
            records = [r for r in records if float(r.get("金额(元)", 0) or 0) <= max_amount]

        stats = _compute_bill_stats(records)
        total_count = len(records)

        # 🚫 硬控：超过 100 条不返回明细，只返回统计 + 分页提示
        MAX_DETAIL = 100
        if total_count > MAX_DETAIL:
            result = {
                "start_date": start_date,
                "end_date": end_date,
                "__stats__": stats,
                "data_truncated": True,
                "total_records": total_count,
                "max_detail_limit": MAX_DETAIL,
                "hint": f"记录共 {total_count} 条，超过明细上限 {MAX_DETAIL} 条。请缩小查询范围（如按周查询），或使用 offset/limit 分页。",
                "data": [],
            }
        else:
            result = {
                "start_date": start_date,
                "end_date": end_date,
                "__stats__": stats,
                "data": records,
            }
        if min_amount is not None:
            result["filter_min_amount"] = min_amount
        if max_amount is not None:
            result["filter_max_amount"] = max_amount
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ 获取日期范围数据失败：{str(e)}"


# ============================================================
# LLM 工具：日常开销基线（预算计算专用）
# ============================================================


def _find_most_recent_complete_month(min_days: int = 7) -> str:
    """找到距离当前时间最近、且数据质量满足日常开销计算要求的月份。

    规则（按优先级）：
    1. 排除当前月（数据不完整）
    2. 从最近月份往前遍历，读取每个 CSV 的实际交易天数
    3. 返回第一个满足「交易天数 ≥ min_days」的月份
    4. 如果所有月份都不够 min_days → 返回实际天数最多的那个月（兜底）

    为什么需要这个检查：
    - 某个月 CSV 文件存在，但可能只有几天数据（如月初刚导入）
    - 用只有 1 天数据的月份算日均 → 结果毫无意义
    - 这个函数确保 baseline 计算始终基于数据充足的月份

    Returns:
        YYYYMM 格式的月份字符串，如 "202605"
    """
    from datetime import datetime

    today = datetime.now()
    if today.month == 1:
        last_complete_month = datetime(today.year - 1, 12, 1)
    else:
        last_complete_month = datetime(today.year, today.month - 1, 1)
    last_complete_ym = last_complete_month.strftime("%Y%m")

    if not os.path.exists(DATA_DIR):
        return last_complete_ym

    # 收集所有 past 月份的文件
    month_files = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".csv") and re.match(r"^\d{6}\.csv$", filename):
            month = filename[:6]
            if month <= last_complete_ym:
                month_files.append(month)

    if not month_files:
        return last_complete_ym

    # 从最近到最远排序
    month_files.sort(reverse=True)

    # 逐个检查实际交易天数，找第一个满足门槛的
    best_month = None
    best_days = 0

    for month in month_files:
        file_path = os.path.join(DATA_DIR, f"{month}.csv")
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
            if df.empty:
                continue

            # 用"交易日期"列计算实际有多少天有记录
            if "交易日期" in df.columns:
                date_series = pd.to_datetime(df["交易日期"], errors="coerce")
                unique_days = date_series.dropna().nunique()
            elif "交易时间" in df.columns:
                date_series = pd.to_datetime(df["交易时间"], errors="coerce").dt.date
                unique_days = date_series.dropna().nunique()
            else:
                unique_days = 0

            # 记录实际天数最多的月份（兜底用）
            if unique_days > best_days:
                best_days = unique_days
                best_month = month

            # 满足门槛 → 直接返回
            if unique_days >= min_days:
                return month

        except Exception:
            continue

    # 兜底：所有月份都不够门槛 → 返回实际天数最多的那个
    return best_month or month_files[0]


@tool
def get_daily_spending_baseline() -> str:
    """
    【预算计算专用】获取用户日常开销基线——以数据充足的最近完整月中 ≤25 元的日常小额消费为准。

    业务逻辑（内部自动完成）：
    1. 自动扫描 data/bills/，从最近月份往前找，**跳过交易天数 < 7 天的月份**
       （比如当月刚导入只有几天数据 → 自动跳过，用上个月完整数据）
    2. 读取选中的月份全部账单数据
    3. **只保留金额 ≤ 25 元的记录**（过滤掉房租、大额购物等非日常消费）
    4. 计算日均支出 = 筛选后总支出 ÷ 交易天数
    5. 返回结构化的基线数据

    为什么条件定死 ≤ 25 元：
    - 日常吃饭、通勤等必需开销，单笔一般不超过 25 元
    - 房租、买手机、高铁票等大额支出会被自动排除
    - 这样算出的日均才能真正反映「日常吃饭通勤」的消费水平

    Returns:
        JSON 字符串，包含：
        - source_month: 数据来源月份 (YYYYMM)
        - filter_max_amount: 筛选条件（固定 25）
        - filtered_record_count: 筛选后记录数 / 原始记录数
        - filtered_total: 筛选后总支出
        - days_count: 交易天数
        - daily_baseline: 日常开销基线（筛选后日均）
        - excluded_total: 被排除的大额支出总额
        - note: 说明信息（含数据质量说明，如是否跳过了不完整月份）
    """
    # Step 1: 找最近完整月
    target_month = _find_most_recent_complete_month()

    # Step 2: 读取该月数据
    try:
        df = _read_monthly(target_month)
    except FileNotFoundError:
        return json.dumps({
            "error": True,
            "message": f"未找到 {target_month} 月的账单数据文件",
            "source_month": target_month,
            "suggestion": "请先下载并解压微信账单，确保 data/bills/ 下有最近完整月的数据",
        }, ensure_ascii=False, indent=2)

    # Step 3: 全部记录 → 按 ≤25 元筛选
    all_records = df.to_dict(orient="records")
    total_count = len(all_records)

    DAILY_CAP = 25.0
    daily_records = []
    excluded_total = 0.0
    for r in all_records:
        amt = float(r.get("金额(元)", 0) or 0)
        direction = r.get("收/支", "")
        if direction == "支出" and amt > DAILY_CAP:
            excluded_total += amt
        elif direction == "支出" and amt <= DAILY_CAP:
            daily_records.append(r)
        else:
            # 收入记录也保留（用于算日均的天数统计）
            daily_records.append(r)

    # Step 4: 基于筛选后记录计算日均
    stats = _compute_bill_stats(daily_records)

    daily_baseline = stats["daily_avg_spending"]
    filtered_total = stats["total_spending"]
    days_count = stats["days_count"]
    filtered_count = stats["record_count"]

    # Step 5: 构造结果
    note = (
        f"来源月份 {target_month}，共 {total_count} 条记录。"
        f"筛选条件：金额 ≤ {DAILY_CAP} 元，保留 {filtered_count} 条，"
        f"排除大额支出 {excluded_total:.2f} 元。"
        f"日常开销基线 = {daily_baseline} 元/天。"
    )

    return json.dumps({
        "source_month": target_month,
        "filter_max_amount": DAILY_CAP,
        "total_record_count": total_count,
        "filtered_record_count": filtered_count,
        "filtered_total": round(filtered_total, 2),
        "excluded_total": round(excluded_total, 2),
        "days_count": days_count,
        "daily_baseline": daily_baseline,
        "note": note,
    }, ensure_ascii=False, indent=2)


# ============================================================
# 后端函数：图表生成（供前端 REST API 使用，不作为 LLM 工具）
# ============================================================

def generate_bill_charts(json_data: str, chart_type: str = "all") -> str:
    """
    根据JSON账单数据生成可视化图表（饼图/柱状图/折线图）。

    Args:
        json_data: 来自 get_date_range_bill_data 返回的完整JSON字符串
        chart_type: 图表类型，可选 "all"（全部）/ "pie"（饼图）/ "bar"（柱状图）/ "line"（折线图），默认 "all"
    """
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False
    data_dict = json.loads(json_data)
    records = data_dict.get("data", data_dict) if isinstance(data_dict, dict) else data_dict
    df = pd.DataFrame(records)
    if df.empty:
        return "❌ 数据为空，无法生成图表"
    if "交易时间" in df.columns:
        df["交易时间"] = pd.to_datetime(df["交易时间"], errors="coerce")
    if "交易日期" in df.columns:
        df["交易日期"] = pd.to_datetime(df["交易日期"], errors="coerce").dt.date
    if "金额(元)" in df.columns:
        df["金额(元)"] = pd.to_numeric(df["金额(元)"], errors="coerce")
    output_dir = Path(config.get("bill.output.chart_folder", "data/bills/charts"))
    output_dir.mkdir(parents=True, exist_ok=True)
    if "交易时间" in df.columns and not df["交易时间"].isna().all():
        time_range = f"{df['交易时间'].min().strftime('%Y%m%d')}-{df['交易时间'].max().strftime('%Y%m%d')}"
    else:
        time_range = "unknown"
    generated = []
    if chart_type in ("all", "pie"):
        exp_df = df[df["收/支"] == "支出"]
        if not exp_df.empty and "交易类型" in exp_df.columns:
            plt.figure(figsize=(7, 7))
            exp_df.groupby("交易类型")["金额(元)"].sum().plot.pie(autopct="%1.1f%%")
            plt.title("支出分类占比"); plt.ylabel("")
            p = output_dir / f"支出分类占比_{time_range}.png"
            plt.savefig(p, dpi=300, bbox_inches="tight"); plt.close()
            generated.append(str(p))
    if chart_type in ("all", "bar"):
        if "交易月份" in df.columns and "收/支" in df.columns:
            plt.figure(figsize=(10, 5))
            md = df.groupby(["交易月份", "收/支"])["金额(元)"].sum().unstack(fill_value=0)
            cols = [c for c in ["收入", "支出"] if c in md.columns]
            if cols: md[cols].plot.bar()
            plt.title("月度收支趋势"); plt.tight_layout()
            p = output_dir / f"月度收支趋势_{time_range}.png"
            plt.savefig(p, dpi=300); plt.close()
            generated.append(str(p))
    if chart_type in ("all", "line"):
        if "交易日期" in df.columns and "收/支" in df.columns:
            plt.figure(figsize=(18, 7))
            dd = df.groupby(["交易日期", "收/支"])["金额(元)"].sum().unstack(fill_value=0)
            cols = [c for c in ["收入", "支出"] if c in dd.columns]
            colors = ["#2E8B57", "#DC143C"]
            ax = plt.gca()
            for idx, col in enumerate(dd.columns[:len(colors)]):
                ax.fill_between(dd.index, 0, dd[col], alpha=0.1, color=colors[idx], edgecolor="none")
                ax.plot(dd.index, dd[col], marker="o", linestyle="-", linewidth=2.5, markersize=7,
                        color=colors[idx], label=col)
            plt.title("每日收支趋势", fontsize=14, pad=20)
            plt.xlabel("日期"); plt.ylabel("金额（元）")
            plt.xticks(rotation=45, ha="right"); plt.grid(True, alpha=0.3, linestyle="--")
            plt.legend(loc="upper right"); plt.subplots_adjust(bottom=0.2); plt.tight_layout()
            p = output_dir / f"每日收支折线图_{time_range}.png"
            plt.savefig(p, dpi=300, bbox_inches="tight"); plt.close()
            generated.append(str(p))
    if not generated:
        return "❌ 未能生成任何图表"
    return "✅ 成功生成 " + str(len(generated)) + " 个图表：\n" + "\n".join(f"  📊 {f}" for f in generated)


@tool
def get_data_inventory() -> str:
    """
    获取当前本地账单数据文件的完整清单和统计信息（解决LLM知识盲区问题）。

    当用户询问以下问题时，必须调用此工具：
    - "我的数据到哪了？"
    - "有多少条账单记录？"
    - "最新的数据是哪天的？"
    - "当前数据库状态如何？"
    - "有哪些月份的数据？"

    Returns:
        JSON字符串，包含 total_files / total_records / latest_date / files 数组
    """
    inventory = {
        "total_files": 0,
        "total_records": 0,
        "latest_date": None,
        "files": []
    }

    if not os.path.exists(DATA_DIR):
        return json.dumps({
            "error": "数据目录不存在",
            "data_dir": DATA_DIR,
            "suggestion": "请先下载并解压微信支付账单"
        }, ensure_ascii=False, indent=2)

    for filename in sorted(os.listdir(DATA_DIR)):
        if filename.endswith(".csv") and re.match(r"^\d{6}\.csv$", filename):
            month = filename[:6]
            file_path = os.path.join(DATA_DIR, filename)

            try:
                df = pd.read_csv(file_path, encoding="utf-8-sig")
                record_count = len(df)

                if record_count == 0:
                    inventory["files"].append({
                        "month": month,
                        "filename": filename,
                        "record_count": 0,
                        "warning": "空文件，无数据记录"
                    })
                    inventory["total_files"] += 1
                    continue

                # 提取日期范围
                date_range = "暂无日期列"
                for col in ["交易时间", "交易日期"]:
                    if col in df.columns:
                        try:
                            date_series = pd.to_datetime(df[col], errors="coerce")
                            valid_dates = date_series.dropna()
                            if not valid_dates.empty:
                                min_date = valid_dates.min().strftime("%Y-%m-%d")
                                max_date = valid_dates.max().strftime("%Y-%m-%d")
                                date_range = f"{min_date} to {max_date}"
                                if inventory["latest_date"] is None or max_date > inventory["latest_date"]:
                                    inventory["latest_date"] = max_date
                            break
                        except Exception:
                            pass

                inventory["files"].append({
                    "month": month,
                    "filename": filename,
                    "record_count": record_count,
                    "date_range": date_range
                })
                inventory["total_files"] += 1
                inventory["total_records"] += record_count

            except Exception as e:
                inventory["files"].append({
                    "month": month,
                    "filename": filename,
                    "record_count": 0,
                    "warning": f"读取失败: {str(e)}"
                })
                inventory["total_files"] += 1

    inventory["summary"] = f"共 {inventory['total_files']} 个文件，{inventory['total_records']} 条记录"
    return json.dumps(inventory, ensure_ascii=False, indent=2)
