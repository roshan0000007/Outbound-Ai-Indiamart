#!/usr/bin/env python3
"""
Inspect Google Sheets headers
One-time utility to read actual headers from the target spreadsheet
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def inspect_sheets():
    """Inspect the actual Google Sheets structure"""
    
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sheet_tab = os.getenv("GOOGLE_SHEET_TAB", "Client_Requirements")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    print(f"\n{'='*70}")
    print("GOOGLE SHEETS INSPECTION")
    print(f"{'='*70}")
    print(f"Spreadsheet ID: {sheet_id}")
    print(f"Worksheet Tab: {sheet_tab}")
    print(f"Credentials Path: {creds_path}")
    
    # Check credentials file
    if not creds_path:
        print(f"\n⚠️  GOOGLE_APPLICATION_CREDENTIALS not set in .env")
        print("   Required steps:")
        print("   1. Create service account in Google Cloud Console")
        print("   2. Download JSON credentials file")
        print("   3. Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json")
        print("   4. Share spreadsheet with service account email")
        return
    
    if not os.path.exists(creds_path):
        print(f"\n❌ Credentials file not found: {creds_path}")
        return
    
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        
        print(f"\n✅ Credentials file found: {creds_path}")
        
        # Load credentials
        credentials = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        
        # Build service
        service = build("sheets", "v4", credentials=credentials)
        
        print("✅ Google Sheets API authenticated")
        
        # Get spreadsheet metadata
        try:
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=sheet_id
            ).execute()
            
            print(f"\n📊 Spreadsheet Title: {spreadsheet.get('properties', {}).get('title', 'Unknown')}")
            print(f"📄 Available Worksheets:")
            for sheet in spreadsheet.get('sheets', []):
                sheet_prop = sheet.get('properties', {})
                print(f"   - {sheet_prop.get('title')} (GID: {sheet_prop.get('sheetId', 'N/A')})")
        except Exception as e:
            print(f"⚠️  Could not fetch spreadsheet metadata: {e}")
        
        # Read first row (headers)
        range_name = f"{sheet_tab}!1:1"
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            print(f"\n⚠️  No data found in worksheet '{sheet_tab}'")
            print("   The spreadsheet may be empty or the tab name is incorrect.")
            return
        
        headers = values[0]
        
        print(f"\n{'='*70}")
        print(f"HEADERS IN WORKSHEET '{sheet_tab}' (Row 1):")
        print(f"{'='*70}")
        
        for idx, header in enumerate(headers, 1):
            print(f"Column {idx:2d} ({chr(64+idx)}): {header}")
        
        print(f"\nTotal columns: {len(headers)}")
        
        # Read row 2 as example
        range_name2 = f"{sheet_tab}!2:2"
        result2 = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name2
        ).execute()
        
        values2 = result2.get('values', [])
        
        if values2:
            print(f"\n{'='*70}")
            print(f"FIRST DATA ROW (Row 2 - Example):")
            print(f"{'='*70}")
            for idx, (header, value) in enumerate(zip(headers, values2[0] if values2 else []), 1):
                val = value if idx <= len(values2[0]) else "(empty)"
                print(f"Column {idx:2d} ({chr(64+idx)}): {header:30s} = {val}")
        
        # Count total rows
        range_name_col_a = f"{sheet_tab}!A:A"
        result_col_a = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name_col_a
        ).execute()
        
        all_rows = result_col_a.get('values', [])
        print(f"\n{'='*70}")
        print(f"SHEET STATISTICS:")
        print(f"{'='*70}")
        print(f"Total rows (including header): {len(all_rows)}")
        print(f"Total data rows: {len(all_rows) - 1}")
        
    except ImportError:
        print(f"\n❌ Google API client not installed")
        print("   Install: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    inspect_sheets()
