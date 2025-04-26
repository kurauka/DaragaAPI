# main.py

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime
import base64
import httpx
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # Load .env

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (you can restrict in production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Safaricom Daraja Credentials
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
PASSKEY = os.getenv("PASSKEY")
SHORTCODE = os.getenv("SHORTCODE")
CALLBACK_URL = os.getenv("CALLBACK_URL")

# Daraja URLs
ACCESS_TOKEN_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

# Pydantic model
class DonationRequest(BaseModel):
    name: str
    phone: str  # Expect format 7XXXXXXXX
    amount: int
    message: str = ""

@app.post("/donate")
async def donate(data: DonationRequest):
    # 1. Get Access Token
    async with httpx.AsyncClient() as client:
        auth = (CONSUMER_KEY, CONSUMER_SECRET)
        token_resp = await client.get(ACCESS_TOKEN_URL, auth=auth)

        if token_resp.status_code != 200:
            print("Access token response:", token_resp.text)
            raise HTTPException(status_code=500, detail="Failed to authenticate with Safaricom")

        access_token = token_resp.json().get('access_token')
        if not access_token:
            print("Access token missing from response:", token_resp.text)
            raise HTTPException(status_code=500, detail="Access token not found in Safaricom response.")

    # 2. Generate Password
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = SHORTCODE + PASSKEY + timestamp
    password = base64.b64encode(password_str.encode()).decode()

    # 3. Prepare STK Push payload
    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": data.amount,
        "PartyA": f"254{data.phone}",
        "PartyB": SHORTCODE,
        "PhoneNumber": f"254{data.phone}",
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "JogooCBO",
        "TransactionDesc": f"Donation from {data.name}"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # 4. Send STK Push
    async with httpx.AsyncClient() as client:
        stk_resp = await client.post(STK_PUSH_URL, headers=headers, json=payload)

    if stk_resp.status_code != 200:
        print("Safaricom STK Push Error Response:", stk_resp.text)  # <-- Added print
        raise HTTPException(status_code=500, detail=f"Safaricom STK Push failed: {stk_resp.text}")

    print("STK Push Initiated Successfully:", stk_resp.json())
    return stk_resp.json()

@app.post("/mpesa-callback")
async def mpesa_callback(request: Request):
    body = await request.json()
    print("M-Pesa Callback Received:", body)
    # Optional: Save this body to database for transaction logs
    return {"message": "Callback received successfully"}
