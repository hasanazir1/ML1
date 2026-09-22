# AI Opportunity Agent

Course final project: upload a text-based PDF CV, review matched jobs, and ask a chat assistant about a selected job. The chat can explain matches, suggest CV improvements, and write a tailored cover letter.

[Final project slides](presentation/AI_Opportunity_Agent_Final_Project.pptx)

حلول ذكية لتحليل السيرة الذاتية والبحث عن وظائف مطابقة باستخدام الذكاء الاصطناعي.

## الوصف

تطبيق ويب يقوم بـ:
- **رفع السيرة الذاتية** (PDF) واستخراج المعلومات منها آلياً
- **جلب الوظائف** من Jobs.ps عبر RSS مع بيانات احتياطية (Seed Data)
- **مطابقة ذكية** باستخدام Embeddings + LLM (OpenRouter)
- **متابعة التقدم** في الوقت الحقيقي عبر WebSocket (SocketIO)
- **دردشة تفاعلية** لفهم النتائج وتحسين السيرة وكتابة Cover Letters

## المتطلبات

- Python 3.10+
- مفتاح OpenRouter API مع إمكانية استخدام نموذج الدردشة والـembeddings المختارين

## التثبيت

```powershell
git clone https://github.com/hasanazir1/ML1.git
cd ML1
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

ضع مفتاح OpenRouter الحقيقي وقيمة عشوائية لـ`SECRET_KEY` داخل `.env` قبل التشغيل. الملف مستثنى من Git. على Linux أو macOS استخدم `source venv/bin/activate` و`cp .env.example .env`.

## التشغيل

```bash
python run.py
```

ثم افتح المتصفح على: **http://localhost:5000**

## ملف .env

```env
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
EMBEDDING_MODEL=openai/text-embedding-3-small
JOBS_RSS_URL=https://www.jobs.ps/rss/jobs/gaza-jobs
JOBS_LIMIT=20
SECRET_KEY=مفتاح-سري-عشوائي
FLASK_DEBUG=False
HOST=127.0.0.1
PORT=5000
```

## هيكل المشروع

```
AI Opportunity Agent/
├── flask_app/
│   ├── app.py              # تطبيق Flask + SocketIO الرئيسي
│   ├── database/
│   │   ├── db.py           # عمليات SQLite
│   │   ├── create_tables/  # ملفات SQL لإنشاء الجداول
│   │   └── initial_data/   # بيانات بدائية (CSV)
│   ├── utils/
│   │   ├── pdf_parser.py       # استخراج نص PDF
│   │   ├── jobs_fetcher.py     # جلب الوظائف (RSS + Seed)
│   │   ├── embedding_service.py # توليد Embeddings
│   │   ├── prompts.py          # Master Prompt Template مثل Homework 1
│   │   ├── http_client.py      # HTTP مع إعادة محاولة واحدة للأخطاء المؤقتة
│   │   └── llm_service.py      # استدعاءات LLM
│   ├── agents/
│   │   ├── cv_analyzer.py       # خبير تحليل السير الذاتية
│   │   ├── match_scorer.py      # خبير تقييم المطابقة
│   │   ├── chat_orchestrator.py # منسق المحادثة
│   │   ├── chat_query.py        # خبير الأسئلة
│   │   ├── cv_improvement.py    # خبير تحسين السيرة
│   │   └── cover_letter.py      # مولّد رسائل التقديم
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── tests/                  # اختبارات مستقلة عن OpenRouter والبيانات الحقيقية
├── presentation/           # شرائح المشروع بالإنجليزية
├── requirements.txt
├── .env.example
├── run.py
└── README.md
```

## قاعدة البيانات

SQLite مع 5 جداول:
- `cv_profiles` - السير الذاتية المرفوعة وتحليلها
- `jobs` - الوظائف المتاحة
- `match_results` - نتائج المطابقة بين CV ووظيفة
- `chat_messages` - سجل المحادثة
- `llm_roles` - إعدادات الخبراء (Experts)

## الخبراء (LLM Agents)

1. **CV Analysis Expert** - يستخرج البيانات المنظمة من نص CV
2. **Match Scoring Expert** - يقارن CV مع وظيفة ويصدر تقييم
3. **Chat Orchestrator** - يوجه الرسائل للخبير المناسب
4. **Chat Query Expert** - يجيب على أسئلة المستخدم
5. **CV Improvement Expert** - يقترح تعديلات للسيرة مرتبطة بالوظيفة

6. **Cover Letter Generator Expert** - يكتب رسائل تقديم احترافية

## تدفق تحليل السيرة الذاتية

```text
رفع ملف PDF
	-> استخراج نص السيرة الذاتية
	-> CV Analysis Expert
	-> إنشاء embedding للسيرة الذاتية
	-> جلب الوظائف من RSS ثم اختيار أحدث JOBS_LIMIT وظيفة (افتراضيًا 20)
	-> إنشاء embeddings للوظائف التي لا تملك embedding
	-> Semantic Search: ترتيب الوظائف حسب Cosine Similarity
	-> اختيار أفضل 10 وظائف
	-> Match Scoring Expert لكل وظيفة مختارة
	-> حفظ النتائج وعرضها للمستخدم
