<div dir="rtl" align="right">

# ADR-005: حوكمة FinOps لميزانيات التوكن وقاطع تكلفة السقف اليومي والتوجيه الحتمي للمراحل

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.7
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/finops.py`
    - `src/ai_core/gateway.py`
    - `src/config.py`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `finops_enabled`
    - `finops_call_token_budget`
    - `finops_min_turn_tokens`
    - `finops_daily_spend_cap_usd`
    - `finops_daily_alert_ratio`
    - `finops_max_tracked_sessions`
    - `finops_max_tool_list_items`
    - `finops_max_tool_field_chars`
    - `finops_max_tool_payload_chars`
    - `llm_cost_per_1m_tokens`
    - `voice_max_tokens`
    - `stage_max_tokens`
    - `llm_stage_model`
    - `groq_model`

---

## السياق (Context)
تتراكم تكلفة النماذج اللغوية بسرعة في الأنظمة الصوتية لثلاثة أسباب:
1. التوكنات المخرجة (`Completion Tokens`) أغلى ثمناً وأبطأ نطقاً في TTS.
2. إلحاق مخرجات الأدوات الخام (مثل قوائم الأطباء والمواعيد الطويلة) بتاريخ المحادثة يؤدي إلى تضخم عدد توكنات المدخلات في كل دورة تالية.
3. أي حلقة غير منضبطة أو هجوم استنزاف (Denial of Wallet) عبر مكالمات متكررة قد يرفع الفاتورة السحابية اليومية بشكل مفاجئ.

---

## القرار (Decision)
اعتمدنا منظومة حوكمة **FinOps (`FinOpsController`)** في `src/ai_core/finops.py` مدمجة مباشرة في `ModelGateway`:

1. **التوجيه الحتمي للنماذج حسب المرحلة (بدون استدعاء LLM لاختيار LLM)**:
   - ربط حتمي في الكود: مرحلتا `Stage.CLASSIFICATION` و`Stage.EXTRACTION` تستخدمان دائماً النموذج الخفيف `llm_stage_model = "llama-3.1-8b-instant"` (`$0.05 / $0.08` لكل مليون توكن) بسقف `stage_max_tokens = 256`، بينما مرحلة الحوار `Stage.DIALOGUE` تستخدم `groq_model = "llama-3.3-70b-versatile"` بسقف صارم `voice_max_tokens = 150`.
2. **ميزانية التوكن لكل مكالمة (`finops_call_token_budget = 8000`)**:
   - يتتبع `_SessionLedger` استهلاك التوكنات التراكمي لكل جلسة مكالمة (حتى `finops_max_tracked_sessions = 2000` جلسة نشطة).
   - يتم تقليص سقف توكنات الدورة تلقائياً (`clamped_max_tokens`) ليتناسب مع المتبقي من ميزانية المكالمة، وعند انخفاض المتبقي عن `finops_min_turn_tokens = 16` توكن، تُرفض استدعاءات LLM الإضافية (`FinOpsGateStatus.CALL_BUDGET_EXCEEDED`).
3. **قاطع الدائرة المالي اليومي (`finops_daily_spend_cap_usd = 10.0`)**:
   - يحسب `_DailyBucket` الإنفاق اليومي بالدولار وفق جدول الأسعار `llm_cost_per_1m_tokens`.
   - عند الوصول إلى نسبة التنبيه المبكر `finops_daily_alert_ratio = 0.80` (`$8.00`)، يطلق النظام تنبيهاً مالياً (`AlertLevel.WARNING`).
   - عند بلوغ السقف اليومي `$10.00` (`FinOpsGateStatus.DAILY_CAP_EXCEEDED`)، يفتح قاطع التكلفة ويحوّل النظام تلقائياً إلى **المستوى الثالث (`TIER_3_SEARCH_ONLY`)** أو **المستوى الرابع (`TIER_4_HUMAN_ESCALATION`)** دون إسقاط المكالمة.
4. **تقليم مخرجات الأدوات (`prune_tool_payload`)**:
   - تقليم مخرجات الأدوات قبل إضافتها لسياق المحادثة: بحد أقصى `finops_max_tool_list_items = 5` عناصر للقوائم، و`finops_max_tool_field_chars = 300` حرف للحقل الواحد، و`finops_max_tool_payload_chars = 1200` حرف للحمولة الكلية.

---

## البدائل المرفوضة (Alternatives Rejected)
1. **استخدام نموذج التوجيه اللغوي (LLM Router) لاختيار النموذج المناسب في كل دورة**:
   - *سبب الرفض*: استدعاء نموذج لغوي فقط ليقرر أي نموذج لغوي نستدعي يضيف زمن استجابة (`100ms–250ms`) وتكلفة إضافية في كل دورة، بينما مراحل سير العمل في العيادة معروفة مسبقاً بشكل حتمي في الكود.
2. **استخدام النموذج الكبير (`llama-3.3-70b-versatile`) لجميع المراحل بما فيها التصنيف واستخراج الكيانات**:
   - *سبب الرفض*: تكلفة التوكن في 70B أعلى بنحو 10 أضعاف من 8B، بينما مهام استخراج JSON المقيّد لا تحتاج قدرات الصياغة الحوارية للنموذج الكبير.
3. **قطع المكالمة أو إرجاع خطأ صامت عند انتهاء الميزانية اليومية (Hard Drop on Budget Breach)**:
   - *سبب الرفض*: غير مقبول طبياً وتجارياً؛ التدهور الآمن إلى البحث في قاعدة المعرفة أو موظف الاستقبال يحمي المريض ويحفظ سمعة العيادة.

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- سقف إنفاق يومي مضمون رياضياً لا يمكن تجاوزه حتى في حال حدوث هجوم أو خطأ برمجي.
- خفض استهلاك التوكنات التراكمي في المكالمات متعددة الأدوات بفضل `prune_tool_payload`.

### السلبيات والمقايضات (Negative / Trade-offs)
- إذا استُنفد السقف اليومي (`$10.00`) خلال ساعات الذروة، سيتحول النظام إلى الردود المستخرجة من قاعدة المعرفة أو التحويل للاستقبال حتى منتصف الليل (`UTC`) أو حتى يرفع المشرف قيمة `finops_daily_spend_cap_usd` في الإعدادات.

</div>
