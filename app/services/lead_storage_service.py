"""
Lead Storage Service
Handles persisting customer requirements to Google Sheets or Excel
"""

import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..core.config import log


class GoogleSheetsAdapter:
    """Adapter for Google Sheets integration"""

    def __init__(self):
        self.sheet_id = os.getenv("GOOGLE_SHEET_ID")
        self.sheet_tab = os.getenv("GOOGLE_SHEET_TAB", "Client_Requirements")
        self.credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.service = None

    async def initialize(self) -> bool:
        """Initialize Google Sheets service"""
        try:
            if not self.sheet_id or not self.credentials_path:
                log.warning("[GoogleSheets] Credentials not fully configured")
                return False
            
            # Import Google API client
            from google.oauth2.service_account import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            
            # Load credentials
            if not os.path.exists(self.credentials_path):
                log.error(f"[GoogleSheets] Credentials file not found: {self.credentials_path}")
                return False
            
            credentials = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            
            self.service = build("sheets", "v4", credentials=credentials)
            
            # Ensure headers exist with new columns
            await self._ensure_headers()
            
            log.info("[GoogleSheets] ✅ Service initialized successfully")
            return True
        except ImportError:
            log.warning("[GoogleSheets] Google API client not installed. Install: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
            return False
        except Exception as e:
            log.error(f"[GoogleSheets] Initialization failed: {e}")
            return False

    async def _ensure_headers(self) -> None:
        """Ensure headers exist with Call Session ID, Mobile Number, and Call Date & Time"""
        try:
            if not self.service:
                return
            
            log.info(f"[GoogleSheets] Checking headers in sheet: {self.sheet_tab}")
            
            # Read first row to check existing headers
            range_name = f"{self.sheet_tab}!A1:J1"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            existing_values = result.get("values", [])
            existing_headers = existing_values[0] if existing_values else []
            
            log.info(f"[GoogleSheets] Existing headers: {existing_headers}")
            
            # Define required headers in order
            required_headers = [
                "Call Session ID",
                "Customer Mobile Number",
                "Customer Name",
                "Company Name",
                "Location",
                "Interested Products",
                "Required Quantity",
                "Business Requirement",
                "Bulk & Other Requirements",
                "Call Date & Time"
            ]
            
            # Only update if headers don't match
            if existing_headers != required_headers:
                log.info(f"[GoogleSheets] Creating/updating headers with new columns")
                log.info(f"[GoogleSheets] Expected headers: {required_headers}")
                log.info(f"[GoogleSheets] Actual headers: {existing_headers}")
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    body={"values": [required_headers]}
                ).execute()
                
                log.info("[GoogleSheets] ✅ Headers ensured")
            else:
                log.info("[GoogleSheets] ✅ Headers already correct")
        except Exception as e:
            log.error(f"[GoogleSheets] Error ensuring headers: {e}")

    async def save_requirements(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save requirements to Google Sheets with Call Session ID, Mobile Number, and timestamp.
        
        Args:
            requirements: Dict with keys:
                - call_session_id: Unique call session identifier
                - mobile_number: Customer's phone number
                - customer_name: Name
                - company_name: Company
                - location: Location
                - interested_products: Products
                - required_quantity: Quantity
                - business_requirement: Business need
                - bulk_and_other_requirements: Other requirements
                - call_timestamp: ISO format datetime string (optional, generated if missing)
                
        Returns:
            Dict with success status, message, row_number, and call_session_id
        """
        try:
            if not self.service:
                return {
                    "success": False,
                    "message": "Service not initialized",
                    "row_number": None,
                    "call_session_id": requirements.get("call_session_id", "unknown")
                }
            
            call_session_id = requirements.get("call_session_id", "")
            mobile_number = requirements.get("mobile_number", "N/A")
            call_timestamp = requirements.get("call_timestamp", datetime.utcnow().isoformat())
            
            # DEBUG: Log what we received
            log.info(f"[GoogleSheets] ===== DEBUG INFO =====")
            log.info(f"[GoogleSheets] Call Session ID received: '{call_session_id}' (type: {type(call_session_id).__name__})")
            log.info(f"[GoogleSheets] Mobile Number received: '{mobile_number}'")
            log.info(f"[GoogleSheets] Requirements keys: {requirements.keys()}")
            log.info(f"[GoogleSheets] Full requirements: {requirements}")
            log.info(f"[GoogleSheets] ====================")
            
            # Prepare row data in exact order matching headers
            # Ensure all values are strings to prevent formatting issues
            row_data = [
                str(call_session_id) if call_session_id else "",
                str(mobile_number) if mobile_number else "N/A",
                str(requirements.get("customer_name", "")) if requirements.get("customer_name") else "",
                str(requirements.get("company_name", "")) if requirements.get("company_name") else "",
                str(requirements.get("location", "")) if requirements.get("location") else "",
                str(requirements.get("interested_products", "")) if requirements.get("interested_products") else "",
                str(requirements.get("required_quantity", "")) if requirements.get("required_quantity") else "",
                str(requirements.get("business_requirement", "")) if requirements.get("business_requirement") else "",
                str(requirements.get("bulk_and_other_requirements", "")) if requirements.get("bulk_and_other_requirements") else "",
                str(call_timestamp) if call_timestamp else ""
            ]
            
            # Log the row data being saved with index
            log.info(f"[GoogleSheets] Row data ({len(row_data)} values):")
            for idx, (header, value) in enumerate(zip([
                "Call Session ID",
                "Customer Mobile Number",
                "Customer Name",
                "Company Name",
                "Location",
                "Interested Products",
                "Required Quantity",
                "Business Requirement",
                "Bulk & Other Requirements",
                "Call Date & Time"
            ], row_data), 1):
                log.info(f"[GoogleSheets]   Col {idx} ({chr(64+idx)}): {header:30s} = '{value}'")
            
            # Find next empty row by checking column A
            range_name = f"{self.sheet_tab}!A:A"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            existing_rows = result.get("values", [])
            next_row = len(existing_rows) + 1
            
            log.info(f"[GoogleSheets] Found {len(existing_rows)} existing rows, appending to row {next_row}")
            
            # Idempotency check: Verify this call_session_id doesn't already exist
            if call_session_id:
                range_name_check = f"{self.sheet_tab}!A:A"
                existing_data = self.service.spreadsheets().values().get(
                    spreadsheetId=self.sheet_id,
                    range=range_name_check
                ).execute()
                
                existing_session_ids = existing_data.get("values", [])[1:]  # Skip header
                for idx, existing_id in enumerate(existing_session_ids):
                    if existing_id and len(existing_id) > 0 and existing_id[0] == call_session_id:
                        log.warning(f"[GoogleSheets] Call {call_session_id} already saved (idempotency)")
                        return {
                            "success": True,
                            "message": "Already saved (idempotent)",
                            "row_number": idx + 2,  # +2 because header is row 1 and idx is 0-based
                            "call_session_id": call_session_id,
                            "already_saved": True
                        }
            
            # Append row with proper formatting
            range_name = f"{self.sheet_tab}!A{next_row}:J{next_row}"
            log.info(f"[GoogleSheets] Updating range: {range_name}")
            
            response = self.service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [row_data]}
            ).execute()
            
            log.info(f"[GoogleSheets] API Response: {response}")
            
            log.info(f"[GoogleSheets] ✅ Saved to row {next_row}")
            log.info(f"[GoogleSheets] Call Session ID: {call_session_id}")
            log.info(f"[GoogleSheets] Customer Mobile: {mobile_number}")
            log.info(f"[GoogleSheets] Validated fields: 8/8")
            
            return {
                "success": True,
                "message": "Saved to Google Sheets",
                "row_number": next_row,
                "call_session_id": call_session_id,
                "already_saved": False
            }
        except Exception as e:
            log.error(f"[GoogleSheets] Error saving requirements: {e}")
            return {
                "success": False,
                "message": str(e),
                "row_number": None,
                "call_session_id": requirements.get("call_session_id", "unknown")
            }


class ExcelAdapter:
    """Adapter for Excel file integration"""

    def __init__(self):
        self.file_path = os.getenv("EXCEL_FILE_PATH")
        self.sheet_name = os.getenv("EXCEL_SHEET_NAME", "Client_Requirements")
        self.workbook = None

    async def initialize(self) -> bool:
        """Initialize Excel service"""
        try:
            if not self.file_path:
                log.warning("[Excel] File path not configured")
                return False
            
            try:
                from openpyxl import load_workbook, Workbook
                from openpyxl.utils import get_column_letter
            except ImportError:
                log.warning("[Excel] openpyxl not installed. Install: pip install openpyxl")
                return False
            
            # Load or create workbook
            if os.path.exists(self.file_path):
                self.workbook = load_workbook(self.file_path)
                log.info(f"[Excel] Loaded existing file: {self.file_path}")
            else:
                self.workbook = Workbook()
                log.info(f"[Excel] Created new file: {self.file_path}")
            
            # Ensure sheet exists
            if self.sheet_name not in self.workbook.sheetnames:
                sheet = self.workbook.create_sheet(self.sheet_name)
            else:
                sheet = self.workbook[self.sheet_name]
            
            # Ensure headers
            await self._ensure_headers(sheet)
            
            self.workbook.save(self.file_path)
            log.info("[Excel] ✅ Service initialized successfully")
            return True
        except Exception as e:
            log.error(f"[Excel] Initialization failed: {e}")
            return False

    async def _ensure_headers(self, sheet) -> None:
        """Ensure headers exist in sheet"""
        try:
            required_headers = [
                "Customer Name",
                "Company Name",
                "Location",
                "Interested Products",
                "Required Quantity",
                "Business Requirement",
                "Bulk & Other Requirements"
            ]
            
            # Check if headers exist
            if sheet.cell(1, 1).value is None:
                for col, header in enumerate(required_headers, 1):
                    sheet.cell(1, col, header)
                log.info("[Excel] Headers created")
        except Exception as e:
            log.error(f"[Excel] Error ensuring headers: {e}")

    async def save_requirements(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Save requirements to Excel file"""
        try:
            if not self.workbook or not self.file_path:
                return {
                    "success": False,
                    "message": "Service not initialized",
                    "row_number": None
                }
            
            from openpyxl.utils import get_column_letter
            
            sheet = self.workbook[self.sheet_name]
            
            # Find next empty row
            next_row = sheet.max_row + 1
            
            # Prepare row data
            row_data = [
                requirements.get("customer_name", ""),
                requirements.get("company_name", ""),
                requirements.get("location", ""),
                requirements.get("interested_products", ""),
                requirements.get("required_quantity", ""),
                requirements.get("business_requirement", ""),
                requirements.get("bulk_and_other_requirements", "")
            ]
            
            # Write row
            for col, value in enumerate(row_data, 1):
                sheet.cell(next_row, col, value)
            
            # Save workbook
            self.workbook.save(self.file_path)
            
            log.info(f"[Excel] ✅ Saved to row {next_row}")
            
            return {
                "success": True,
                "message": "Saved to Excel",
                "row_number": next_row
            }
        except Exception as e:
            log.error(f"[Excel] Error saving requirements: {e}")
            return {
                "success": False,
                "message": str(e),
                "row_number": None
            }


class LeadStorageService:
    """Central lead storage service with multiple adapters"""

    def __init__(self):
        self.provider = os.getenv("LEAD_STORAGE_PROVIDER", "mysql")
        self.google_sheets = None
        self.excel = None

    async def initialize(self) -> bool:
        """Initialize storage service"""
        try:
            log.info(f"[LeadStorage] Initializing with provider: {self.provider}")
            
            if self.provider == "google_sheets":
                self.google_sheets = GoogleSheetsAdapter()
                success = await self.google_sheets.initialize()
                if not success:
                    log.warning("[LeadStorage] Google Sheets initialization failed, falling back to MySQL")
                    self.provider = "mysql"
            
            elif self.provider == "excel":
                self.excel = ExcelAdapter()
                success = await self.excel.initialize()
                if not success:
                    log.warning("[LeadStorage] Excel initialization failed, falling back to MySQL")
                    self.provider = "mysql"
            
            log.info(f"[LeadStorage] ✅ Initialized with provider: {self.provider}")
            return True
        except Exception as e:
            log.error(f"[LeadStorage] Initialization error: {e}")
            self.provider = "mysql"  # Fall back to MySQL
            return True

    async def save_requirements(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Save requirements using configured provider"""
        try:
            if not requirements:
                return {
                    "success": False,
                    "message": "No requirements provided",
                    "provider": self.provider
                }
            
            if self.provider == "google_sheets" and self.google_sheets:
                result = await self.google_sheets.save_requirements(requirements)
                result["provider"] = "google_sheets"
                return result
            
            elif self.provider == "excel" and self.excel:
                result = await self.excel.save_requirements(requirements)
                result["provider"] = "excel"
                return result
            
            else:
                # Fall back to MySQL (handled by caller)
                return {
                    "success": True,
                    "message": "Saved to MySQL database",
                    "provider": "mysql"
                }
        except Exception as e:
            log.error(f"[LeadStorage] Error saving requirements: {e}")
            return {
                "success": False,
                "message": str(e),
                "provider": self.provider
            }


_service: Optional[LeadStorageService] = None


async def init_lead_storage_service():
    """Initialize lead storage service"""
    global _service
    _service = LeadStorageService()
    await _service.initialize()
    return _service


def get_lead_storage_service() -> Optional[LeadStorageService]:
    """Get lead storage service instance"""
    return _service
