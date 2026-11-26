#!/usr/bin/env python3
"""
Quick test to save a sample record to Google Sheets
"""
import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

async def test_save():
    # Import after load_dotenv
    from app.services.lead_storage_service import get_lead_storage_service, init_lead_storage_service
    from app.core.config import log
    
    print("\n" + "="*70)
    print("GOOGLE SHEETS SAVE TEST")
    print("="*70)
    
    # Initialize service
    print("\nInitializing lead storage service...")
    service = await init_lead_storage_service()
    
    if not service:
        print("❌ Failed to initialize lead storage service")
        return False
    
    print("✅ Service initialized")
    
    # Create test record
    test_record = {
        "call_session_id": f"CALL-20261126-TEST{datetime.now().timestamp()}",
        "mobile_number": "9876543210",
        "customer_name": "Test Customer",
        "company_name": "Test Company",
        "location": "Test City",
        "interested_products": "Test Products",
        "required_quantity": "100 units",
        "business_requirement": "Test",
        "bulk_and_other_requirements": "No",
        "call_timestamp": datetime.utcnow().isoformat()
    }
    
    print(f"\nTest Record:")
    for key, value in test_record.items():
        print(f"  {key}: {value}")
    
    # Try to save
    print(f"\nSaving to Google Sheets...")
    result = await service.save_requirements(test_record)
    
    print(f"\nResult:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    
    if result.get("success"):
        print("\n✅ Save successful!")
        return True
    else:
        print(f"\n❌ Save failed: {result.get('message')}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_save())
    sys.exit(0 if success else 1)
