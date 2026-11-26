#!/usr/bin/env python3
"""
Check actual sheet structure and headers
"""
import os
from dotenv import load_dotenv

load_dotenv()

sheet_id = os.getenv("GOOGLE_SHEET_ID")
sheet_tab = os.getenv("GOOGLE_SHEET_TAB", "Client_Requirements")
creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

print("\n" + "="*70)
print("GOOGLE SHEETS STRUCTURE CHECK")
print("="*70)
print(f"Sheet ID: {sheet_id}")
print(f"Sheet Tab: {sheet_tab}")
print(f"Credentials: {creds_path}")

if not creds_path or not os.path.exists(creds_path):
    print(f"\n❌ Credentials not found at: {creds_path}")
    exit(1)

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    
    # Authenticate
    credentials = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    
    service = build("sheets", "v4", credentials=credentials)
    
    print("\n✅ Authentication successful")
    
    # Get spreadsheet metadata
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        print(f"\n📄 Spreadsheet: {spreadsheet.get('properties', {}).get('title')}")
        print(f"📋 Available Sheets:")
        for sheet in spreadsheet.get('sheets', []):
            props = sheet.get('properties', {})
            print(f"   - {props.get('title')} (GID: {props.get('sheetId')})")
    except Exception as e:
        print(f"⚠️ Could not get metadata: {e}")
    
    # Read first 5 rows
    print(f"\n📊 Reading sheet: {sheet_tab}")
    for row_num in range(1, 6):
        range_name = f"{sheet_tab}!{row_num}:{row_num}"
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name
        ).execute()
        
        values = result.get("values", [[]])
        if values and values[0]:
            print(f"\nRow {row_num}:")
            for col_idx, value in enumerate(values[0], 1):
                col_letter = chr(64 + col_idx)  # A, B, C, ...
                print(f"  {col_letter}: {value}")
        else:
            print(f"\nRow {row_num}: (empty)")
    
except ImportError:
    print("❌ Google API not installed")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
