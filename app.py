# main.py

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime
import base64
import httpx
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials, firestore
from twilio.rest import Client  # <-- Twilio import

# Load environment variables
load_dotenv()

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Twilio Credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Firebase Credentials
FIREBASE_KEY_FILE = os.getenv("FIREBASE_KEY_FILE")

# Initialize Firebase
cred = credentials.Certificate(FIREBASE_KEY_FILE)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Daraja URLs
ACCESS_TOKEN_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

# Pydantic model
class DonationRequest(BaseModel):
    name: str
    phone: str  # Expect format 7XXXXXXXX
    amount: int
    message: str = ""

@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to Jogoo CBO M-Pesa Donation API"}

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
        print("Safaricom STK Push Error Response:", stk_resp.text)
        raise HTTPException(status_code=500, detail=f"Safaricom STK Push failed: {stk_resp.text}")

    print("STK Push Initiated Successfully:", stk_resp.json())
    return stk_resp.json()

@app.post("/mpesa-callback")
async def mpesa_callback(request: Request):
    body = await request.json()
    print("M-Pesa Callback Received:", body)

    # Extract important metadata
    callback_metadata = body.get('Body', {}).get('stkCallback', {}).get('CallbackMetadata', {}).get('Item', [])
    mpesa_data = {item['Name']: item.get('Value') for item in callback_metadata}

    if not mpesa_data:
        print("No Callback Metadata Found")
        return {"message": "No payment metadata found"}

    # Prepare document to save
    donation_record = {
        "amount": mpesa_data.get("Amount"),
        "phone": mpesa_data.get("PhoneNumber"),
        "mpesa_receipt_number": mpesa_data.get("MpesaReceiptNumber"),
        "transaction_date": mpesa_data.get("TransactionDate"),
        "created_at": datetime.utcnow().isoformat()
    }

    # Save to Firestore
    db.collection('donations').add(donation_record)
    print("Donation record saved to Firebase:", donation_record)

    # Send SMS confirmation using Twilio
    try:
        twilio_client.messages.create(
            body=f"Thank you for donating KES {mpesa_data.get('Amount')} to Jogoo CBO! Receipt: {mpesa_data.get('MpesaReceiptNumber')}.",
            from_=TWILIO_PHONE_NUMBER,
            to=f"+{mpesa_data.get('PhoneNumber')}"
        )
        print("Twilio SMS sent successfully")
    except Exception as e:
        print("Failed to send Twilio SMS:", e)

    return {"message": "Callback received, saved, and SMS sent via Twilio successfully"}
