# Skill: Customer Requirement Collection

## Overview

This skill implements a structured conversation flow to collect exactly seven categories of customer business requirements during inbound calls. The collected information is validated, persisted to Google Sheets/Excel, and used to generate leads for the sales team.

## Seven Required Categories

### 1. CUSTOMER NAME
**Question:** "May I know your name, please?"
**Internal Key:** `customer_name`
**Type:** String (max 100 characters)
**Validation Rules:**
- Cannot be empty or null
- Accept actual names provided by customer
- If unclear, ask customer to repeat or spell
- Do not guess spellings

**Examples:**
- "Rahul"
- "Priya Sharma"
- "Amit Kumar"

---

### 2. COMPANY NAME
**Question:** "Could you please share your company or business name?"
**Internal Key:** `company_name`
**Type:** String (max 150 characters)
**Validation Rules:**
- Cannot be empty or null
- Accept registered company name or trading name
- Accept sole proprietorship/unregistered business names
- Do not invent a company name
- If customer says "I don't have a company yet", record as "Self-Employed" or similar

**Examples:**
- "ABC Traders"
- "XYZ Manufacturing Ltd"
- "Self-Employed"
- "Home Business"

---

### 3. LOCATION
**Question:** "Which city and state are you contacting us from?"
**Internal Key:** `location`
**Type:** String (City, State format, max 100 characters)
**Validation Rules:**
- Save city and state together in ONE field
- Do not assume state from ambiguous city name
- If city is known but state unclear, ask confirmation
- Format: "City, State"

**Examples:**
- "Faridabad, Haryana"
- "Delhi, Delhi"
- "Mumbai, Maharashtra"
- "Jaipur, Rajasthan"
- "Pune, Maharashtra"

**Clarification Pattern:**
Customer: "I'm in Noida"
AI: "Thank you. Just to confirm, is that Noida in Uttar Pradesh?"

---

### 4. INTERESTED PRODUCTS
**Question:** "Which product are you interested in purchasing? We deal in cable ties, cable clips, disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."
**Internal Key:** `interested_products`
**Type:** Array of Strings (comma-separated list)
**Validation Rules:**
- Allow multiple products
- Recognize aliases and variations (see persona.md)
- If description could refer to multiple products, ask clarification
- If description too vague ("wooden items"), ask for specifics
- Do not classify unclear products without confirmation
- Store each product separated by commas

**Examples:**
- "Cable Tie"
- "Cable Tie, Cable Clip"
- "Wooden Fork, Wooden Bowl"
- "Disposable Wooden Cutlery, Cable Tie"

**Product Recognition:**
- "Nylon cable ties" → "Cable Tie"
- "Wire clips" → "Cable Clip"
- "Wooden spoons" → "Disposable Wooden Cutlery"
- "Wooden forks" → "Wooden Fork"
- "Wooden items" → Ask: "Which specific wooden products? Forks, bowls, or cutlery?"

---

### 5. REQUIRED QUANTITY
**Question:** "What quantity would you approximately require?"
**Internal Key:** `required_quantity`
**Type:** String with quantity and unit (e.g., "10,000 pieces", "5 tons")
**Validation Rules:**
- Never invent a quantity
- Never assume a unit
- If only number given, ask what unit
- If unclear, repeat back and request confirmation
- For multiple products, capture each product's quantity separately within this single field
- Accept quantities like "pieces", "cartons", "kg", "boxes", etc.

**Examples:**
- "10,000 pieces"
- "5,000 pieces of Wooden Fork"
- "50 boxes (10,000 pieces)"
- "2 tons of Cable Tie"
- "5,000 pieces of Cable Tie and 3,000 pieces of Wooden Fork"

**Clarification Pattern:**
Customer: "Around fifty thousand"
AI: "Certainly. Just to confirm, are you referring to fifty thousand pieces?"

Customer: "Ten thousand"
AI: "Thank you. Just to clarify, would that be 10,000 pieces or in a different unit?"

