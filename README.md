# 🤖 AI Opportunity Agent

حلول ذكية لتحليل السيرة الذاتية والبحث عن وظائف مطابقة باستخدام الذكاء الاصطناعي.

## الوصف

تطبيق ويب يقوم بـ:
- **رفع السيرة الذاتية** (PDF) واستخراج المعلومات منها آلياً
- **جلب الوظائف** من Jobs.ps عبر RSS مع بيانات احتياطية (Seed Data)
- **مطابقة ذكية** باستخدام Embeddings + LLM (OpenRouter)
- **متابعة التقدم** في الوقت الحقيقي عبر WebSocket (SocketIO)
- **دردشة تفاعلية** مع Match Agent لطرح الأسئلة وكتابة Cover Letters

## المتطلبات

- Python 3.10+
- مفتاح OpenRouter API (مجاني)

## التثبيت

```bash
# استنساخ المشروع
git clone <repo-url>
cd AI Opportunity Agent

# إنشاء بيئة افتراضية (اختياري)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# تثبيت المتطلبات
pip install -r requirements.txt

# إنشاء ملف .env
copy .env.example .env
# ثم عدّل .env وأضف مفتاح OpenRouter
```

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
JOBS_RSS_URL=https://jobs.ps/rss
SECRET_KEY=مفتاح-سري-عشوائي
FLASK_DEBUG=True
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
│   │   └── llm_service.py      # استدعاءات LLM
│   ├── agents/
│   │   ├── cv_analyzer.py       # خبير تحليل السير الذاتية
│   │   ├── match_scorer.py      # خبير تقييم المطابقة
│   │   ├── chat_orchestrator.py # منسق المحادثة
│   │   ├── chat_query.py        # خبير الأسئلة
│   │   └── cover_letter.py      # مولّد رسائل التقديم
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── uploads/                # ملفات PDF المرفوعة (مؤقتة)
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
5. **Cover Letter Generator** - يكتب رسائل تقديم احترافية

## تدفق تحليل السيرة الذاتية

```text
رفع ملف PDF
	-> استخراج نص السيرة الذاتية
	-> CV Analysis Expert
	-> إنشاء embedding للسيرة الذاتية
	-> جلب الوظائف من RSS أو البيانات الاحتياطية
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
	-> JSON decision: agent + reason
	-> التحقق من الوكيل المسموح
	-> Chat Query Expert أو Cover Letter Generator Expert
	-> عرض الرد وحفظه في chat_messages
```

## Agents and Executors

| Agent | Inputs | Outputs | Executor |
|---|---|---|---|
| CV Analysis Expert | Raw CV text | Structured CV data | `analyze_cv()` |
| Match Scoring Expert | CV data and one job | Match score, strengths, missing skills, recommendation, and comment | `score_match()` |
| Chat Orchestrator | User message and current jobs | JSON decision with `agent` and `reason` | `route_message()` |
| Chat Query Expert | User question, profile id, and saved match results | Natural-language answer | `answer_question()` |
| Cover Letter Generator Expert | CV data and selected job | Cover letter text | `generate_cover_letter()` |
| Semantic Search step | CV embedding and all job embeddings | Top 10 jobs ranked by cosine similarity | `search_matching_jobs()` |

## ملاحظات

- إذا فشل جلب الوظائف من RSS (مثل حماية Cloudflare)، يتم تلقائياً استخدام البيانات الاحتياطية من `jobs_seed.csv`
- يتم حساب Cosine Similarity بين embeddings بالإضافة إلى تقييم LLM
- التطبيق يعمل بالكامل بدون OpenRouter (مع نتائج محدودة) لكن يُفضل إضافته للتحليل الكامل

## الترخيص

MIT