```

## تدفق الدردشة

```text
رسالة المستخدم
	-> Chat Orchestrator
	-> JSON decision: agent + job_id + needs_clarification
	-> التحقق من الوكيل المسموح
	-> Chat Query Expert أو CV Improvement Expert أو Cover Letter Generator Expert
	-> عرض الرد وحفظه في chat_messages
```

## Agents and Executors

| Agent | Inputs | Outputs | Executor |
|---|---|---|---|
| CV Analysis Expert | Raw CV text | Structured CV data | `analyze_cv()` |
| Match Scoring Expert | CV data and one job | Match score, strengths, missing skills, recommendation, and comment | `score_match()` |
| Chat Orchestrator | User message, last 6 messages and current jobs | JSON decision with `agent`, `job_id`, `needs_clarification` | `route_message()` |
| Chat Query Expert | User question, profile id, and saved match results | Natural-language answer | `answer_question()` |
| Cover Letter Generator Expert | CV data and selected job | Cover letter text | `generate_cover_letter()` |
| CV Improvement Expert | Parsed CV data and optional selected job match | Suggestions to improve the CV text | `suggest_cv_improvements()` |
| Semantic Search step | CV embedding and up to JOBS_LIMIT recent jobs | Top 10 jobs ranked by cosine similarity | `search_matching_jobs()` |

## ملاحظات

- إذا فشل RSS، تُستخدم الوظائف المخزنة أولًا، ثم `jobs_seed.csv` فقط إذا كانت قاعدة الوظائف فارغة. بيانات Seed للتجربة وقد لا تمثل إعلانات حديثة.
- يتم حساب Cosine Similarity بين embeddings بالإضافة إلى تقييم LLM
- تحليل CV والتقييم والدردشة تحتاج OpenRouter. غياب المفتاح أو تعذر الخدمة ينتج حالة فشل واضحة؛ لا يتم اختلاق نتائج بديلة.

## التعديلات الأساسية وعلاقتها بالواجبات

- **Homework 1:** الأدوار الستة تستخدم `MASTER_TEMPLATE` في `utils/prompts.py`. الدور والتخصص والتعليمات والسياق والأمثلة تأتي من `llm_roles`. تعديل CSV ثم إعادة تشغيل التطبيق يحدّث الأدوار دون حذف CVs أو النتائج.
- **Homework 2:** تُخزَّن embeddings كـJSON في SQLite. يتم فحص الأرقام والأبعاد واسم النموذج قبل المقارنة، وإعادة إنشاء cache غير المتوافق. البحث الدلالي هنا خطوة Python محددة ضمن workflow التحليل، وليس خبيرًا يختاره منسق الشات.
- الـOrchestrator يختار أحد خبراء الدردشة الثلاثة بقرار JSON، والتنفيذ يتم بدوال Python معروفة. أزرار الأسئلة والخطاب وتحسين السيرة تختار الخبير مباشرة عندما يكون الإجراء واضحًا. لا يوجد `eval` أو `exec` لمخرجات النموذج.
- آخر ست رسائل تُرسل إلى المنسق والخبير مع السؤال الحالي، ويُحفظ `job_id` المختار مع الرسائل. لا تُكرر الرسالة الحالية ضمن التاريخ. يُعالَج طلب شات واحد لكل profile في الوقت نفسه.

## حالة التحليل والـAPI

الحالة وآخر حدث progress محفوظان في SQLite. يُعاد إرسال الحدث عند اتصال الصفحة، ويُتاح أيضًا في `GET /api/results/<id>` تحت `analysis` لتعرضه الواجهة الحالية.

```text
pending → cv_analysis → embedding → fetch_jobs → matching → completed
                                                      ↘ partial / failed