**Multi-Product Quantities:**
If customer provides multiple products, store all quantities:
- "5,000 pieces of Cable Tie, 3,000 pieces of Wooden Fork, 2,000 pieces of Wooden Bowl"

---

### 6. BUSINESS REQUIREMENT
**Question:** "Could you briefly explain your business requirement and how you plan to use these products?"
**Internal Key:** `business_requirement`
**Type:** String (free-form text, max 500 characters)
**Validation Rules:**
- Allow natural free-form answers
- Do not force predefined categories
- Accept any legitimate business use case
- Capture the actual business context

**Common Business Requirements:**
- Wholesale distribution
- Retail sales
- Manufacturing/Assembly
- Distribution network
- Reselling to retailers
- Hotel/Restaurant operations
- Corporate purchasing
- Industrial manufacturing
- Packaging/Assembly use
- End-user consumption

**Examples:**
- "Wholesale distribution to retail stores"
- "Manufacturing - we use these in our production process"
- "Hotel supplies for restaurant use"
- "Corporate gifts and merchandise"
- "Retail sales through our shop"
- "Direct end-use in our factory"

---

### 7. BULK & OTHER REQUIREMENTS
**Question:** "Are you planning to purchase in bulk, and do you have any other specific requirements?"
**Internal Key:** `bulk_and_other_requirements`
**Type:** String (combined multi-line, max 500 characters)
**Validation Rules:**
- Combine multiple details into this single field
- If customer has no additional requirements, record clearly
- Do not ask unnecessary additional questions
- If already answered partially, ask only for missing details

**Capture Within This Category:**
1. **Bulk Purchase Status:** Yes / No / Not Sure
2. **Required Size:** (if applicable)
3. **Required Material:** (if applicable)
4. **Packaging Requirements:** (if applicable)
5. **Customization Requirements:** (if applicable)
6. **Other Product-Specific Requirements:** (if any)

**Examples:**
- "Yes, planning bulk purchase. No specific requirements."
- "No bulk plans. Standard packaging is fine."
- "Yes, bulk purchase. Need custom packaging with our logo."
- "Not sure about bulk yet. Standard materials preferred."
- "Bulk: Yes. Need smaller individual packs for resale. Custom branding required."

**Clarification Pattern:**
Customer: "We need bulk quantities but custom packaging"
AI: "Understood. For the packaging, could you describe what customization you're looking for?"

---

## Information Extraction Rules

### Critical Rules

1. **Distinguish Information States:**
   - Confirmed information → Use for storage
   - Unclear information → Ask again politely
   - Missing information → Ask appropriately
   - Corrected information → Update to latest value
   - Not provided → Mark as pending

2. **Handle Multiple Answers in One Response:**
   - Extract ALL supported information
   - Update ALL relevant fields
   - Skip questions for already-answered topics
   - Identify next unanswered field
   - Ask only the next appropriate question

3. **Maintain Complete Independence:**
   - Create separate state for every active call
   - Do not use shared global mutable state
   - Use call_id as unique key
   - Clean up completely after call ends

4. **Never Treat Uncertainty as Confirmation:**
   - If you cannot clearly understand, ask again
   - Examples:
     - Customer: "About fifty thousand" → AI: "Just to confirm, fifty thousand pieces?"
     - Customer: "Some wooden products" → AI: "Which specific products - forks, bowls, or cutlery?"
     - Customer: "We're in a city near Delhi" → AI: "Could you tell me the specific city name?"

### Question Selection Logic

After every customer response:

1. Extract all supported information from response
2. Update relevant fields in customer_requirements
3. Validate updated information
4. Identify pending/unclear required fields
5. Ask only the next unanswered or unclear field
6. Skip questions for already-answered topics

**Pending Fields List:**
```python
pending_fields = [
    "customer_name",
    "company_name",
    "location",
    "interested_products",
    "required_quantity",
    "business_requirement",
    "bulk_and_other_requirements"
]
```

### Completion Criteria

Conversation is complete when:
1. ✅ All 7 fields have been asked
2. ✅ All 7 fields have been answered (not null/empty)
3. ✅ All answers have been validated
4. ✅ No field is marked as "unclear" or "needs_confirmation"
5. ✅ Customer confirms understanding (optional but good practice)

