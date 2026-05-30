# AI Clinical Assistant Module

## Purpose

The AI Clinical Assistant provides clinicians with AI-powered decision support through natural language conversation. It answers clinical questions, provides evidence-based suggestions, and helps with differential diagnosis reasoning.

Key capabilities:
- **Clinical Q&A**: Ask questions about patient presentation, risk, management
- **Evidence-Based Suggestions**: AI references clinical guidelines and evidence
- **Differential Diagnosis**: Helps reason through diagnostic possibilities
- **Medication Guidance**: Reviews drug interactions, contraindications (works with Task 12)
- **Risk Interpretation**: Explains risk scores in clinical context
- **Multi-Turn Conversation**: Maintains conversation history for context

This is the **API layer** (Task 11). The actual LLM models are from cloud providers (OpenAI GPT-4o, Anthropic Claude, or local Ollama).

## Key Concepts

### Conversation
A chat session between a clinician and the AI for a specific patient. May span multiple messages over time.

Fields:
- **clinician_id**: Which doctor initiated the conversation
- **patient_id**: Patient being discussed
- **message_count**: Total messages (clinician + AI)
- **is_active**: true if ongoing, false if archived
- **last_message_at**: For "recent conversations first" UI sorting

### Message
Individual message in a conversation.

Fields:
- **role**: "user" (clinician's question) or "assistant" (AI response)
- **content**: Message text (PHI: clinical discussion)
- **model_used**: Which LLM generated response (e.g., "gpt-4o", "claude", "ollama")
- **tokens_used**: Token count (for cost tracking)

### LLM Providers
Pluggable interface supporting multiple LLM backends with automatic failover:

- **GPT-4o** (OpenAI): Most capable, cloud-based
- **Claude** (Anthropic): Strong reasoning, cloud-based
- **Ollama** (local): Open-source models, runs on-premises
- **Failover Chain**: Tries GPT-4o → Claude → Ollama automatically

## Dependencies

### Other Modules
- **Risk Engine** (Task 9): Context for risk score interpretation
- **Measurements** (Task 7): Patient measurement data
- **Patients** (Task 5): Patient profile
- **Drug Interactions** (Task 12): Medication safety context
- **Audit** (core): Audit logging for compliance
- **Events** (core): Future: events for escalation scenarios

### External Services
- **OpenAI API**: GPT-4o provider (requires API key)
- **Anthropic API**: Claude provider (requires API key)
- **Ollama**: Local LLM service (localhost:11434 by default)
- **PostgreSQL**: Data persistence (Conversation, Message tables)

## API Surface

### Public Functions (AIAssistantService)

```python
# Send clinical message and get AI response
result: dict = await ai_service.send_message(patient_id, clinician_id, message_text, conversation_id=None)

# Get conversation history
messages: list[dict] = await ai_service.get_history(patient_id, conversation_id=None, limit=50)
```

### API Endpoints

**POST** `/api/v1/patients/{id}/assistant/chat` (200 OK)
- Send clinical message to AI
- Request: `{message: "...", conversation_id: "..." (optional)}`
- Response: `{success: true, data: {conversation_id, message_id, response, tokens_used, model_used}, meta: {...}}`
- Requires: Doctor role
- HIPAA: Response marked `Cache-Control: no-store`
- Advisory: Response includes "⚠️ AI-generated — verify independently"

**GET** `/api/v1/patients/{id}/assistant/history?conversation_id=...&limit=50` (200 OK)
- Fetch conversation history
- Response: `{success: true, data: [messages], meta: {...}}`
- Requires: Doctor role
- HIPAA: Response marked `Cache-Control: no-store`

## How to Test

### Unit Tests
```bash
pytest backend/tests/unit/ai_assistant/ -v
```

### Integration Tests
```bash
pytest backend/tests/integration/test_ai_assistant_flow.py -v
```

### Manual Test (with real DB)

1. Start Ollama (local fallback):
   ```bash
   ollama serve  # Listens on localhost:11434
   ollama pull mistral  # Download model
   ```

2. Create patient (see Patients module)

3. Send message:
   ```bash
   curl -X POST http://localhost:8000/api/v1/patients/<id>/assistant/chat \
     -H "Authorization: Bearer <jwt>" \
     -H "Content-Type: application/json" \
     -d '{"message": "What interventions would help reduce this patients hypertension?"}'
   
   # Returns:
   # {
   #   "success": true,
   #   "data": {
   #     "conversation_id": "...",
   #     "message_id": "...",
   #     "response": "Based on the patient profile... [AI response]...\n\n⚠️ AI-generated — verify independently",
   #     "tokens_used": 245,
   #     "model_used": "ollama"
   #   },
   #   "meta": {...}
   # }
   ```

4. Get history:
   ```bash
   curl http://localhost:8000/api/v1/patients/<id>/assistant/history \
     -H "Authorization: Bearer <jwt>"
   
   # Returns list of messages [user, assistant, user, assistant, ...]
   ```

## HIPAA Compliance

### PHI Fields
- `messages.content`: Clinical discussions (PHI)
- `conversations.patient_id, clinician_id`: Identifiers (PHI)

### Protections
- **Storage**: Encrypted at rest (column-level or TDE)
- **Transit**: TLS 1.2+ (enforced by FastAPI middleware)
- **Cloud LLM Calls**: Patient data de-identified before sending
  - No patient name (use ID only)
  - No MRN or full dates (use age ranges)
  - Clinical data (measurements, risks) OK (no direct identifiers)
- **Local Ollama**: Full clinical data (stays on-premises)
- **Caching**: No-store headers on all responses with PHI
- **Logging**: Never log message content (only patient_id UUID)
- **Audit Trail**: Every conversation and data access logged
- **Advisory**: Every response includes "⚠️ AI-generated — verify independently"
- **Immutable Records**: Conversations are append-only (audit trail)
- **Retention**: 7-year minimum per HIPAA (preserved in encrypted DB)

### De-Identification Before Cloud LLMs
```python
# BEFORE sending to GPT-4o / Claude:
patient_data = {
    "patient_id": "abc-123",  # OK: UUID, not name
    "age_range": "50-60",      # OK: Range, not birth date
    "sex": "M",
    "conditions": ["HTN", "DM2"],
    "bp": 160,
    "medications": ["lisinopril"],
}

# NEVER send:
# - Patient name
# - MRN
# - Exact birth date
# - Home address
# - Insurance ID
```

## Architecture Decisions

### Why Multiple LLM Providers?
- **Resilience**: If OpenAI is down, Claude is available. If Claude fails, Ollama (local) always works
- **Cost**: Use cheaper local Ollama for simple questions, reserve OpenAI for complex cases
- **Compliance**: Ollama stays on-premises (no cloud data exfil)
- **Flexibility**: Users can choose which provider (settings in Task 17)

### Why Automatic Failover?
Clinicians can't wait for API calls to fail — they need responses. Failover ensures:
- User tries GPT-4o (best quality)
- If timeout/error, silently try Claude
- If Claude fails, use local Ollama (always available)
- User gets response within 30 seconds

### Why Advisory Label?
- AI is not a doctor
- Decisions must be clinician-verified
- Liability protection (clear disclaimer on every response)
- Regulatory compliance (FDA guidance on AI decision support)

### Why De-Identification for Cloud LLMs?
- OpenAI/Anthropic may log API calls for training
- Sending named patients could violate HIPAA
- De-identification enables cloud LLM use without privacy risk
- Local Ollama doesn't require de-identification (stays on-premises)

## Forward Compatibility

### Task 12 (Drug Interactions) Needs
- Conversation context available for interaction checking
- Can reference medications discussed in conversation

### Task 14 (Alerts) Needs
- AI suggestions can trigger alerts (e.g., "recommend BP medication" → alert to review)

### Task 17 (Admin) Needs
- LLM provider selection UI
- Token usage analytics
- Cost per conversation
- Model A/B testing

### Task 20+ (ML Pipeline) Needs
- Fine-tuned clinical models (replaces generic GPT-4o)
- Domain-specific safety filters
- Evidence sourcing (cite guidelines)

## Performance

### Latency
- **LLM response time**: 3–15 seconds typical
- **Failover delay**: 5 seconds per provider timeout
- **Database operations**: <50ms
- **Total end-to-end**: <30 seconds (user-facing)

### Token Usage & Cost
- **Average response**: 150–300 tokens
- **GPT-4o**: ~$0.015 per 1K tokens
- **Claude**: ~$0.003 per 1K tokens
- **Ollama**: Free (local)
- **Cost per response**: $0.002–$0.005 (GPT-4o), negligible for Ollama

### Throughput
- Platform target: 500 concurrent tenants
- At peak: ~2–3 conversations/hour per tenant (reasonable for 5–10 clinicians)
- Conversations stored in DB (persistent, searchable)

## Monitoring & Debugging

### Database Queries
```sql
-- Recent conversations
SELECT patient_id, clinician_id, message_count, last_message_at, is_active
FROM conversations
ORDER BY last_message_at DESC
LIMIT 20;

-- Messages for one conversation
SELECT role, content, model_used, tokens_used, created_at
FROM messages
WHERE conversation_id = '...'
ORDER BY created_at;

-- Token usage summary
SELECT model_used, COUNT(*) as response_count, SUM(tokens_used) as total_tokens
FROM messages
WHERE role = 'assistant' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY model_used
ORDER BY total_tokens DESC;
```

### Audit Logs
```sql
-- AI assistant interactions
SELECT timestamp, action, user_id, resource_id, changes
FROM audit_logs
WHERE action IN ('clinical_message_sent', 'history_accessed')
ORDER BY timestamp DESC
LIMIT 50;
```

### LLM Provider Fallback
```bash
# Watch which provider is being used
docker logs prescphealth_api | grep "trying_provider\|provider_succeeded\|provider_failed"

# Manually test Ollama
curl http://localhost:11434/api/chat -d '{"model": "mistral", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Known Limitations (Task 11)

1. **LLM Quality**: Using generic GPT-4o/Claude, not fine-tuned for clinical tasks (Task 20+ will fix)
2. **Context Window**: Only last 20 messages in conversation (could be expanded)
3. **No Evidence Citation**: AI responses don't cite sources (Task 20+ will add)
4. **No Safety Filters**: Responses not checked against clinical guidelines (Task 20+ will add)
5. **No Offline Mode**: Cloud LLMs required (Ollama fallback helps, but not in all scenarios)
6. **Token Cost**: No quota limits or cost caps (Task 17+ will add)

## Related Tasks

- **Task 9** (Risk Engine): Provides risk context
- **Task 7** (Measurements): Provides patient data context
- **Task 12** (Drug Interactions): Drug safety context for conversations
- **Task 14** (Alerts): Can trigger alerts based on AI suggestions
- **Task 17** (Admin): LLM provider selection, token analytics
- **Task 20+** (ML Pipeline): Fine-tuned clinical models, evidence citation
- **Task 23** (Security): RLS policy tests, audit compliance
- **Task 33** (Integration): Wires router into main FastAPI app
