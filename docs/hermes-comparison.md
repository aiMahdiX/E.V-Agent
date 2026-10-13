# بررسی E.V. و مقایسه با Hermes Agent

> تاریخ بررسی: ۲۰۲۶-۰۹-۲۹ · شاخه: `main` · حدود ۱۰٬۳۰۰ خط پایتون در ۸۱ ماژول
> مبنای Hermes: مستندات رسمی Nous Research (`hermes-agent.nousresearch.com/docs`)

---

## ۱. خلاصهٔ اجرایی

**E.V. یک پروژهٔ جدی و منسجم است، ولی در وضعیت فعلی بالا نمی‌آید.** دو باگ ساده در
`main.py` مسیر راه‌اندازی را می‌شکنند (بخش ۲.۴). جز آن، معماری تمیز، تفکیک لایه‌های
درست، و ۹ اسکریپت آزمون آفلاین دارد که همه پاس می‌شوند (~۱۰٬۳۰۰ خط کد، بدون آزمون
واحد رسمی).

از نظر رابطه با Hermes: **E.V. رقیب Hermes نیست، یک پیاده‌سازی کوچک و آفلاین از
همان ایده در مقیاس یک لپ‌تاپ است.** خودِ README می‌گوید حلقهٔ خودبهسازی
«patterned after Hermes Agent's skill system, but sized for a 4 GB laptop» —
و این توصیف دقیقی است. E.V. ایدهٔ *learning loop* را برداشته و آن را به یک
`skills.json` و یک `SkillEngine` ۲۵۰ خطی تقلیل داده، در حالی که Hermes روی همان
ایده یک استاندارد باز (`agentskills.io`)، یک مخزن مهارت (Skills Hub)، سیستم
اسکن امنیتی و ۲۵٬۰۰۰ تست بنا کرده است.

نقطهٔ قوت اصلی E.V. جای دیگری است: **آفلاین بودن واقعی، فارسی‌بودن، و بهینه‌سازی
برای ۴ گیگابایت VRAM.** این‌ها چیزهایی هستند که Hermes اصلاً هدفش نیست.

---

## ۲. بررسی پروژهٔ E.V.

### ۲.۱ نمای کلی

```
main.py  ─┬─ models/llm.py         ProviderClient (Ollama + OpenAI-compatible)
          ├─ core/agent.py         ReAct loop  + turbo + نجات از خروجی خراب
          ├─ core/router.py        ModelRouter (auto/fixed، انتخاب بر اساس اندازه)
          ├─ core/context.py       ContextBuilder (persona + state + memory + skills)
          ├─ core/tool_router.py   ToolOrchestrator (native ⟷ MCP)
          ├─ memory/               short_term / long_term(SQLite+FTS5) / episodic
          │                        / semantic / embeddings
          ├─ skills/               SkillStore + SkillEngine  (فاز ۷)
          ├─ security/             policy(L0..L4) + permissions + approval + sandbox
          ├─ tools/                shell, filesystem, process, services, gpu,
          │                        network, audio, screen, gui, browser, camera,
          │                        vision, integrations  + mcp/{client,registry,discovery}
          ├─ mcp_servers/          browser, echo_demo, game, home, messaging, vision
          ├─ tasks/ sensors/       scheduler + event bus + system/GPU monitor
          ├─ voice/                VAD + Vosk STT + Piper TTS + wake word
          └─ ui/                   cli/repl.py + web/(aiohttp HUD) + overlay(خالی)
```

### ۲.۲ کیفیت لایه‌ها

