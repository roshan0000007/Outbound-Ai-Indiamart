# AI Voice Calling - Customer Requirements Collection Implementation Guide

## Overview

This implementation adds a complete customer requirements collection workflow to the existing AI calling system. It collects exactly 7 categories of customer information during inbound calls, validates them, persists to storage (MySQL, Google Sheets, or Excel), and manages the entire conversation lifecycle.

## Architecture

### New Components Created

1. **Models** (`app/models/`)
   - `customer_requirements.py` - Database model for storing requirements

2. **Services** (`app/services/`)
   - `customer_requirement_service.py` - Manages requirement collection state per call
   - `requirement_tools_service.py` - Implements 4 backend tools for LLM interactions
   - `lead_storage_service.py` - Multi-adapter storage (MySQL, Google Sheets, Excel)
   - `greeting_service.py` - Manages greeting playback after call answer

3. **Core** (`app/core/`)
   - `client_config.py` - Client-specific configuration and product aliases

4. **LLM** (`app/llm/`)
   - `system_prompts.py` - Dynamic system prompt builder for different conversation phases

5. **API** (`app/api/`)
   - `requirements.py` - REST endpoints for the 4 backend tools

6. **Configuration Files**
   - `persona.md` - AI personality and business guidelines
   - `skill.md` - Detailed 7-category collection workflow

### Call Lifecycle with Requirements Collection

```
Call Initiated (ARI StasisStart)
↓
Initialize Call Session (Redis)
↓
Initialize Requirement Collection State (Redis)
↓
Play Greeting ("Hello! Good morning...")
↓
Customer Answers
↓
AI begins listening for customer input
↓
Customer provides information
↓
AI extracts info and calls update_customer_requirements() tool
↓
AI validates with validate_customer_requirements() tool
↓
If incomplete: Ask next pending question
↓
If complete: Call save_customer_requirements() tool
↓
Save succeeds: Call complete_customer_conversation() tool
↓
Play Closing Message ("Thank you for sharing...")
↓
Wait for audio playback completion
↓
Call Hangup (ARI StasisEnd)
↓
Cleanup resources
```

## Seven Required Customer Categories

| # | Category | Key | Question | Example |
|---|----------|-----|----------|---------|
| 1 | Customer Name | customer_name | "May I know your name, please?" | "Rahul Kumar" |
| 2 | Company Name | company_name | "Could you please share your company or business name?" | "ABC Traders" |
| 3 | Location | location | "Which city and state are you contacting us from?" | "Faridabad, Haryana" |
| 4 | Interested Products | interested_products | "Which product are you interested in purchasing?..." | "Wooden Fork, Cable Tie" |
| 5 | Required Quantity | required_quantity | "What quantity would you approximately require?" | "50,000 pieces of Wooden Fork" |
| 6 | Business Requirement | business_requirement | "Could you briefly explain your business requirement...?" | "Wholesale distribution to retailers" |
| 7 | Bulk & Other Requirements | bulk_and_other_requirements | "Are you planning to purchase in bulk...?" | "Yes, bulk purchase. Standard packaging." |

## Configuration

### Environment Variables (.env)

```env
# Client Business
CLIENT_BUSINESS_NAME=Industrial Products & Disposable Wooden Products
CLIENT_DEFAULT_LANGUAGE=en-IN
CLIENT_GREETING=Custom greeting message (optional)
CLIENT_CLOSING_MESSAGE=Custom closing message (optional)

# Lead Storage
LEAD_STORAGE_PROVIDER=mysql  # or google_sheets, excel

# Google Sheets (if using google_sheets provider)
GOOGLE_SHEET_ID=your-sheet-id
GOOGLE_SHEET_TAB=Client_Requirements
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Excel (if using excel provider)
EXCEL_FILE_PATH=data/client_requirements.xlsx
EXCEL_SHEET_NAME=Client_Requirements
```

### Product Configuration

Products and aliases are configured in `app/core/client_config.py`:

```python
PRODUCTS = [
    "Cable Tie",
    "Cable Clip",
    "Disposable Wooden Cutlery",
    "Wooden Bowl",
    "Wooden Fork",
    "Other Wooden Products"
]

PRODUCT_ALIASES = {
    "cable tie": ["nylon cable tie", "plastic cable tie", ...],
    "wooden fork": ["wooden fork", "fork"],
    # ... more aliases
}
```

Customize by editing `client_config.py`.

## API Endpoints

### Tool 1: Update Requirements

