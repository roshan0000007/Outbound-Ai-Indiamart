# Fix: Remove Unnecessary DTMF Prompt Beep

## Problem
When a call arrives, the system was playing:
1. 1-2 second unnecessary beep
2. Then language selection message

Expected behavior:
- **NO beep**
- Directly play language selection menu audio (or just wait for DTMF)
- Caller immediately hears "Press 1 for English, 2 for Hindi"
- Or just silence so caller can press 1-2

## Root Cause

**File:** `app/services/greeting_service.py`  
**Function:** `_generate_dtmf_prompt_audio()`

The function was generating a 1000Hz beep for 1 second as a **fallback** when:
1. Google Cloud Text-to-Speech (TTS) is not configured
2. `GOOGLE_APPLICATION_CREDENTIALS` is empty in `.env`
3. TTS client initialization fails

Since TTS was not configured, the fallback generated a beep, which was then sent to the caller via RTP.

## Solution

✅ **FIXED:** Changed `_generate_dtmf_prompt_audio()` to return **silence instead of beep**

### Changes Made

**File:** `app/services/greeting_service.py`

```python
# BEFORE (Generated 1-second beep)
except Exception as e:
    log.debug(f"[Greeting] TTS unavailable, using fallback beep sequence: {e}")
    
    # Generated 1000Hz sine wave for 1 second
    # This created the unnecessary beep heard by caller

# AFTER (Returns silence)
except Exception as e:
    log.debug(f"[Greeting] TTS not available ({type(e).__name__}), returning silence for DTMF prompt")
    
    # Returns 500ms of mu-law silence (0xFF bytes)
    # This signals readiness without any beep
    # Caller can immediately press 1 or 2
    silence_duration_ms = 500
    sample_rate = 8000
    silence_samples = silence_duration_ms * sample_rate // 1000
    return b'\xff' * silence_samples  # mu-law silence
```

### Additional Improvements

1. **Added `import os`** to check if credentials file exists
2. **Better fallback logic:**
   - Check if `GOOGLE_APPLICATION_CREDENTIALS` is configured
   - If not configured, skip TTS attempt and return silence immediately
   - If configured but fails, still return silence (not beep)

## Testing the Fix

### Expected Behavior After Fix

```
1. Caller dials
2. System answers
3. Caller hears: "Press 1 for English, 2 for Hindi" (or just silence)
4. NO unnecessary beep
5. Caller presses 1 or 2
6. Greeting plays from Gemini
7. Conversation starts
```

### How to Verify

1. Place a test call
2. Listen carefully for audio sequence:
   - ✅ **Should hear:** Silence or "Press 1/2" message immediately
   - ❌ **Should NOT hear:** 1-2 second beep before message
3. Press 1 for English or 2 for Hindi
4. Greeting should play immediately (from Gemini)

### Logs to Check

Look for these logs (should NOT see beep generation):

```
[Greeting] 📢 Playing language selection prompt via RTP
[Greeting] ✅ Prompt audio generated: X bytes
[Greeting] ✅ Prompt audio queued to RTP TX: X bytes
[ARI] ✅ Language selection prompt sent via RTP
[ARI] ✅ CALL ORCHESTRATION COMPLETE
```

Should NOT see (old fallback):
```
[Greeting] TTS unavailable, using fallback beep sequence
```

Should see (new fallback):
```
[Greeting] TTS not available, returning silence for DTMF prompt
```

## Configuration Option: Enable Real TTS (Optional)

If you want to use Google Cloud Text-to-Speech for the actual "Press 1/2" message:

1. Set up Google Cloud credentials:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
   ```

2. Update `.env`:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-credentials.json
   ```

3. Restart the application

Then `_generate_dtmf_prompt_audio()` will generate the actual TTS audio instead of silence.

## Files Modified

- `app/services/greeting_service.py`
  - Added `import os`
  - Updated `_generate_dtmf_prompt_audio()` function
  - Now returns silence instead of beep when TTS unavailable

## Impact

✅ **No breaking changes**  
✅ **Cleaner call experience** - No unnecessary beep  
✅ **Faster DTMF response** - Caller can press 1/2 immediately  
✅ **Better for accessibility** - No startling beep sound  

## Related Issue in Logs

The logs showed:
```
11:31:00.511 [INFO] [ARI] ✅ Language selection prompt sent via RTP
11:31:00.511 [INFO] [ARI]    └─ Caller now hears the language selection menu
```

But caller was hearing a beep instead of a prompt message. This was because:
1. `play_language_selection_prompt_via_rtp()` was called
2. `_generate_dtmf_prompt_audio()` returned beep (fallback)
3. Beep was sent via RTP to caller
4. Caller heard beep instead of "Press 1/2" message

Now:
1. `play_language_selection_prompt_via_rtp()` is called
2. `_generate_dtmf_prompt_audio()` returns silence
3. Silence is sent via RTP to caller (imperceptible)
4. Caller is ready to press 1 or 2
5. Greeting from Gemini plays next

## Verification Checklist

- [x] Code change made
- [x] Import added
- [x] Fallback logic updated
- [ ] Test with actual call
- [ ] Verify no beep heard
- [ ] Verify DTMF 1/2 works
- [ ] Verify greeting plays after language selection
- [ ] Check logs for silence message

## Next Steps

1. Deploy the fix
2. Test with actual phone call
3. Verify caller immediately hears language menu or is ready to press 1/2
4. Confirm no beep before greeting

---

**Status:** ✅ Fixed  
**Date:** November 26, 2026  
**Impact:** Improves call experience by removing unnecessary beep
