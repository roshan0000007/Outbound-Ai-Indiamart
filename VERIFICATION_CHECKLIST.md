# Verification Checklist - Complete Implementation

Use this checklist to verify all components are properly installed and working.

## ✅ Phase 1: Code Files Created

### Models
- [ ] `app/models/customer_requirements.py` exists (40 lines)
  ```bash
  ls -la app/models/customer_requirements.py
  ```

### Services
- [ ] `app/services/customer_requirement_service.py` exists (350+ lines)
- [ ] `app/services/requirement_tools_service.py` exists (350+ lines)
- [ ] `app/services/lead_storage_service.py` exists (450+ lines)
- [ ] `app/services/greeting_service.py` exists (100+ lines)

### Core
- [ ] `app/core/client_config.py` exists (200+ lines)

### LLM
- [ ] `app/llm/system_prompts.py` exists (300+ lines)

### API
- [ ] `app/api/requirements.py` exists (280+ lines)

### Documentation
- [ ] `persona.md` exists (400+ lines)
- [ ] `skill.md` exists (600+ lines)
- [ ] `IMPLEMENTATION_GUIDE.md` exists (400+ lines)
- [ ] `QUICK_START.md` exists (300+ lines)
- [ ] `IMPLEMENTATION_SUMMARY.md` exists (400+ lines)

**Total Files Created**: 15 ✅

```bash
# Verify file count
find app -type f -name "*.py" | grep -E "(customer_requirement|requirement_tool|lead_storage|greeting|client_config|system_prompt|requirements)" | wc -l
# Should output: 7
```

---

## ✅ Phase 2: Code Files Modified

### Configuration
- [ ] `.env` has CLIENT_* variables
  ```bash
  grep "CLIENT_BUSINESS_NAME" .env
  grep "LEAD_STORAGE_PROVIDER" .env
  ```

### Application
- [ ] `app/main.py` initializes new services
  ```bash
  grep "init_customer_requirement_service" app/main.py
  grep "init_requirement_tools_service" app/main.py
  grep "init_lead_storage_service" app/main.py
  grep "init_greeting_service" app/main.py
  ```

### Event Handling
- [ ] `app/handlers/ari_event_handler.py` calls greeting service
  ```bash
  grep "greeting_service" app/handlers/ari_event_handler.py
  ```

### Call Handler
- [ ] `app/handlers/call_handler.py` cleans up requirements
  ```bash
  grep "cleanup_call" app/handlers/call_handler.py
  ```

### Session
- [ ] `app/session/redis_session.py` fixed campaign_id bug
  ```bash
  grep "campaign_id.*0" app/session/redis_session.py
  ```

### Dependencies
- [ ] `requirements.txt` has Google libraries
  ```bash
  grep "google-auth" requirements.txt
  grep "google-api-python-client" requirements.txt
  ```

**Total Files Modified**: 6 ✅

---

## ✅ Phase 3: Dependencies Installed

```bash
# Check if dependencies are installed
pip show groq | grep Name
pip show google-auth-oauthlib | grep Name
pip show google-auth-httplib2 | grep Name
pip show google-api-python-client | grep Name
pip show openpyxl | grep Name

# Or all at once
pip list | grep -E "groq|google-auth|google-api|openpyxl"
```

**Expected Output**:
```
groq              0.7.x or higher
google-auth-oauthlib  1.1.x or higher
google-auth-httplib2  0.2.x or higher
google-api-python-client  2.1x.x or higher
openpyxl          3.1.x or higher
```

✅ All dependencies present?

---

## ✅ Phase 4: Configuration Variables

Check `.env` has all required variables:

```bash
# Client configuration
grep "CLIENT_BUSINESS_NAME" .env && echo "✅"
grep "CLIENT_DEFAULT_LANGUAGE" .env && echo "✅"
grep "CLIENT_GREETING" .env && echo "✅"
grep "CLIENT_CLOSING_MESSAGE" .env && echo "✅"

# Storage configuration
grep "LEAD_STORAGE_PROVIDER" .env && echo "✅"
grep "GOOGLE_SHEET_ID" .env && echo "✅"
grep "EXCEL_FILE_PATH" .env && echo "✅"
```

