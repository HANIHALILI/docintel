# הרצה — docintel

שירות בינת מסמכים: מקבל קובץ, מחזיר טקסט + תיאורי VLM לתמונות שבו.

## מה רץ

| שירות | תפקיד | פורט |
|---|---|---|
| `xberg` | מנוע חילוץ (טקסט + תמונות), container רשמי `1.0.14` | 8000 (פנימי) |
| `docintel` | השירות שלנו: חילוץ מהיר + נתיב VLM אסינכרוני | 8090 |
| `mock-vlm` | שרת VLM מזויף לבדיקות (מחזיר תשובה קבועה) | 9090 |

הזרימה: `docintel` שולח את הקובץ ל־`xberg` ב־HTTP → מקבל טקסט+תמונות → שולח כל תמונה ל־VLM במקביל → שוזר את התיאורים בטקסט → מחזיר JSON.

## דרישות מקדימות

- Docker + Docker Compose
- לבדיקה עם מודל אמיתי: endpoint תואם־OpenAI (מפתח OpenAI/Anthropic, או מודל בהוסטינג עצמי)

---

## מסלול א' — בדיקה מהירה עם ה־mock (בלי מודל, בלי עלות)

מוודא שכל הצינור עובד מקצה־לקצה. משתמש ב־`docker-compose.yml` (שכולל את ה־mock).

```bash
docker compose up -d --build xberg mock-vlm docintel

# בריאות
curl -s http://localhost:8090/health | python -m json.tool

# חילוץ
curl -s -F "file=@testdata/sample_with_image.docx" http://localhost:8090/extract | python -m json.tool
```

מצופה: `engine: "xberg-http"`, `images[].description` מלא ב־`MOCK-VLM-FIXED-RESPONSE`, ובשדה `text` התיאור שזור אחרי עוגן התמונה.

---

## מסלול ב' — בדיקה עם VLM אמיתי

אותו צינור בדיוק, רק שה־VLM מצביע על מודל אמיתי במקום ה־mock. שלושה משתנים משתנים: `VLM_MODEL`, `VLM_BASE_URL`, `VLM_API_KEY`.

### ⚠️ שים לב לשם המודל

ה־client שלנו מדבר פרוטוקול OpenAI **גולמי**, אז שם המודל חייב להיות מה שהספק מצפה לו:
- מול **OpenAI ישירות**: `VLM_MODEL=gpt-4o-mini` (בלי הקידומת `openai/`)
- מול **LiteLLM / router**: שם עם קידומת, למשל `openai/gpt-4o-mini`
- מול **הוסטינג עצמי**: השם שהשרת מגיש

### הדרך הכי מהירה — override חד־פעמי על ה־compose הקיים

```bash
VLM_MODEL=gpt-4o-mini \
VLM_BASE_URL=https://api.openai.com \
VLM_API_KEY=sk-... \
docker compose up -d --build xberg docintel

curl -s -F "file=@testdata/sample_with_image.docx" http://localhost:8090/extract | python -m json.tool
```

> ה־`environment` ב־`docker-compose.yml` מגדיר ערכי mock קבועים. כדי שהמשתנים מהשורה למעלה יתפסו, ערכי ה־mock צריכים לרדת — או השתמשי במסלול הפרודקשן למטה (`docker-compose.prod.yml`), שמושך את הערכים מ־`.env` ובלי mock. זו הדרך המומלצת גם לבדיקה אמיתית.

מצופה: `images[].description` עם תיאור **אמיתי** של התמונה מהמודל, ו־`vlm.calls: 1`.

---

## מסלול ג' — פרודקשן

משתמש ב־`docker-compose.prod.yml`: רק `xberg` + `docintel`, בלי mock, עם secrets מ־`.env`, ו־`xberg` לא חשוף החוצה.