After completion:
1. Call validate_customer_requirements() tool
2. If validation returns is_complete=true, proceed to save
3. If validation returns pending_fields, ask remaining questions
4. Only after validation success, call save_customer_requirements() tool

---

## Tool Integration

### Tool 1: update_customer_requirements

**Purpose:** Extract and update customer requirement categories

**When to Call:**
- After every customer response that provides new information
- When correcting previously provided information

**Input Structure:**
```json
{
  "call_id": "call_12345",
  "customer_name": null,
  "company_name": null,
  "location": null,
  "interested_products": [],
  "required_quantity": null,
  "business_requirement": null,
  "bulk_and_other_requirements": null
}
```

**Rules:**
- Update only supported information
- Preserve existing confirmed fields
- Support corrections (overwrite if necessary)
- Do not overwrite valid info with null
- Keep uncertain info as pending

---

### Tool 2: validate_customer_requirements

**Purpose:** Validate current per-call customer information

**When to Call:**
- After extracting information from last customer response
- Before attempting to save

**Returns Structure:**
```json
{
  "is_complete": true/false,
  "completed_fields": ["customer_name", "company_name"],
  "pending_fields": ["location", "interested_products"],
  "unclear_fields": ["required_quantity"],
  "validation_errors": ["Quantity format invalid"]
}
```

**Decision Logic:**
- If is_complete=true → Proceed to save
- If is_complete=false AND pending_fields exists → Ask next field
- If is_complete=false AND unclear_fields exists → Ask for clarification

---

### Tool 3: save_customer_requirements

**Purpose:** Persist validated customer information to storage

**When to Call:**
- Only after validate_customer_requirements returns is_complete=true
- Never call with incomplete or unvalidated data

**Saves Exactly 7 Columns:**
1. Customer Name
2. Company Name
3. Location
4. Interested Products
5. Required Quantity
6. Business Requirement
7. Bulk & Other Requirements

**Rules:**
- Validate data before saving
- Return actual backend success/failure
- Prevent duplicate saves
- Never claim success without backend confirmation
- Handle storage errors gracefully

---

### Tool 4: complete_customer_conversation

**Purpose:** Start controlled completion workflow

**When to Call:**
- After save_customer_requirements returns success
- Before triggering final closing message

**Workflow:**
1. Verify save operation succeeded
2. Prevent additional requirement questions
3. Trigger final closing message
4. Wait for final audio playback completion
5. Initiate call hangup
6. Clean up Gemini session and resources

---

## Example Conversation Flow