```
POST /api/requirements/update
Content-Type: application/json

{
  "call_id": "call_12345",
  "customer_name": "Rahul Kumar",
  "company_name": "ABC Traders",
  "location": "Faridabad, Haryana",
  "interested_products": ["Wooden Fork", "Cable Tie"],
  "required_quantity": "50,000 pieces of Wooden Fork",
  "business_requirement": "Wholesale distribution",
  "bulk_and_other_requirements": "Yes, bulk purchase"
}

Response:
{
  "success": true,
  "message": "Requirements updated successfully",
  "updated_fields": ["customer_name", "company_name", ...],
  "current_state": {all 7 fields}
}
```

### Tool 2: Validate Requirements

```
POST /api/requirements/validate
Content-Type: application/json

{
  "call_id": "call_12345"
}

Response:
{
  "is_complete": true,
  "completed_fields": [all 7],
  "pending_fields": [],
  "unclear_fields": [],
  "validation_errors": []
}
```

### Tool 3: Save Requirements

```
POST /api/requirements/save
Content-Type: application/json

{
  "call_id": "call_12345"
}

Response:
{
  "success": true,
  "message": "Requirements saved successfully",
  "storage": "mysql",
  "row_number": null,
  "timestamp": "2026-11-24T10:30:00.000000"
}
```

### Tool 4: Complete Conversation

```
POST /api/requirements/complete
Content-Type: application/json

{
  "call_id": "call_12345",
  "final_message": "Thank you for..."
}

Response:
{
  "success": true,
  "message": "Conversation completed successfully",
  "requirements_saved": true,
  "call_ended": false
}
```

### Utility: Get Status

```
GET /api/requirements/status/{call_id}

Response:
{
  "call_id": "call_12345",
  "requirements": {all current data},
  "validation": {validation result}
}
```

### Utility: Get Questions

```
GET /api/requirements/questions

Response:
{
  "customer_name": "May I know your name, please?",
  "company_name": "Could you please share your company...",
  ... (all 7 questions)
}
```

## Greeting Integration

The greeting is automatically triggered when:
1. Call starts (ARI StasisStart event)
2. Session is initialized
3. Requirement collection initialized
4. Greeting service plays message

The greeting only plays once per call. If customer interrupts, the system continues with normal conversation flow.

## State Management

### Redis Keys

```
call:{call_id}                    - Call session data (TTL: 3600s)
req:{call_id}                     - Requirement collection state (TTL: 3600s)
greeting:{call_id}               - Greeting status (TTL: 60s)
```

### MySQL Tables

```
customer_requirements:
  - id (primary key)
  - call_id (unique)
  - customer_name
  - company_name
  - location
  - interested_products
  - required_quantity
  - business_requirement
  - bulk_and_other_requirements
  - is_complete
  - created_at
  - updated_at
  - source
```

## Google Sheets Integration

### Setup

1. Create a Google Cloud project
2. Create a service account with Sheets API access
3. Download service account key JSON file
4. Set environment variables:

```env
GOOGLE_SHEET_ID=your-spreadsheet-id
GOOGLE_SHEET_TAB=Client_Requirements
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
LEAD_STORAGE_PROVIDER=google_sheets
```

### Sheet Structure

The service automatically creates 7 columns in exact order:

| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| Customer Name | Company Name | Location | Interested Products | Required Quantity | Business Requirement | Bulk & Other Requirements |

Each row = one lead/customer

### Install Dependencies

```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

## Excel Integration

### Setup

```env
LEAD_STORAGE_PROVIDER=excel
EXCEL_FILE_PATH=data/client_requirements.xlsx
EXCEL_SHEET_NAME=Client_Requirements
```

### Install Dependencies

```bash
pip install openpyxl
```

The service automatically creates the file and headers if they don't exist.

## Conversation Flow Example

```
SYSTEM: [Call answered, greeting ready]

AI: "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, 
cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. We 
would like to understand your business requirements and the products you may be interested 
in. May I take a few details from you?"

CUSTOMER: "Sure, thank you."

AI: "Great! May I know your name, please?"

CUSTOMER: "My name is Rahul Kumar, I run ABC Traders from Faridabad, Haryana."

[AI extracts: customer_name="Rahul Kumar", company_name="ABC Traders", 
location="Faridabad, Haryana"]

[Remaining questions: location (needs confirmation), interested_products, required_quantity, 
business_requirement, bulk_and_other_requirements]

AI: "Thank you, Rahul. Just to confirm, ABC Traders is in Faridabad, Haryana, correct?"

CUSTOMER: "Yes, that's right."

[Location confirmed: "Faridabad, Haryana"]
[Next pending: interested_products]

AI: "Which products are you interested in? We offer cable ties, cable clips, 
disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."

CUSTOMER: "We need wooden forks and cable ties. Around 50,000 pieces of forks 
and 20,000 pieces of cable ties for wholesale distribution to retailers."

