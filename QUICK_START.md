# Quick Start Guide - Customer Requirements Collection

## 30-Minute Setup

### Step 1: Install Dependencies (5 minutes)

```bash
cd "d:\OutBoundAi\Anukul Client"

# Install new dependencies
pip install -r requirements.txt --upgrade

# Or install specific additions
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client openpyxl
```

### Step 2: Create Database Table (5 minutes)

Connect to your MySQL database and run:

```sql
USE seatechcc;

CREATE TABLE IF NOT EXISTS customer_requirements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  call_id VARCHAR(64) UNIQUE NOT NULL,
  customer_name VARCHAR(100),
  company_name VARCHAR(150),
  location VARCHAR(100),
  interested_products TEXT,
  required_quantity TEXT,
  business_requirement TEXT,
  bulk_and_other_requirements TEXT,
  is_complete BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  source VARCHAR(50) DEFAULT 'call',
  INDEX idx_call_id (call_id),
  INDEX idx_created_at (created_at),
  INDEX idx_is_complete (is_complete)
);

-- Verify table creation
DESC customer_requirements;
```

### Step 3: Configure Environment (5 minutes)

The `.env` file already has all required variables. Customize if needed:

```env
# Client Business (already configured)
CLIENT_BUSINESS_NAME=Industrial Products & Disposable Wooden Products
CLIENT_DEFAULT_LANGUAGE=en-IN

# Greeting (already configured with defaults)
CLIENT_GREETING=Hello! Good morning. Thank you for taking our call...
CLIENT_CLOSING_MESSAGE=Thank you for sharing your requirements...

# Storage (default: MySQL)
LEAD_STORAGE_PROVIDER=mysql

# If using Google Sheets, add:
# LEAD_STORAGE_PROVIDER=google_sheets
# GOOGLE_SHEET_ID=your-sheet-id
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# If using Excel, add:
# LEAD_STORAGE_PROVIDER=excel
# EXCEL_FILE_PATH=data/client_requirements.xlsx
```

### Step 4: Start Application (5 minutes)

```bash
# From project root directory
python main.py

# Or using uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8111 --reload
```

You should see in logs:

```
✓ Customer requirement service initialized
✓ Requirement tools service initialized
✓ Lead storage service initialized
✓ Greeting service initialized
```

### Step 5: Test the System (5 minutes)

#### Test 1: Check API availability

```bash
curl http://localhost:8111/api/requirements/questions
```

Expected response:
```json
{
  "customer_name": "May I know your name, please?",
  "company_name": "Could you please share your company or business name?",
  ...
}
```

#### Test 2: Simulate a full call

```bash
# Start a test call
curl -X POST http://localhost:8111/api/calls/handler/start \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "test_001",
    "caller_number": "9876543210",
    "dnid": "1234",
    "user_id": 1
  }'

# Check status
curl http://localhost:8111/api/requirements/status/test_001

# Update requirements with customer info
curl -X POST http://localhost:8111/api/requirements/update \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "test_001",
    "customer_name": "Rahul Kumar",
    "company_name": "ABC Traders",
    "location": "Faridabad, Haryana",
    "interested_products": ["Wooden Fork", "Cable Tie"],
    "required_quantity": "50000 pieces",
    "business_requirement": "Wholesale",
    "bulk_and_other_requirements": "Yes, bulk"
  }'

# Validate
curl -X POST http://localhost:8111/api/requirements/validate \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_001"}'

# Save
curl -X POST http://localhost:8111/api/requirements/save \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_001"}'

# Complete
curl -X POST http://localhost:8111/api/requirements/complete \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_001"}'

# End call
curl -X POST http://localhost:8111/api/calls/handler/end \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_001"}'
```

Expected flow:
```
update → ✅ Updated 7 fields
validate → ✅ is_complete: true, pending_fields: []
save → ✅ Saved to MySQL
complete → ✅ Completed successfully
```

#### Test 3: Check database

```bash
# Connect to MySQL
mysql -u root -p seatechcc

# View saved records
SELECT * FROM customer_requirements ORDER BY created_at DESC LIMIT 1;

# Should show your test record
```

## Configuration Options

### Storage Provider Options

#### Option 1: MySQL (Default)
No additional setup needed. Uses existing database.

```env
LEAD_STORAGE_PROVIDER=mysql
```