| لایه | ارزیابی | توضیح |
|---|---|---|
| `core/agent.py` | **خوب** | ReAct کامل با سه نکتهٔ بالغ: (۱) fallback برای مدل‌هایی که `tool_call` را به‌صورت متن می‌نویسند، (۲) گاردِ `_is_junk` برای خروجی خالی/`}`، (۳) `_pending_task` برای «ادامه بده». این‌ها نشانهٔ کار با مدل‌های کوچک واقعی است. |
| `core/tool_router.py` + `capability_manager.py` | **خوب** | تفکیک «چه کاری می‌توانم» از «چطور اجرا کنم». MCP با `needs_approval` سختگیرانه‌تر از native. |
| `security/` | **خوب با یک حفرهٔ بزرگ** | طبقه‌بندی L0..L4 + دستور ناشناخته → L3 (محافظه‌کارانه و درست) + لاگ JSONL. اما `sandbox.py` صرفاً یک `NotImplementedError` است؛ هیچ جداسازی فرایندی/کانتینری وجود ندارد، در حالی که مدل فرمان شل را به‌طور پیش‌فرض تا L3 تأییدشده اجرا می‌کند. |
| `memory/` | **خوب** | SQLite + FTS5 با trigger، embedding ترکیبی (hash n-gram + `nomic-embed-text`) با fallback خودکار. طراحی «هرگز crash نکن» درست پیاده شده. |
| `skills/` | **قابل قبول، ساده‌شده** | نگاه بخش ۴. |
| `models/llm.py` | **خوب** | لایهٔ استاندارد-کتابخانه‌ای، `warm()`، `keep_alive`، retry روی `fallback` فقط وقتی مدل cloud شکست بخورد. |
| `ui/web/` | **خوب** | aiohttp + SSE، کار سنگین در worker thread. |
| `core/reflection.py`, `core/reasoning.py`, `ui/overlay/` | **مرده** | نوشته شده‌اند ولی هیچ‌جا import نمی‌شوند. |

### ۲.۳ وضعیت آزمون‌ها

آزمون‌ها اسکریپت‌های دستی در ریشه‌اند (`_smoke*.py`)، نه `tests/` و نه pytest.
نتیجهٔ اجرای واقعی من:

```
_smoke.py           ALL SMOKE TESTS PASSED        (46 ابزار طبقه‌بندی شد)
_smoke_hybrid.py    ALL HYBRID SMOKE TESTS PASSED (MCP round-trip، مسیریابی مدل)
_smoke_agent.py     ALL AGENT INTEGRATION TESTS PASSED (4 فراخوانی LLM، fake LLM)
_smoke_skills.py    ALL PASSED ✅                 (skill store/consolidate/replay)
```

یعنی **کد کتابخانه‌ها سالم است** — مشکل فقط نقطهٔ ورود است. `mypy`/`ruff`/CI هم
وجود ندارد؛ تنها محافظ، `# noqa: E402` های دستی است.

### ۲.۴ یافته‌های بحرانی — برنامه در وضعیت فعلی بالا نمی‌آید

