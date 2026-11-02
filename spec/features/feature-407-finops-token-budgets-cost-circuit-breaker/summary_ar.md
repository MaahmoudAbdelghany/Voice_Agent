<div dir="rtl" align="right">

# ملخص مواصفات الميزة 4.7: ميزانيات التوكنز وقاطع التكلفة الذكي (FinOps Token Budgets & Cost Circuit Breaker)

تم إعداد ملفات المواصفات الثلاثة الخاصة بـ **Feature 4.7** بناءً على إجاباتك وقرارات التصميم المتفق عليها:
- خطة التنفيذ: [`plan.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-407-finops-token-budgets-cost-circuit-breaker/plan.md)
- المتطلبات الوظيفية وغير الوظيفية: [`requirements.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-407-finops-token-budgets-cost-circuit-breaker/requirements.md)
- معايير التحقق والاختبار (7 مستويات): [`validation.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-407-finops-token-budgets-cost-circuit-breaker/validation.md)

---

## 1. ملخص خطة التنفيذ (`plan.md`)

### الهدف ولماذا (Objective & Why)
بناء محرك **FinOps** حتمي فائق السرعة (`< 0.5ms`) داخل `src/ai_core/finops.py` ومربوط تلقائياً مع بوابة النماذج `ModelGateway` (`src/ai_core/gateway.py`) وإعدادات النظام (`src/config.py`) لتحقيق ثلاث ركائز أساسية:
1. **ميزانية التوكنز لكل مكالمة (`8,000` توكن/مكالمة)**: منع الحلقات اللانهائية وتضخم استهلاك المكالمة الواحدة، مع تقليم `max_tokens` في الجولة الأخيرة إذا اقتربت المكالمة من السقف، وتحويل المتصل بلطف لموظف الاستقبال (**Tier 4**) عند استنفاد الميزانية.
2. **عداد الإنفاق اليومي بتوقيت القاهرة وقاطع التكلفة (`\$10.00`/يوم مع تنبيه `80%`)**: حماية ميزانية العيادة السحابية من الارتفاعات المفاجئة عبر إطلاق تنبيه مبكر عند `\$8.00` مرة واحدة يومياً، وتفعيل قاطع التكلفة عند `\$10.00` للتحويل التلقائي إلى البحث المعرفي المجاني (**Tier 3**) أو موظف الاستقبال (**Tier 4**) دون إسقاط أي مكالمة، مع التصفير التلقائي عند منتصف الليل بتوقيت القاهرة (`Africa/Cairo`).
3. **تقليم مخرجات الأدوات (`prune_tool_payload`)**: تصفية مخرجات أدوات العيادة الـ 5 للاحتفاظ بالحقول الجوهرية فقط قبل إضافتها لسجل المحادثة، مما يوفر 50–70% من توكنز السياق في المكالمات متعددة الجولات.

### القرارات المعمارية الرئيسية (Key Decisions)
- **D1 — ربط تلقائي داخل `ModelGateway`**: فحص الميزانية قبل الاتصال بـ Groq أو Gemini، وتسجيل التوكنز والتكلفة فور انتهاء التدفق (بما في ذلك حالات الانقطاع الجزئي بعد توليد توكنز).
- **D2 — استنتاج تلقائي لمعرف الجلسة (`session_id`) من 3 مستويات**: يلتقط المعرف تلقائياً بالترتيب من `finops_session_scope` ثم `trace_scope` ثم `caller_session_scope`.
- **D3 — تصفير يومي تلقائي بتوقيت القاهرة (`Africa/Cairo`) وتنبيهات غير متكررة (Idempotent Alerts)**: ربط الإنفاق بتاريخ اليوم (`YYYY-MM-DD`) مع سجل LRU محدود في الذاكرة (`2,000` جلسة).
- **D4 — تقليم ذكي مبني على قوائم السماح لكل أداة (Schema-Aware Allowlist)**: الحفاظ على `booking_code` و`queue_number` و`fee_egp` و`message` مع تحديد سقف القوائم بـ `5` عناصر، والحقل النصي بـ `300` حرف، والـ JSON الكلي بـ `1,200` حرف.

---

## 2. ملخص المتطلبات (`requirements.md`)

- **R1 (ميزانية المكالمة 8,000 توكن)**:
  - تتبع `prompt_tokens` و`completion_tokens` و`total_tokens` و`total_cost_usd` لكل `session_id`.
  - تقليم `effective_max_tokens` إلى `min(stage_cap, remaining_call_tokens)` عندما يتبقى بين `16` و`150` توكن.
  - عند الوصول إلى `>= 8,000` توكن (أو المتبقي `< 16`)، يتم إيقاف استدعاء الـ LLM وإرجاع رد صوتي مهذب بالعامية المصرية مع `DegradationTier.TIER_4_HUMAN_ESCALATION` و`escalate=True` و`error_class="call_token_budget_exceeded"`.
- **R2 (العداد اليومي وتنبيه الـ 80%)**:
  - حساب التكلفة بالدولار عبر `estimate_llm_cost_usd()` وتجميعها حسب تاريخ القاهرة.
  - إطلاق تنبيه `WARNING_80_PERCENT` عند `\$8.00` مرة واحدة يومياً مع دعم Callbacks دون حجب المكالمات.
- **R3 (قاطع التكلفة اليومي عند `\$10.00`)**:
  - عند وصول الإنفاق اليومي إلى `\$10.00`، ينطلق تنبيه `CRITICAL_100_PERCENT` ويُفتح قاطع التكلفة (`DAILY_CAP_EXCEEDED`).
  - في مرحلة `Stage.DIALOGUE`: يتم فحص الطوارئ الطبية أولاً (`detect_emergency` -> **Tier 4** ورقم الإسعاف `123`)، وفي الحالات غير الطارئة يتم التحويل إلى **Tier 3 (`TIER_3_SEARCH_ONLY`)** للرد من قاعدة المعرفة خلال `< 400ms` (أو **Tier 4** إذا لم يتوفر مقتطف).
- **R4 (تقليم مخرجات الأدوات)**:
  - توفير `prune_tool_payload()` و`format_pruned_tool_message()` لتصفية `ToolResult` وفق قوائم الحقول الأساسية للأدوات الخمس (`check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist`).

---

## 3. ملخص معايير التحقق (`validation.md`)

تم تصميم التحقق باستخدام القدرات الفعلية للمشروع (`uv`, `pytest`, `ruff`) عبر 7 مستويات:
1. **Tier 1 (اختبارات الوحدة)**: التحقق من تتبع الـ 8,000 توكن وتقليم الجولة الأخيرة، تنبيه الـ 80% وقاطع الـ 100%، التصفير عند منتصف الليل بتوقيت القاهرة، أولويات استنتاج `session_id`، وتقليم مخرجات الأدوات الخمس.
2. **Tier 2 (اختبارات التكامل)**: التحقق من تكامل `ModelGateway` مع `FinOpsController` (تحويل Tier 4 عند انتهاء ميزانية المكالمة، وتحويل Tier 3 عند تجاوز السقف اليومي، وأولوية الطوارئ الطبية Tier 4 حتى أثناء فتح قاطع التكلفة، وتسجيل بيانات FinOps داخل `trace_scope`).
3. **Tier 3 (الحالات الحدية والأخطاء)**: اختبار سقف الذاكرة LRU (`finops_max_tracked_sessions`)، التزامن (`25` مهمة `asyncio.gather` متوازية)، تعطيل `finops_enabled=False`، ورفض مراحل التصنيف/الاستخراج غير الحوارية عند نفاد الميزانية.
4. **Tier 4 (فحص عدم الانحدار Regression)**: تشغيل جميع اختبارات المراحل 1 إلى 4 (`test_tracing.py`, `test_workflow_gates.py`, `test_guardrails.py`, `test_hybrid_rag.py`, `test_cache_ladder.py`, `test_model_gateway.py`, `test_circuit_breaker.py`, واختبارات قاعدة البيانات والأدوات).
5. **Tier 5 (فحص الكود والأنماط)**: `uv run ruff check` و`uv run ruff format --check`.
6. **Tier 6 (التحقق اليدوي/البصري)**: `Not Applicable` مع مبرر تقني (مكون خلفي بدون واجهة مستخدم؛ لوحة التحكم في المرحلة 7).
7. **Tier 7 (فحص الـ CLI المباشر)**: أمر تشغيل مباشر عبر `uv run python -c ...` للتحقق من قاطع الميزانية وتقليم الأدوات.

</div>