```

أسماء أحداث Socket.IO القديمة تبقى متوافقة مع الواجهة: `complete` يُحفظ كـ`completed` و`error` كـ`failed`. عند بدء التشغيل عبر `python run.py`، تتحول المهام المنقطعة إلى `partial` إذا كانت لها نتائج، أو `failed` إذا لم تكن لها نتائج. لا يوجد استئناف تلقائي: يعيد المستخدم رفع الملف. حالة بيانات الإصدار القديم `legacy` لأن عدد النتائج وحده لا يثبت اكتمال التحليل.

الـAPI يعيد حقول العرض فقط، دون raw CV أو device_id أو embedding. حقلا `similarity` و`match_score` موجودان في النتائج؛ الأول تشابه دلالي والثاني تقييم النموذج، ولا يمثل أي منهما احتمال الحصول على الوظيفة. عند `semantic_ranking=degraded` يكون اختيار المرشحين تقريبيًا، وتعرض الواجهة تحذيرًا واضحًا بدل درجة تشابه مضللة.

## الاختبارات

```bash
python -B -m unittest discover -v
```

تستخدم الاختبارات SQLite مؤقتة وطلبات مزود محاكية، وتحظر الشبكة. تغطي الصلاحيات، رفع PDF، تحديث schema والأدوار، حفظ حالة التحليل، انقطاع التشغيل، الفشل الجزئي، المتجهات، JSON contracts، retries وذاكرة الشات. لا تعدّل قاعدة المستخدم أو تستخدم رصيد API. يلزم اختبار يدوي بمفتاح صالح وCV تجريبية للحكم على جودة الإجابات الحقيقية.

## حدود النسخة التعليمية

- التشغيل بعملية واحدة محليًا؛ SQLite وbackground threads كافيان للعرض. لا تشغّل عدة نسخ على قاعدة البيانات نفسها، لأن اكتشاف الانقطاع عند البدء يفترض أن العملية السابقة توقفت.
- ترقية قاعدة قديمة تضيف أعمدة فقط. embeddings القديمة التي ليس لها model تُعاد مرة واحدة عند الحاجة؛ قد يجعل هذا أول تحليل أبطأ.
- يتم حذف PDF المؤقت بعد الاستخراج، لكن النص والنتائج والدردشة تبقى في قاعدة البيانات. النص يُرسل إلى OpenRouter للتحليل؛ استخدم CV تجريبية أثناء العرض.
- PDFs الممسوحة كصور تحتاج OCR غير متوفر في هذه النسخة. تحليل CV يستخدم أول 8000 حرف، ومقتطف الاتصال للرسالة أول 4000 حرف.
- ملفات PDF التاريخية نُقلت إلى `private_archive/legacy_uploads` للاسترجاع المحلي؛ المجلد غير متتبع في Git. لم يُحذف نص السير الذاتية من قاعدة البيانات.
- السيرفر يستخدم Werkzeug للتجربة المحلية. يُسمح بالتشغيل دون terminal تفاعلي على loopback فقط؛ هذا لا يضيف دعم نشر إنتاجي.
- HTTP يعيد المحاولة مرة واحدة عند انقطاع الاتصال أو 429 أو 5xx. لا يعيد المحاولة عند مفتاح خاطئ؛ فشل الـLLM لا يُفسَّر على أنه غموض وظيفة.
- لم تُضف أفعال حذف أو تقديم وظائف آليًا. Human Validation من Homework 2 يصبح مناسبًا إذا أضيفت أفعال تعديل أو إرسال لاحقًا؛ ليس شرطًا جديدًا مفروضًا على هذا المشروع.
- الواجهة عربية RTL باستخدام HTML وCSS وJavaScript فقط، دون إطار إضافي. الشات بجانب النتائج على الكمبيوتر وتحتها على الهاتف.

## الواجهة والشات المرتبط بالوظيفة

زر «ناقش هذه الفرصة» يحدد `job_id` ويعرض اسم الوظيفة في الشات. الأسئلة السريعة ترسل `action=ask` إلى خبير الأسئلة مباشرة؛ زر الخطاب يرسل `action=cover_letter`. الرسائل الحرة ترسل `action=auto` للـOrchestrator، مع تقييد اختياره بالوظيفة المحددة إن وجدت. يتحقق الخادم أن الوظيفة من نتائج صاحب الجلسة. الطلبات القديمة التي ترسل `job_id` فقط تبقى طلبات خطاب تقديم.

زر «حسّن سيرتي لهذه الفرصة» يرسل `action=improve_cv` مع `job_id` المحدد إلى CV Improvement Expert. يمكن أيضًا طلب تحسين السيرة عمومًا برسالة حرة دون تحديد وظيفة. يستخدم الخبير بيانات السيرة المحللة؛ وعند اختيار وظيفة يستخدم وصفها ونتيجة المطابقة أيضًا. يعرض اقتراحات نصية فقط ولا يغيّر قاعدة البيانات أو ملف PDF، ولا يرسل النص الخام أو بيانات الاتصال لهذا الخبير.

يمكن فحص التصميم ببيانات وهمية دون استهلاك API أو لمس قاعدة المشروع:

```bash
python -B -m tests.preview_ui
```

افتح `http://127.0.0.1:5055` لصفحة الرفع أو `http://127.0.0.1:5055/_preview` لنتائج تجريبية. ردود هذه المعاينة محاكية وليست من AI. أوقفها بـCtrl+C. التشغيل الحقيقي يبقى `python run.py`.

## الترخيص

MIT