**Expected**: 7 variables configured ✅

---

## ✅ Phase 5: Database Schema

### Create Table

```bash
mysql -u root -p -e "
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

DESCRIBE customer_requirements;
"
```

**Expected**: Table with 13 columns ✅

### Verify Table

```bash
mysql -u root -p -e "
USE seatechcc;
DESC customer_requirements;
SELECT COUNT(*) as 'Column Count' FROM information_schema.columns WHERE table_name='customer_requirements' AND table_schema='seatechcc';
"
```

**Expected**: 13 columns ✅

---

## ✅ Phase 6: Application Startup

### Start Application

```bash
cd "d:\OutBoundAi\Anukul Client"
python app/main.py

# Or with uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8111 --reload
```

### Check Startup Logs

Look for these messages:

```
[STARTUP] ✓ Customer requirement service initialized
[STARTUP] ✓ Requirement tools service initialized
[STARTUP] ✓ Lead storage service initialized
[STARTUP] ✓ Greeting service initialized
```

✅ All services initialized?

---

## ✅ Phase 7: API Endpoints Verification

### Test Endpoint Access

```bash
# Check if requirements API is loaded
curl http://localhost:8111/api/requirements/questions
```

**Expected Response**: JSON with 7 field questions ✅

### Test Individual Endpoints

```bash
# 1. Update endpoint
curl -X POST http://localhost:8111/api/requirements/update \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test", "customer_name": "Test"}'
# Expected: 200 OK with success message

# 2. Validate endpoint
curl -X POST http://localhost:8111/api/requirements/validate \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test"}'
# Expected: 200 OK with validation result

# 3. Get questions
curl http://localhost:8111/api/requirements/questions
# Expected: 200 OK with all 7 questions

# 4. Get status
curl http://localhost:8111/api/requirements/status/test
# Expected: 200 OK with status object
```

✅ All endpoints responding?

---

## ✅ Phase 8: Redis Connection

```bash
# Test Redis
redis-cli ping
# Expected: PONG

# Check Redis keys
redis-cli KEYS "*"
# After a call, should see keys like: call:*, req:*, greeting:*
```

✅ Redis working?

---

## ✅ Phase 9: MySQL Connection

```bash
# Test MySQL connection
mysql -u root -p -e "SELECT 1 as connection_test;"
# Expected: Shows 1

# Verify table
mysql -u root -p -e "DESC seatechcc.customer_requirements;"
# Expected: Shows all 13 columns

# Check for test data
mysql -u root -p -e "SELECT * FROM seatechcc.customer_requirements LIMIT 1;"
```

✅ MySQL working and table accessible?

---

## ✅ Phase 10: Full API Test Workflow

```bash
#!/bin/bash

API="http://localhost:8111"
CALL_ID="test_$(date +%s)"

echo "Testing: $CALL_ID"
echo ""

# 1. Get questions
echo "1. Getting questions..."
curl -s $API/api/requirements/questions | jq '.customer_name'

# 2. Get initial status
echo -e "\n2. Getting initial status..."
curl -s -X GET $API/api/requirements/status/$CALL_ID | jq '.validation.is_complete'

# 3. Update all fields
echo -e "\n3. Updating all fields..."
curl -s -X POST $API/api/requirements/update \
  -H "Content-Type: application/json" \
  -d "{
    \"call_id\": \"$CALL_ID\",
    \"customer_name\": \"Rahul Kumar\",
    \"company_name\": \"ABC Traders\",
    \"location\": \"Faridabad, Haryana\",
    \"interested_products\": [\"Wooden Fork\", \"Cable Tie\"],
    \"required_quantity\": \"50000 pieces\",
    \"business_requirement\": \"Wholesale\",
    \"bulk_and_other_requirements\": \"Yes bulk\"
  }" | jq '.success'

# 4. Validate
echo -e "\n4. Validating..."
curl -s -X POST $API/api/requirements/validate \
  -H "Content-Type: application/json" \
  -d "{\"call_id\": \"$CALL_ID\"}" | jq '.is_complete'

# 5. Save
echo -e "\n5. Saving..."
curl -s -X POST $API/api/requirements/save \
  -H "Content-Type: application/json" \
  -d "{\"call_id\": \"$CALL_ID\"}" | jq '.success'

# 6. Complete
echo -e "\n6. Completing..."
curl -s -X POST $API/api/requirements/complete \
  -H "Content-Type: application/json" \
  -d "{\"call_id\": \"$CALL_ID\"}" | jq '.success'

echo -e "\n✅ Complete workflow test finished"
```

