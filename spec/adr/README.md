<div dir="rtl" align="right">

# فهرس سجلات القرارات المعمارية (Architecture Decision Records — ADRs)

يوثّق هذا الدليل القرارات المعمارية الجوهرية لنظام **المساعد الصوتي الذكي للعيادات والمراكز الطبية المصرية (Voice AI Medical Receptionist)**، لا سيما قرارات المرحلة الرابعة (**Phase 4: Enterprise AI Architecture & Resilience**).

- للاطلاع على المخططات المعمارية الشاملة للنظام (بمستوى C4)، راجع [`spec/architecture.md`](../architecture.md).
- لإضافة قرار معماري جديد، انسخ القالب القياسي من [`template.md`](./template.md) وأضف سطراً جديداً في الجدول أدناه.

---

## جدول القرارات المعتمدة

| الرقم | عنوان القرار المعماري | الحالة (Status) | الميزة المرتبطة (Feature) |
|:---|:---|:---|:---|
| **001** | [الاسترجاع الهجين (Dense Qdrant + BM25) عبر دمج الترتيب التبادلي (RRF) والتقسيم الواعي بالبنية](./001-hybrid-search-rrf.md) | `Accepted` | Feature 4.3 |
| **002** | [بوابات التحقق البرمجية الحتمية ومفاتيح عدم التكرار (Idempotency Keys) بدل قواعد البرومبت](./002-deterministic-gates-vs-prompt-rules.md) | `Accepted` | Feature 4.5 |
| **003** | [بوابة النماذج متعددة المستويات (Groq + Gemini Fallback) وقاطع الدائرة و4 درجات تدهور](./003-multi-tier-model-gateway.md) | `Accepted` | Feature 4.1 |
| **004** | [التتبع الهرمي المستضاف ذاتياً عبر Langfuse وOpenTelemetry لحماية سيادة بيانات المرضى](./004-self-hosted-langfuse-tracing.md) | `Accepted` | Feature 4.6 |
| **005** | [حوكمة FinOps لميزانيات التوكن وقاطع تكلفة السقف اليومي والتوجيه الحتمي للمراحل](./005-finops-budgets-and-stage-routing.md) | `Accepted` | Feature 4.7 |
| **006** | [مجموعة التقييم الذهبية وبوابة RAGAS في CI مع حَكَم من عائلة نماذج مختلفة](./006-ragas-ci-evaluation.md) | `Accepted` | Feature 4.8 |
| **007** | [طبقة الثقة المتوافقة مع OWASP وحواجز الحماية الفورية وتنقية PII والمصنّف غير المتزامن](./007-owasp-trust-layer.md) | `Accepted` | Feature 4.4 |
| **008** | [سلّم التخزين المؤقت ثلاثي المستويات مع عزل الفئات وعتبة التشابه الدلالي `0.97`](./008-three-tier-cache-ladder.md) | `Accepted` | Feature 4.2 |
| **009** | [آلة الحالة المحدودة الحتمية (FSM) لسير عمل الحجز بدل حلقات الوكيل المفتوحة](./009-state-machine-over-agent-loop.md) | `Accepted` | Feature 4.5 |

</div>
