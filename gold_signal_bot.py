
import os
import time
import requests
import pandas as pd

# =========================
# CONFIGURATION
# =========================
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "YOUR_TWELVE_DATA_API_KEY")
SYMBOL = "XAU/USD"
INTERVAL = "1min"
OUTPUTSIZE = 100

POLL_SECONDS = 60  # ตรวจสอบทุก 60 วินาที
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14

API_URL = "https://api.twelvedata.com/time_series"


def fetch() -> pd.DataFrame:
    """ดึงข้อมูลแท่งเทียน XAU/USD จาก Twelve Data"""

    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "outputsize": OUTPUTSIZE,
        "apikey": API_KEY,
        "format": "JSON"
    }

    response = requests.get(
        API_URL,
        params=params,
        timeout=15
    )
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(f"Twelve Data API Error: {data}")

    df = pd.DataFrame(data["values"])

    if df.empty:
        raise ValueError("API ไม่ส่งข้อมูลราคา")

    df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="last")]

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])

    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })

    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """คำนวณ EMA และ RSI"""

    df = df.copy()

    df["EMA9"] = df["Close"].ewm(
        span=EMA_FAST, adjust=False
    ).mean()

    df["EMA21"] = df["Close"].ewm(
        span=EMA_SLOW, adjust=False
    ).mean()

    delta = df["Close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / RSI_PERIOD,
        min_periods=RSI_PERIOD,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / RSI_PERIOD,
        min_periods=RSI_PERIOD,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI"] = 100 - (100 / (1 + rs))

    # ป้องกันกรณีราคาขึ้นต่อเนื่องหรือไม่มีการเปลี่ยนแปลง
    df.loc[avg_loss == 0, "RSI"] = 100
    df.loc[
        (avg_gain == 0) & (avg_loss == 0), "RSI"
    ] = 50

    return df


def generate_signal(df: pd.DataFrame) -> dict:
    """
    ประเมินสัญญาณจากแท่งที่ปิดแล้ว
    สมมติว่าแท่งสุดท้ายเป็นแท่งที่กำลังก่อตัว
    """

    if len(df) < 40:
        return {"signal": "WAIT", "reason": "ข้อมูลไม่เพียงพอ"}

    df = add_indicators(df)

    # ใช้แท่งก่อนหน้าสุดท้ายเป็นแท่งปิดแล้ว
    prev = df.iloc[-3]
    curr = df.iloc[-2]

    if pd.isna(curr["RSI"]):
        return {"signal": "WAIT", "reason": "RSI ยังไม่พร้อม"}

    # EMA ตัดขึ้น + RSI ยืนยันโมเมนตัม
    buy = (
        prev["EMA9"] <= prev["EMA21"]
        and curr["EMA9"] > curr["EMA21"]
        and 50 <= curr["RSI"] < 70
    )

    # EMA ตัดลง + RSI ยืนยันโมเมนตัม
    sell = (
        prev["EMA9"] >= prev["EMA21"]
        and curr["EMA9"] < curr["EMA21"]
        and 30 < curr["RSI"] <= 50
    )

    if buy:
        signal = "BUY"
        reason = "EMA9 ตัดขึ้น EMA21 และ RSI ยืนยัน"
    elif sell:
        signal = "SELL"
        reason = "EMA9 ตัดลง EMA21 และ RSI ยืนยัน"
    else:
        signal = "WAIT"
        reason = "ยังไม่พบจังหวะเข้าเทรดตามเงื่อนไข"

    return {
        "signal": signal,
        "reason": reason,
        "candle_time": str(df.index[-2]),
        "price": float(curr["Close"]),
        "ema9": float(curr["EMA9"]),
        "ema21": float(curr["EMA21"]),
        "rsi": float(curr["RSI"])
    }


def main():
    if API_KEY == "YOUR_TWELVE_DATA_API_KEY":
        raise ValueError("กรุณาตั้งค่า Twelve Data API Key ก่อน")

    last_processed_candle = None

    print(f"เริ่มติดตาม {SYMBOL} | Interval={INTERVAL}")
    print("ระบบนี้ส่งสัญญาณเท่านั้น ยังไม่ส่งคำสั่งซื้อขายจริง")

    while True:
        try:
            df = fetch()
            result = generate_signal(df)

            candle_time = result.get("candle_time")

            # แจ้งผลเฉพาะเมื่อมีแท่งใหม่ที่ยังไม่เคยประมวลผล
            if candle_time and candle_time != last_processed_candle:
                last_processed_candle = candle_time

                print("\n------------------------------")
                print("เวลาแท่งเทียน:", candle_time)
                print("สัญญาณ:", result["signal"])
                print("เหตุผล:", result["reason"])

                if "price" in result:
                    print(f'ราคาปิด: {result["price"]:.2f}')
                    print(f'EMA9: {result["ema9"]:.2f}')
                    print(f'EMA21: {result["ema21"]:.2f}')
                    print(f'RSI: {result["rsi"]:.2f}')

                if result["signal"] in ("BUY", "SELL"):
                    print(">>> พบสัญญาณเข้าเทรด โปรดตรวจสอบก่อนตัดสินใจ")

        except (requests.RequestException, ValueError, RuntimeError) as e:
            print(f"ข้อผิดพลาดในการดึงข้อมูล: {e}")
        except Exception as e:
            print(f"ข้อผิดพลาดอื่น: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