**Expected**: All steps succeed ✅

---

## ✅ Phase 11: Database Record Verification

```bash
# After running API test workflow
mysql -u root -p -e "
USE seatechcc;
SELECT call_id, customer_name, company_name, location, is_complete 
FROM customer_requirements 
ORDER BY created_at DESC 
LIMIT 1;
"
```

**Expected**: Shows one test record with is_complete=1 ✅

---

## ✅ Phase 12: Configuration Verification

### Check Client Config

```bash
python -c "
from app.core.client_config import ClientConfig
print('Business:', ClientConfig.BUSINESS_NAME)
print('Language:', ClientConfig.DEFAULT_LANGUAGE)
print('Products:', len(ClientConfig.PRODUCTS))
print('Greeting (first 50):', ClientConfig.GREETING[:50])
"
```

**Expected**:
- Business name set
- Language: en-IN
- Products: 6
- Greeting text visible

✅ Configuration loaded correctly?

### Check Product Aliases

```bash
python -c "
from app.core.client_config import ClientConfig
test_products = [
    ('wooden fork', 'Wooden Fork'),
    ('nylon cable ties', 'Cable Tie'),
    ('wire clips', 'Cable Clip')
]
for input_text, expected in test_products:
    result = ClientConfig.normalize_product(input_text)
    status = '✅' if result == expected else '❌'
    print(f'{status} {input_text} -> {result} (expected: {expected})')
"
```

**Expected**: All 3 tests pass ✅

---

## ✅ Phase 13: Greeting Service Verification

```bash
python -c "
from app.services.greeting_service import GreetingService
from app.core.config import log
import asyncio

async def test_greeting():
    service = GreetingService()
    result = await service.play_greeting('test_greeting')
    return result

result = asyncio.run(test_greeting())
print('Greeting service working:', result)
"
```

**Expected**: Returns True ✅

---

## ✅ Phase 14: System Prompt Builder Verification

```bash
python -c "
from app.llm.system_prompts import build_full_system_prompt

# Test greeting phase
prompt = build_full_system_prompt('greeting')
print('Greeting prompt length:', len(prompt))

# Test collection phase
prompt = build_full_system_prompt('collection', 
    completed_fields=['customer_name'],
    pending_fields=['company_name', 'location'],
    current_data={'customer_name': 'Rahul'})
print('Collection prompt length:', len(prompt))

# Test closing phase
prompt = build_full_system_prompt('closing')
print('Closing prompt length:', len(prompt))

print('✅ All prompt phases generated successfully')
"
```

**Expected**: All prompt lengths > 100, all phases work ✅

---

## ✅ Phase 15: Documentation Verification

```bash
# Check all documentation files exist
files=(
    "persona.md"
    "skill.md"
    "IMPLEMENTATION_GUIDE.md"
    "QUICK_START.md"
    "IMPLEMENTATION_SUMMARY.md"
    "VERIFICATION_CHECKLIST.md"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        echo "✅ $file ($lines lines)"
    else
        echo "❌ $file MISSING"
    fi
done
```

**Expected**: All 6 documentation files exist ✅

---

## ✅ Final Verification Script

Save as `verify_installation.sh`:

