# AlaminSignal2026Bot — ফ্রি সেটআপ

এই প্রকল্পটি সাধারণ Forex ডেটা থেকে EMA/RSI-ভিত্তিক পরীক্ষামূলক CALL/PUT/NO TRADE বার্তা Telegram-এ পাঠায়।

## সীমাবদ্ধতা
- Quotex OTC ডেটা ব্যবহার করে না।
- GitHub Actions-এর নির্ধারিত কাজ দেরি হতে পারে; এটি রিয়েল-টাইম বা প্রতি মিনিটের সেবা নয়।
- Twelve Data free tier-এর ডেটা/কোটা সীমা থাকতে পারে।
- কোনো লাভ বা নির্ভুলতার নিশ্চয়তা নেই। আগে demo-তে পরীক্ষা করুন।

## সেটআপ
1. GitHub-এ একটি Public repository তৈরি করুন, যেমন `alamin-free-signals`।
2. ZIP-এর ফাইলগুলো একই folder structure-এ upload করুন।
3. Telegram-এ BotFather থেকে bot token নিন এবং নিজের bot-এ `/start` পাঠান।
4. নিজের Telegram chat ID সংগ্রহ করুন। Bot API `getUpdates` ব্যবহার করলে token-যুক্ত URL গোপন রাখুন।
5. Twelve Data-তে free account করে API key নিন।
6. GitHub repository → Settings → Secrets and variables → Actions-এ তিনটি repository secret যোগ করুন:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TWELVE_DATA_API_KEY`
7. Actions tab-এ workflow enable করুন, যদি prompt আসে।
8. `Alamin Forex Signals` workflow খুলে `Run workflow` চাপুন। Telegram-এ বার্তা এলে কাজ করছে।
9. Schedule প্রায় প্রতি 5 মিনিটে চালানোর চেষ্টা করবে, কিন্তু সময়/ধারাবাহিকতা নিশ্চিত নয়।

## নিরাপত্তা
Token বা API key কখনো source code, screenshot, বা চ্যাটে প্রকাশ করবেন না। Token ফাঁস হলে BotFather থেকে revoke করে নতুন token নিন।