[AI extracts: interested_products=["Wooden Fork", "Cable Tie"], 
required_quantity="50,000 pieces of Wooden Fork, 20,000 pieces of Cable Tie",
business_requirement="Wholesale distribution to retailers"]
[Next pending: bulk_and_other_requirements]

AI: "Are you planning to purchase in bulk, and do you have any other specific requirements?"

CUSTOMER: "Yes, definitely bulk. We need standard packaging but would prefer 
monthly delivery terms."

[AI extracts: bulk_and_other_requirements="Yes, bulk purchase. Standard packaging. 
Monthly delivery terms preferred."]

[All 7 fields complete. Validation passes. Save to MySQL.]

AI: "Thank you for sharing your requirements with us. We have noted your product 
and quantity requirements. Our sales team will review the details and contact you 
shortly for further discussion. Thank you for your valuable time. Have a great day!"

[Closing message plays]
[Audio playback completes]
[Call hangup initiated]
[Resources cleaned up]
```

## Testing

### Manual Testing via API

#### 1. Initialize a call
```bash
curl -X POST http://localhost:8111/api/calls/handler/start \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "test_call_001",
    "caller_number": "9876543210",
    "dnid": "1234",
    "user_id": 1
  }'
```

#### 2. Update requirements
```bash
curl -X POST http://localhost:8111/api/requirements/update \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "test_call_001",
    "customer_name": "Rahul Kumar",
    "company_name": "ABC Traders",
    "location": "Faridabad, Haryana",
    "interested_products": ["Wooden Fork"],
    "required_quantity": "50000 pieces",
    "business_requirement": "Wholesale",
    "bulk_and_other_requirements": "Yes"
  }'
```

#### 3. Validate requirements
```bash
curl -X POST http://localhost:8111/api/requirements/validate \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_call_001"}'
```

#### 4. Save requirements
```bash
curl -X POST http://localhost:8111/api/requirements/save \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_call_001"}'
```

#### 5. Get status
```bash
curl -X GET http://localhost:8111/api/requirements/status/test_call_001
```

#### 6. End call
```bash
curl -X POST http://localhost:8111/api/calls/handler/end \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test_call_001"}'
```

## Database Setup

### Create Required Table

```sql
CREATE TABLE customer_requirements (
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
```

## Troubleshooting

### Requirement collection not initializing

Check logs:
```bash
grep "ReqService" logs/app.log
```

Verify service initialized in startup:
```bash
grep "✓ Customer requirement service" logs/app.log
```

### Greeting not playing

Check greeting service logs:
```bash
grep "Greeting" logs/app.log
```

Verify greeting configuration:
```bash
curl http://localhost:8111/api/requirements/questions | grep customer_name
```

### Save failing to database

Verify table exists:
```sql
DESC customer_requirements;
```

Check database connection:
```bash
grep "DB Pool" logs/app.log | head -5
```

### Google Sheets integration not working

1. Verify credentials file exists:
```bash
ls -la /path/to/service-account-key.json
```

2. Check API is enabled in Google Cloud Console
3. Verify sheet ID is correct:
```bash
curl https://sheets.googleapis.com/v4/spreadsheets/SHEET_ID/values/A1 \
  -H "Authorization: Bearer $(gcloud auth print-access-token)"
```

### Excel file not being created

1. Verify directory exists:
```bash
ls -la data/
```

2. Check permissions:
```bash
touch data/test.xlsx
rm data/test.xlsx
```

3. Check openpyxl is installed:
```bash
python -c "import openpyxl; print(openpyxl.__version__)"
```

## Performance Considerations

- **Redis state TTL**: 3600 seconds (1 hour) - Increase if calls are longer
- **Greeting state TTL**: 60 seconds - Quick cleanup for greeting status
- **Database connection pool**: 10-150 connections - Adjust based on concurrent calls
- **Tool execution**: All tool operations are async and non-blocking

## Production Checklist

- [ ] Database table created with proper indices
- [ ] MySQL connection pool configured for expected call volume
- [ ] Redis connection configured and tested
- [ ] Google Sheets credentials set up (if using)
- [ ] Excel file path accessible and writable (if using)
- [ ] All environment variables configured
- [ ] Client business name, greeting, and closing customized
- [ ] Product list and aliases match business products
- [ ] Application tested with sample calls
- [ ] Logging configured to appropriate level (INFO for production)
- [ ] Backups configured for Excel file
- [ ] Monitoring set up for failed saves
- [ ] Rate limiting considered for API endpoints

## Support

For issues or questions:
1. Check application logs: `grep -i "error\|warning" logs/app.log`
2. Review this documentation
3. Test manually via API endpoints
4. Verify all configuration variables
5. Check database and storage connectivity