```
SYSTEM: [Greeting plays]
AI: "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, 
cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. We 
would like to understand your business requirements and the products you may be interested 
in. May I take a few details from you?"

CUSTOMER: "Sure, thank you."

[AI_ACTION] No requirement data extracted. Ask first field.

AI: "Great! May I know your name, please?"

CUSTOMER: "My name is Rahul Kumar, I run ABC Traders from Faridabad."

[AI_ACTION] Extract: 
  - customer_name = "Rahul Kumar"
  - company_name = "ABC Traders"
  - location = "Faridabad" (needs confirmation of state)
Call update_customer_requirements() with these values.

[AI_ACTION] Ask for state confirmation.

AI: "Thank you, Rahul. Just to confirm, ABC Traders is in Faridabad, Haryana, correct?"

CUSTOMER: "Yes, that's right."

[AI_ACTION] location updated to "Faridabad, Haryana"

[AI_ACTION] Check pending fields:
  - customer_name ✅ (Rahul Kumar)
  - company_name ✅ (ABC Traders)
  - location ✅ (Faridabad, Haryana)
  - interested_products ❌
  - required_quantity ❌
  - business_requirement ❌
  - bulk_and_other_requirements ❌

[AI_ACTION] Ask next pending field.

AI: "Which products are you interested in? We offer cable ties, cable clips, 
disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."

CUSTOMER: "We need wooden forks and cable ties. Around 50,000 pieces of forks 
and 20,000 pieces of cable ties for wholesale distribution to retailers."

[AI_ACTION] Extract:
  - interested_products = "Wooden Fork, Cable Tie"
  - required_quantity = "50,000 pieces of Wooden Fork, 20,000 pieces of Cable Tie"
  - business_requirement = "Wholesale distribution to retailers"
Call update_customer_requirements() with these values.

[AI_ACTION] Check pending fields:
  - customer_name ✅
  - company_name ✅
  - location ✅
  - interested_products ✅
  - required_quantity ✅
  - business_requirement ✅
  - bulk_and_other_requirements ❌

[AI_ACTION] Ask final pending field.

AI: "Are you planning to purchase in bulk, and do you have any other specific requirements?"

CUSTOMER: "Yes, definitely bulk. We need standard packaging but would prefer 
monthly delivery terms."

[AI_ACTION] Extract:
  - bulk_and_other_requirements = "Yes, bulk purchase confirmed. Standard packaging. 
    Requesting monthly delivery terms."
Call update_customer_requirements() with this value.

[AI_ACTION] All 7 fields now have values. Call validate_customer_requirements().

VALIDATION RESPONSE:
{
  "is_complete": true,
  "completed_fields": [all 7],
  "pending_fields": [],
  "unclear_fields": []
}

[AI_ACTION] Call save_customer_requirements() to persist to Google Sheets.

SAVE RESPONSE:
{
  "success": true,
  "row_number": 42,
  "storage": "google_sheets"
}

[AI_ACTION] Save succeeded. Trigger final closing message.

AI: "Thank you for sharing your requirements with us. We have noted your product 
and quantity requirements. Our sales team will review the details and contact you 
shortly for further discussion. Thank you for your valuable time. Have a great day!"

[AI_ACTION] Wait for final audio playback to complete.

[AI_ACTION] Call complete_customer_conversation() to trigger hangup.

[SYSTEM] Audio playback completed → Call hangup initiated → Session cleanup
```

---

## Error Handling

### Invalid or Unclear Information

**Pattern:**
```
Customer provides unclear/ambiguous information
  → AI recognizes uncertainty
  → AI politely asks for clarification
  → Customer provides correction
  → AI confirms and updates field
```

### Missing Information

**Pattern:**
```
Customer skips a required field
  → AI identifies pending field
  → AI asks appropriate question
  → Customer provides information
  → AI confirms and updates field
```

### Corrections

**Pattern:**
```
Customer corrects previously provided information
  → AI identifies which field is being corrected
  → AI updates only that field
  → AI preserves all other valid information
  → AI confirms the correction
```

### Storage Failures

**Pattern:**
```
save_customer_requirements() fails
  → Return error without claiming success
  → Log the failure
  → Inform customer: "I encountered an issue saving your information. 
    Please hold while I try again."
  → Do NOT proceed to completion workflow
  → Do NOT hang up
  → Retry save operation
```

---

## Configuration

All aspects can be customized through environment variables:

```env
# Client Business
CLIENT_BUSINESS_NAME=Industrial Products Supplier
CLIENT_GREETING=Hello! Good morning...
CLIENT_CLOSING_MESSAGE=Thank you for sharing...
CLIENT_DEFAULT_LANGUAGE=en-IN

# Storage
LEAD_STORAGE_PROVIDER=google_sheets
GOOGLE_SHEET_ID=1abc2def3ghi...
GOOGLE_SHEET_TAB=Client_Requirements
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# Or for Excel
EXCEL_FILE_PATH=/data/client_requirements.xlsx
EXCEL_SHEET_NAME=Client_Requirements
```

---

## Testing Checklist

- [ ] Greeting plays exactly once per call
- [ ] All 7 categories extracted correctly
- [ ] Multiple products handled properly
- [ ] Quantities with units captured correctly
- [ ] Corrections update only relevant field
- [ ] Validation works for all scenarios
- [ ] Google Sheets persistence works
- [ ] Final message plays before hangup
- [ ] Session cleanup completes fully
- [ ] Multiple concurrent calls maintain independent state