| # | یافته | مکان | اثر |
|---|---|---|---|
| **۱** | `context.attach_skills(skill_engine)` در خط **۲۴۶** اجرا می‌شود، ولی `context` در خط **۲۷۸** ساخته می‌شود (`context = ContextBuilder(...)`). هیچ‌جای دیگری `context` تعریف نشده. | [main.py:246](main.py#L246) در برابر [main.py:278](main.py#L278) | **NameError: name 'context' is not defined** — اجرا همیشه در همین خط می‌میرد |
| **۲** | ایمپورت `from core.workflow import DesktopWorkflow` داخل کامنت خط قبلی گیر کرده: `...GPUMonitor  # noqa: E402from core.workflow import DesktopWorkflow  # noqa: E402`. کامپایلر آن را بخشی از کامنت می‌بیند. | [main.py:40](main.py#L40) | **NameError: DesktopWorkflow** در [main.py:313](main.py#L313) — حتی اگر باگ ۱ رفع شود |

اثبات (استخراج AST، نه حدس):

```
Name "context" nodes in main.py: [(246, 'Name'), (278, 'Name'), (279, 'Name')]
assignments to "context":        [278]
DesktopWorkflow refs:            [(313, 'Name')]
core.workflow imported in main.py: False
```

هر دو باگ یک‌خطی‌اند و ترتیب رفع هم مهم است: ابتدا خط ۴۰ را جدا کنید، سپس
`attach_skills` را پس از خط ۲۷۸ ببرید.

### ۲.۵ یافته‌های درجهٔ دو

| # | یافته | مکان | توضیح |
|---|---|---|---|
| ۳ | `return` داخل حلقهٔ `for` در `ProviderClient.list_models` | [models/llm.py](models/llm.py) | فقط خروجی *اولین* provider برمی‌گردد؛ با چند provider فعال، لیست ناقص می‌شود. `return` باید بعد از حلقه باشد. |
| ۴ | `requirements.txt` فقط `openai` را اعلام می‌کند | [requirements.txt](requirements.txt) | در عمل `aiohttp`, `edge-tts`, `vosk`, `piper`, `sounddevice`, `playwright`, `pyautogui`, `opencv-python`, `numpy` لازم‌اند. یک نصب تازه از روی این فایل، پروژه را خراب بالا می‌آورد. |
| ۵ | پروپت `_adapt_args` نام ابزار را نمی‌فرستد | [skills/engine.py](skills/engine.py) | `f"گام {index+1}: ابزار {context.get('goal')}"` — به‌جای نام ابزار، هدف کلی را می‌گذارد. تطبیق آرگومان‌ها در replay ضعیف‌تر می‌شود. |
| ۶ | `relevant()` با مهارت‌های بی‌ربط پر می‌شود | [skills/engine.py](skills/engine.py) | بعد از فیلتر `score >= 0.25`، باقی اسلات‌های top-k از پرمصرف‌ترین‌ها پر می‌شود؛ پروپت را رقیق می‌کند. |
| ۷ | `data/` و ۱۸ فایل `_smoke*`/تصویر در ریشه | — | ریشهٔ مخزن شلوغ است؛ `.gitignore` هم فقط بخشی را می‌گیرد. |
| ۸ | `security/sandbox.py` بدون استفاده و بدون پیاده‌سازی | [security/sandbox.py](security/sandbox.py) | وعدهٔ README با کد هم‌خوان نیست. |
| ۹ | تست مهاجرت کامنت‌های `noqa` | همه‌جا | `# noqa: E402` روی ۲۰+ خط نشان می‌دهد import ها عمداً بعد از `sys.path` آمده‌اند؛ راه‌حل بهتر یک پکیج نصب‌شدنی یا `pyproject.toml` است. |

---

## ۳. Hermes Agent در یک نگاه

Hermes Agent محصول open-source و self-hosted تیم **Nous Research** است: یک عامل
همیشه‌روشن که روی یک سرور (VPS یا GPU workstation) زندگی می‌کند، بین نشست‌ها
به‌خاطر می‌سپارد و مهارت‌هایش را خودش می‌سازد.

**اصول طراحی اعلام‌شده:** پایداری پروپت (system prompt میان نشست تغییر نمی‌کند تا
prefix cache نشکند)، اجرای قابل‌مشاهده، قابل‌وقفه‌بودن، هستهٔ مستقل از پلتفرم،
کوپلینگ سست، و جداسازی profile.

**زیرسامانه‌ها:**

| زیرسامانه | مشخصات |
|---|---|
| Agent Loop | یک کلاس `AIAgent` واحد؛ بدون orchestrator و بدون swarm. سه حالت API: `chat_completions`, `codex_responses`, `anthropic_messages`. |
| Tools | ۷۰+ ابزار در ~۲۸ toolset؛ ثبت خودکار در import با `registry.register()`. |
| Terminal Backends | **۷ بک‌اند**: local, Docker, SSH, Daytona, Singularity, Modal, Vercel Sandbox. |
| Gateway | ۲۵+ آداپتور پیام‌رسان (Telegram, Discord, Slack, WhatsApp, Matrix, Email, SMS, …) از یک فرایند واحد. |
| Session Storage | SQLite + FTS5، با lineage (parent/child بعد از compression) و ابزار `session_search` برای جست‌وجوی بدون‌مرز تاریخچه. |
| Context | موتور context پلاگین‌پذیر؛ پیش‌فرض = خلاصه‌سازی lossy؛ prompt caching برای Anthropic. |
| Providers | ۱۸+ provider، OAuth، credential pool، alias resolution. |
| Plugins | سه منبع کشف؛ دو نوع تخصصی: memory provider و context engine. |
| Cron | کارهای زمان‌بندی‌شده **به‌عنوان task خود عامل** (نه shell)، با امکان attach کردن skill. |
| ACP | آداپتور stdio/JSON-RPC برای VS Code / Zed / JetBrains. |
| Trajectories | خروجی ShareGPT برای تولید دادهٔ آموزش. |
| Profiles | هر profile خانهٔ Hermes جدا، حافظهٔ جدا، config جدا. |
| Tests | ~۲۵٬۰۰۰ تست در ~۱۲۵۰ فایل pytest. |

### ۳.۱ سیستم مهارت Hermes

- هر مهارت یک پوشه با `SKILL.md` است؛ ساختار: `name/description/version`,
  و بخش‌های `## When to Use`, `## Procedure`, `## Pitfalls`, `## Verification`.
- **Progressive disclosure** سه‌سطحی: `skills_list()` (~۳k توکن) → `skill_view(name)`
  → `skill_view(name, path)` برای فایل مرجع. یعنی هزینهٔ توکن متناسب با *پاسخ*
  رشد می‌کند، نه با *منبع*.
- سازگار با استاندارد باز `agentskills.io`؛ نصب از **Skills Hub** آنلاین.
- `/learn` هر منبعی (فایل، URL، کتاب، رویهٔ گفته‌شده) را به مهارت تبدیل می‌کند؛
  منابع بزرگ به «knowledge-base skill» با `references/` تبدیل می‌شوند.
- فعال‌سازی شرطی: `fallback_for_toolsets` / `requires_tools` — مهارت فقط وقتی
  دیده می‌شود که ابزار مربوطه موجود یا ناموجود باشد.
- **امنیت:** اسکنر داخلی + قرنطینه + `lock.json` + هش محتوا + اسکن advisory با
  NVIDIA SkillEvaluator Tier 1 (کشف PII، unicode smuggling، لایسنس).

### ۳.۲ حافظهٔ Hermes

دو فایل، سقف کاراکتری سخت:

| فایل | نقش | سقف |
|---|---|---|
| `MEMORY.md` | یادداشت‌های خود عامل | ۲٬۲۰۰ کاراکتر (~۸۰۰ توکن) |
| `USER.md` | پروفایل کاربر | ۱٬۳۷۵ کاراکتر (~۵۰۰ توکن) |

- به‌صورت **snapshot یخ‌زده** در ابتدای نشست در system prompt تزریق می‌شود و
  میان نشست تغییر نمی‌کند (برای حفظ prefix cache).
- عامل با ابزار `memory` و اکشن‌های `add` / `replace` / `remove` خودش مدیریت می‌کند.
  وقتی سقف پر شود، **خطا** برمی‌گرداند (بی‌صدا حذف نمی‌کند) و عامل باید همان‌جا
  ادغام/حذف کند.
- ورودی‌ها قبل از پذیرش برای الگوهای injection/exfiltration و یونیکد نامرئی
  اسکن می‌شوند.
- `session_search` شکاف را پر می‌کند: جست‌وجوی FTS5 در **همهٔ** نشست‌های گذشته،
  بدون خلاصه‌سازی LLM، ~۲۰ms.

---

## ۴. جدول مقایسه

### ۴.۱ مقایسهٔ ساختاری

| محور | E.V. | Hermes Agent |
|---|---|---|
| هدف | دستیار OS آفلاین روی یک لپ‌تاپ با GPU 4GB | عامل همیشه‌روشن روی سرور، چندپلتفرمه |
| زبان/زیرساخت | Python، ~۱۰k خط | Python، کدبیس بزرگ (۷۰+ فایل ابزار، ~۲۵k تست) |
| حلقهٔ عامل | ReAct + turbo + resume + نجات از خروجی خراب | ReAct تک‌عامل با ۳ حالت API |
| مدل | محلی (Ollama)، فقط `openai-compatible` به‌عنوان provider دوم | ۱۸+ provider + cloud |
| حافظهٔ کوتاه‌مدت | پنجرهٔ ۱۰ پیام | compression خودکار + caching |
| حافظهٔ بلندمدت | SQLite + FTS5 + embedding ترکیبی (نامحدود) | MEMORY.md/USER.md محدود + `session_search` نامحدود |
| حافظهٔ معنایی | ✅ hash n-gram + `nomic-embed-text` | ❌ (جای آن curation کاراکتری + FTS5) |
| جست‌وجوی تاریخچهٔ گفتگو | ✅ پیام‌های کامل در SQLite + FTS5 و ابزار read-only `session_search` با فیلتر نشست | ✅ `session_search` روی نشست‌های گذشته |
| حافظهٔ رویه‌ای (مهارت) | ✅ `skills.json` تخت | ✅ `SKILL.md` + `references/` + Hub |
| استاندارد مهارت | اختصاصی | `agentskills.io` باز |
| کشف مهارت | token-overlap + difflib، `top_k=5` در هر پروپت | progressive disclosure سه‌سطحی، بار صفر تا لحظهٔ نیاز |
| امنیت مهارت | ندارد (هر اجرا از skill با `record_usage` فقط شمرده می‌شود) | قرنطینه + هش + lock.json + اسکنر |
| امنیت ابزار | L0..L4 + تأیید انسانی + pkexec + لاگ JSONL | approval + ۷ بک‌اند sandbox‌شده |
| sandbox واقعی | ❌ (`NotImplementedError`) | ✅ Docker/SSH/Singularity/Modal/… |
| Gateway پیام‌رسان | خواندنِ فقط‌خواندنی از تلگرام/Slack/GitHub/… | ۲۵+ پلتفرم، send + receive |
| زمان‌بند | یادآورها که **هرگز** خودکار اجرا نمی‌شوند | cron به‌عنوان task عامل، با skill attach |
| Plugin | ❌ | ✅ سه منبع کشف |
| Sub-agent | ❌ | ✅ `delegate_tool` (+ roadmap چندعاملی) |
| یکپارچه‌سازی IDE | ❌ | ✅ ACP (VS Code / Zed / JetBrains) |
| خروجی دادهٔ آموزش | ❌ | ✅ trajectory با فرمت ShareGPT |
| Profile isolation | ❌ (یک `data/` مشترک) | ✅ `hermes -p <name>` |
| تست | ۹ اسکریپت دستی، ~۴۰۰ خط | ~۲۵٬۰۰۰ تست pytest |
| CI / lint | ❌ | بخشی از پروژه |
| مستندسازی | README یکپارچه و خوب + docstring های باکیفیت | سایت Docusaurus کامل |
| فعال‌سازی آفلاین | ✅ کامل | ❌ (سرور، وابسته به provider) |
| چندزبانه (فارسی) | ✅ STT/TTS فارسی آفلاین + intent فارسی | ❌ |

### ۴.۲ حلقهٔ خودبهسازی: تفاوت در عمق، نه در ایده

| مرحله | E.V. | Hermes |
|---|---|---|
| **ساخت** | هر اجرای موفق با ≥۲ ابزار → یک skill (`skills/engine.py`) | `/learn`، `skill_manage create`، و بازبینی پس‌زمینه |
| **تقویت** | `success_count` / `usage_count` بالا می‌رود | signal یادگیری (استفاده = ورود به timeline) |
| **تزریق** | top-5 در هر system prompt (بار ثابت، حتی بی‌ربط) | progressive disclosure: تا لازم نشود، صفر توکن |
| **پخش مجدد** | `run_skill` گام‌ها را روی router اجرا می‌کند | `skill_view` + اجرای عامل با SKILL.md به‌عنوان context |
| **انسجام** | ندارد؛ نسخه‌بندی، ادغام یا هرس ندارد | patch در حین استفاده + هرس زمان‌بندی‌شده |
| **اعتبارسنجی** | ندارد | `## Verification` اجباری در قالب + اسکن امنیتی |

یعنی E.V. سه ضلع اول چرخه را دارد و سه ضلع آخر را ندارد. این تفاوت اصلی
«چرا Hermes بهتر یاد می‌گیرد» است، نه اندازهٔ مدل.

---

## ۵. شکاف‌ها و پیشنهادها

### ۵.۱ فوری (بلاک‌کننده)

1. رفع دو خط `main.py` (بخش ۲.۴).
2. افزودن یک `tests/` با pytest و یک آزمون دود که `main.main()` را تا پیش از
   اتصال به سرویس‌ها اجرا کند — همان چیزی که این دو باگ را می‌گرفت.
3. `ruff` + `mypy` + یک workflow سادهٔ CI.

### ۵.۲ برداشت‌های مشخص از Hermes که با مقیاس E.V. جور است

| ایدهٔ Hermes | چطور در E.V. کوچک پیاده شود |
|---|---|
| **سقف کاراکتری حافظه** | الان `all_facts()` بی‌مرز است و کامل به پروپت می‌رود. یک بودجه (مثلاً ۳k کاراکتر) + خطا در سرریز + ادغام توسط مدل، کیفیت را بالا و توکن را پایین می‌برد. |
| **snapshot یخ‌زده** | `ContextBuilder.system_prompt()` هر دور بازسازی می‌شود؛ یعنی prefix cache مدل محلی همیشه می‌شکند. منجمدکردن بلوک‌های پایدار سرعت محسوسی می‌دهد. |
| **Progressive disclosure برای مهارت** | به‌جای تزریق ۵ مهارت در همهٔ پروپت‌ها، فقط `name + goal` بیاید و گام‌ها با ابزار `skill_view` خوانده شوند. |
| **`session_search`** | ✅ پیاده‌سازی شد: پیام‌های user/assistant با شناسهٔ نشست در `ev.db` ذخیره می‌شوند؛ FTS5 و fallback مبتنی بر `LIKE` جست‌وجوی read-only را انجام می‌دهند. HUD شناسهٔ پایدار محلی می‌فرستد و CLI از نشست `cli` استفاده می‌کند. |
| **`## Verification` در مهارت** | افزودن یک فیلد به `skills.json` که پیش از ثبت «موفق»، نتیجه با یک بررسی مستقل تأیید شود — جلوگیری از یادگیری مسیرهای شانسی. |
| **هام مهارت** | یک `skill_create` با اسکن امنیتی ساده (regex روی دستورات خطرناک) پیش از اجازهٔ اجرا. |

### ۵.۳ نقاط قوتی که باید حفظ شوند (و Hermes ندارد)

- **آفلاین واقعی:** Vosk فارسی + Piper برای STT/TTS، و `nomic-embed-text` محلی.
- **مهندسی برای ۴GB VRAM:** `keep_alive=30m`, `think=false`, turbo path،
  `warm()` در استارتاپ، فیلتر `*-cloud`. این‌ها تصمیم‌های دقیق و اندازه‌گیری‌شده‌اند.
- **امنیت سطح‌دار L0..L4 با `pkexec`:** برای یک عامل که فرمان شل اجرا می‌کند،
  بسیار مناسب‌تر از مدل «allow/deny» ساده است. دستور ناشناخته → L3 منطق درستی است.
- **منطق ضدشکنندگی مدل کوچک:** `_is_junk`, `_extract_textual_tool_calls`,
  `_recover_answer`, nudge برای عمل‌کردن. این‌ها دقیقاً چیزهایی هستند که یک
  پروژهٔ مبتنی بر مدل ۴B به آن‌ها نیاز دارد و پروژه‌های تحقیقاتی روی مدل‌های بزرگ
  هرگز نمی‌نویسند.
- **HUD وب بدون build step:** صفر وابستگی، SSE، state-reactive.
- **دو سری embedding با fallback خودکار:** در محیط آفلاین انتخاب هوشمندانه‌ای است.

### ۵.۴ جمع‌بندی

E.V. را باید در دستهٔ «عامل OS شخصی، آفلاین، فارسی، بهینه برای سخت‌افزار ضعیف»
سنجید — نه در دستهٔ Hermes. با معیار اول، پروژه بالای میانگین است: معماری
لایه‌ای تمیز، امنیت جدی، و توجه نادر به واقعیت‌های مدل‌های کوچک. با معیار دوم
(E.V. در برابر Hermes) فاصله زیاد است، ولی این فاصله در **مهندسی مقیاس**
(تست، پلاگین، gateway، sandbox) است، نه در بینش معماری.

سه اقدام، بیشترین بازده را دارند: (۱) رفع دو باگ و افزودن CI، (۲) بودجه‌بندی
حافظه + snapshot یخ‌زده برای سرعت و کیفیت پروپت، (۳) ارتقای حلقهٔ مهارت به
برگشت‌پذیر و قابل‌اعتبارسنجی.