#### Option 2: Google Sheets
1. Create a Google Cloud project
2. Enable Sheets API
3. Create service account
4. Download JSON credentials

```env
LEAD_STORAGE_PROVIDER=google_sheets
GOOGLE_SHEET_ID=1abc2def3ghi...
GOOGLE_SHEET_TAB=Client_Requirements
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

#### Option 3: Excel
1. Ensure openpyxl is installed
2. Create data directory

```bash
mkdir -p data
```

```env
LEAD_STORAGE_PROVIDER=excel
EXCEL_FILE_PATH=data/client_requirements.xlsx
EXCEL_SHEET_NAME=Client_Requirements
```

### Customizing Greeting and Closing

Edit `.env` file:

```env
CLIENT_GREETING="Your custom greeting here. Keep it professional and friendly."

CLIENT_CLOSING_MESSAGE="Your custom closing. Thank customers and mention follow-up."
```

### Product Customization

Edit `app/core/client_config.py`:

```python
PRODUCTS = [
    "Your Product 1",
    "Your Product 2",
    # ... etc
]

PRODUCT_ALIASES = {
    "product 1": ["alias1", "alias2", "shortname"],
    "product 2": ["variation1", "variation2"],
    # ... etc
}
```

## Common Issues & Fixes

### Issue: "Service not initialized" error

**Cause**: Application startup incomplete

**Fix**:
1. Check logs for startup errors
2. Ensure all services initialized
3. Wait 5 seconds after startup
4. Check Redis and MySQL are running

### Issue: Requirements not saving to database

**Cause**: Table not created or incomplete validation

**Fix**:
1. Run SQL table creation script (Step 2 above)
2. Check validation returns `is_complete: true`
3. Verify all 7 fields are provided
4. Check MySQL connection

### Issue: Greeting service not working

**Cause**: Media service integration not completed

**Fix**:
1. This is currently set up for trigger detection
2. Actual TTS integration is next phase
3. Greeting status is tracked in Redis
4. Check greeting state: `redis-cli get "greeting:{call_id}"`

### Issue: Google Sheets integration failing

**Cause**: Credentials or API access issue

**Fix**:
1. Verify service account JSON exists
2. Check GOOGLE_SHEET_ID is correct
3. Enable Sheets API in Google Cloud Console
4. Share spreadsheet with service account email
5. Test credentials: `gcloud auth application-default print-access-token`

## Next Steps

After successful setup:

1. **Integrate with Asterisk**: Configure actual call routing to use the system
2. **Add TTS/STT**: Implement actual speech synthesis for greetings and closings
3. **Add Gemini Live**: Replace Groq with Gemini Live API
4. **Dashboard**: Build UI to view collected requirements
5. **Analytics**: Add metrics and reporting
6. **Autoresponder**: Email leads after collection

## API Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/requirements/update` | POST | Update requirement fields |
| `/api/requirements/validate` | POST | Check if all required |
| `/api/requirements/save` | POST | Save to storage |
| `/api/requirements/complete` | POST | Finalize conversation |
| `/api/requirements/status/{call_id}` | GET | Check collection status |
| `/api/requirements/questions` | GET | Get all field questions |

## Support & Documentation

- **Full guide**: Read `IMPLEMENTATION_GUIDE.md`
- **Persona & behavior**: Read `persona.md`
- **Collection workflow**: Read `skill.md`
- **Logs**: Check `logs/app.log`
- **Database**: See `customer_requirements` table

## Key Files Modified

- `.env` - Added client configuration variables
- `app/main.py` - Added service initialization
- `app/handlers/ari_event_handler.py` - Added greeting and requirement trigger
- `app/session/redis_session.py` - Fixed session initialization
- `requirements.txt` - Added Google Sheets and Excel dependencies

## Key Files Created

- `app/models/customer_requirements.py` - Database model
- `app/services/customer_requirement_service.py` - Requirement state management
- `app/services/requirement_tools_service.py` - 4 backend tools
- `app/services/lead_storage_service.py` - Multi-adapter storage
- `app/services/greeting_service.py` - Greeting management
- `app/core/client_config.py` - Client configuration
- `app/llm/system_prompts.py` - Dynamic prompt builder
- `app/api/requirements.py` - REST endpoints
- `persona.md` - AI personality guide
- `skill.md` - Detailed workflow
- `IMPLEMENTATION_GUIDE.md` - Comprehensive documentation

---

**Status**: ✅ Complete and ready for testing!