```bash
#!/bin/bash

echo "================================"
echo "Verification Report"
echo "================================"
echo ""

PASS=0
FAIL=0

# 1. Check Python files
echo "1. Checking Python files..."
files=(
    "app/models/customer_requirements.py"
    "app/services/customer_requirement_service.py"
    "app/services/requirement_tools_service.py"
    "app/services/lead_storage_service.py"
    "app/services/greeting_service.py"
    "app/core/client_config.py"
    "app/llm/system_prompts.py"
    "app/api/requirements.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
        ((PASS++))
    else
        echo "  ❌ $file MISSING"
        ((FAIL++))
    fi
done

echo ""
echo "2. Checking documentation..."
docs=(
    "persona.md"
    "skill.md"
    "IMPLEMENTATION_GUIDE.md"
    "QUICK_START.md"
    "IMPLEMENTATION_SUMMARY.md"
)

for doc in "${docs[@]}"; do
    if [ -f "$doc" ]; then
        echo "  ✅ $doc"
        ((PASS++))
    else
        echo "  ❌ $doc MISSING"
        ((FAIL++))
    fi
done

echo ""
echo "3. Checking configuration..."
if grep -q "CLIENT_BUSINESS_NAME" .env; then
    echo "  ✅ CLIENT_BUSINESS_NAME configured"
    ((PASS++))
else
    echo "  ❌ CLIENT_BUSINESS_NAME missing"
    ((FAIL++))
fi

if grep -q "LEAD_STORAGE_PROVIDER" .env; then
    echo "  ✅ LEAD_STORAGE_PROVIDER configured"
    ((PASS++))
else
    echo "  ❌ LEAD_STORAGE_PROVIDER missing"
    ((FAIL++))
fi

echo ""
echo "================================"
echo "Summary: $PASS ✅ | $FAIL ❌"
echo "================================"

if [ $FAIL -eq 0 ]; then
    echo "✅ All verifications passed!"
    exit 0
else
    echo "❌ Some items failed. Check above."
    exit 1
fi
```

Run:
```bash
bash verify_installation.sh
```

---

## Expected Final Status

```
================================
Verification Report
================================

1. Checking Python files...
  ✅ app/models/customer_requirements.py
  ✅ app/services/customer_requirement_service.py
  ✅ app/services/requirement_tools_service.py
  ✅ app/services/lead_storage_service.py
  ✅ app/services/greeting_service.py
  ✅ app/core/client_config.py
  ✅ app/llm/system_prompts.py
  ✅ app/api/requirements.py

2. Checking documentation...
  ✅ persona.md
  ✅ skill.md
  ✅ IMPLEMENTATION_GUIDE.md
  ✅ QUICK_START.md
  ✅ IMPLEMENTATION_SUMMARY.md

3. Checking configuration...
  ✅ CLIENT_BUSINESS_NAME configured
  ✅ LEAD_STORAGE_PROVIDER configured

================================
Summary: 15 ✅ | 0 ❌
================================

✅ All verifications passed!
```

---

## Troubleshooting Failed Verifications

| Issue | Solution |
|-------|----------|
| Python file missing | Re-read file creation section |
| Config variable missing | Edit .env and add variable |
| Database table missing | Run SQL creation script |
| API not responding | Check if app started successfully |
| Dependencies not installed | Run `pip install -r requirements.txt` |
| Redis not responding | Verify Redis server is running |
| MySQL not responding | Verify MySQL server is running |

---

## Sign-Off

Once all verifications pass:

- [ ] All 15 Python/config files created ✅
- [ ] All 5+ files modified correctly ✅
- [ ] All dependencies installed ✅
- [ ] All 10+ config variables set ✅
- [ ] Database table created ✅
- [ ] Application starts without errors ✅
- [ ] All API endpoints working ✅
- [ ] Full workflow test passes ✅
- [ ] Records saved to database ✅
- [ ] Configuration loads correctly ✅
- [ ] Product aliases work ✅
- [ ] Greeting service works ✅
- [ ] System prompts generate ✅
- [ ] All documentation present ✅

**Status**: ✅ **READY FOR PRODUCTION**

**Next Steps**:
1. Read QUICK_START.md for setup
2. Read IMPLEMENTATION_GUIDE.md for details
3. Test with real call flow
4. Integrate with Asterisk
5. Deploy to production

---

Generated: November 24, 2026