```bash
# 1. הגדרת ה-VLM (פעם אחת)
cp .env.example .env
#   ערכי את .env עם VLM_MODEL / VLM_BASE_URL / VLM_API_KEY אמיתיים

# 2. הרצה
docker compose -f docker-compose.prod.yml up -d --build

# 3. בדיקה
curl -s -F "file=@testdata/sample_with_image.docx" http://localhost:8090/extract | python -m json.tool
```

### שיקולי פרודקשן

- **סודות**: המפתח ב־`.env` (git-ignored) או ב־secrets manager — לעולם לא בקוד/compose. אל תחשפי `.env`.
- **גרסאות נעוצות**: `ghcr.io/xberg-io/xberg:1.0.14` נעוץ. אל תשתמשי ב־`:latest`.
- **restart policy**: `unless-stopped` (כבר מוגדר) — הקונטיינרים קמים אחרי קריסה/reboot.
- **חשיפה**: רק `docintel:8090` חשוף. `xberg` נשאר ברשת הפנימית — אל תפרסמי אותו החוצה.
- **סקיילינג**: `docintel` ו־`xberg` נפרדים. אפשר `docker compose ... up -d --scale docintel=3` מאחורי load balancer; `xberg` סקיילבילי בנפרד.
- **מטמון**: `xberg-cache` הוא volume מתמיד — נתוני מודלים/שפה של xberg שורדים restart.
- **עלות VLM**: `VLM_MIN_PIXEL_AREA` מסנן אייקונים; המטמון מונע כפילויות. העלי `VLM_CONCURRENCY` לתפוקה, הורידי אם יש rate-limit.
- **מטמון ה־VLM הוא in-process**: הוא שורד בין בקשות אבל **לא** בין restart ולא משותף בין מספר עותקי docintel. אם צריך מטמון מתמיד/משותף — זו הרחבה עתידית (Redis).

---

## עזרה מהירה (Env vars)

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `PARSER_BACKEND` | `inprocess` | `http` (container) או `inprocess` (wheel) |
| `XBERG_URL` | — | חובה ל־http, למשל `http://xberg:8000` |
| `VLM_MODEL` | `openai/gpt-4o-mini` | שם המודל בפורמט של הספק |
| `VLM_BASE_URL` | — | endpoint תואם־OpenAI |
| `VLM_API_KEY` | — | מפתח; ריק אם אין |
| `VLM_ENABLED` | אוטו | נדלק אם יש base_url/key; `false` מכבה |
| `VLM_CONCURRENCY` | `8` | קריאות VLM מקביליות מקסימום |
| `VLM_MIN_PIXEL_AREA` | `1000` | דילוג על תמונות קטנות מזה |
| `VLM_TIMEOUT` | `60` | שניות לקריאת VLM |
| `VLM_MAX_RETRIES` | `3` | ניסיונות חוזרים |
| `VLM_PROMPT` | ברירת מחדל | ההנחיה שנשלחת למודל |

---

## פתרון תקלות

- **`docintel` מחזיר ריק / `Expecting value`** — עדיין עולה. `docker compose logs docintel`, ואז נסי שוב אחרי כמה שניות.
- **`/health` מראה `vlm_enabled: false`** — לא הגדרת `VLM_BASE_URL`/`VLM_API_KEY`. הצינור יחזיר טקסט בלי תיאורים.
- **`vlm.failed > 0`** — קריאות VLM נכשלו; ראי `vlm.errors` בתשובה (מפתח שגוי, שם מודל לא קיים, endpoint לא נגיש). מ־container, מודל על ה־host = `host.docker.internal`.
- **`422` בחילוץ** — xberg לא הצליח לפרסר את הקובץ. `docker compose logs xberg`.
- **`docintel` לא מגיע ל־xberg** — ודאי ששניהם באותו `docker compose`, ו־`XBERG_URL=http://xberg:8000` (שם השירות, לא localhost).

## עצירה

```bash
docker compose down                              # מסלול mock
docker compose -f docker-compose.prod.yml down   # פרודקשן
```
