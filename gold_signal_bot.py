import requests
import pandas as pd

API_KEY = "YOUR_TWELVE_DATA_API_KEY"  # ใส่ API Key ของคุณที่ได้จาก twelvedata.com
SYMBOL = "XAU/USD"                    # รูปแบบคู่เงินทองคำของ Twelve Data

def fetch() -> pd.DataFrame:
    # ดึงข้อมูลแท่งเทียนแบบ Real-time ผ่าน REST API ของ Twelve Data
    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval={INTERVAL}&outputsize=60&apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    
    # ตรวจสอบว่า API ส่งข้อมูลมาถูกต้องหรือไม่
    if "values" not in data:
        raise ValueError(f"API Error: {data}")
    
    # แปลงข้อมูลให้อยู่ในรูปแบบ DataFrame ของ pandas
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    
    # 1. เปลี่ยนชื่อคอลัมน์จากตัวพิมพ์เล็กให้เป็นตัวพิมพ์ใหญ่ เพื่อให้ตรงกับฟังก์ชันคำนวณเดิม
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })
    
    # 2. แปลงเฉพาะคอลัมน์ราคาที่เป็นตัวเลขให้ปลอดภัย
    numeric_cols = ["Open", "High", "Low", "Close"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(float)
            
    # 3. จัดเรียงข้อมูลจากเก่าไปใหม่ พร้อม Assign ค่ากลับคืนให้ DataFrame
    df = df.sort_index() 
    
    return df

