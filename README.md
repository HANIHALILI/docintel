# docintel

שירות בינת מסמכים: מקבל קובץ, מחזיר טקסט נקי יחד עם **תיאורי VLM לתמונות, שרטוטים וגרפים** שבתוכו — מהר, לרוחב פורמטים.

## הרעיון

שני עקרונות:

1. **הפרדה בין חילוץ מהיר לתיאור איטי.** מנוע ה־parsing מחזיר טקסט + תמונות במהירות; ה־VLM — הרכיב האיטי והיקר — רץ בנתיב אסינכרוני מקבילי נפרד, עם מטמון ו־dedup, ולעולם לא חוסם את החילוץ.
2. **ניתוק מכל parser דרך שכבת מתאם.** כל המערכת עובדת מול חוזה אחד — `parse(file) → {text, images, regions}`. מנוע החילוץ הוא רק מימוש מתחלף מאחוריו.

## ארכיטקטורה

```
POST /extract
      │
      ▼
  [api.py] ──► [adapter] ──HTTP──► xberg container   (טקסט + תמונות, VLM כבוי)
      │                              │
      │        ParseResult ◄─────────┘
      ▼
  [describer] ──► VLM endpoint       (תיאורים: מקביל · מטמון · dedup · retry)
      │
      ▼
  [weave] ──► תיאור שזור אחרי כל תמונה בטקסט
      │
      ▼
     JSON
```

- **`xberg`** רץ כ־container נפרד (image רשמי `1.0.14`); docintel קורא לו ב־HTTP. מנוע החילוץ מתחלף — יש גם מימוש in-process (wheel).
- **נתיב ה־VLM** בבעלותנו המלאה — מדבר פרוטוקול תואם־OpenAI, אז כל endpoint (OpenAI / Anthropic / vLLM / Ollama) עובד בהחלפת כתובת.

## מבנה ה־repo

```
docintel/
├── models.py          החוזה: ParseResult · VisualItem
├── adapters/          מוציא טקסט+תמונות מקובץ
│   ├── base.py            ממשק ParserAdapter
│   ├── xberg_adapter.py       מימוש in-process (wheel)
│   ├── xberg_http_adapter.py  מימוש דרך container
│   └── _xberg_common.py       מיפוי משותף
├── config.py          הגדרות מ-env
├── vlm/               נתיב ה-VLM האסינכרוני
│   ├── client.py          שליחת תמונה למודל (OpenAI-compatible)
│   └── describer.py       תזמור: מקביליות · מטמון · dedup · retry
├── weave.py           שזירת תיאורים בטקסט
└── api.py             FastAPI: /extract · /health

mock-vlm/              שרת VLM מזויף לבדיקות
testdata/              קבצי בדיקה
docker-compose.yml         בדיקה (עם mock)
docker-compose.prod.yml    פרודקשן (VLM אמיתי מ-.env)
```

## הרצה מהירה

```bash
docker compose up -d --build xberg mock-vlm docintel
curl -s -F "file=@testdata/sample_with_image.docx" http://localhost:8090/extract | python -m json.tool
```

הוראות מלאות (VLM אמיתי, פרודקשן, טבלת env, פתרון תקלות) — ראו **[RUNNING.md](RUNNING.md)**.

## סטטוס

| שלב | מה | סטטוס |
|---|---|---|
| 0 | שכבת מתאם + חילוץ מהיר | ✅ |
| 1 | נתיב VLM אסינכרוני (מקביל · מטמון · dedup) | ✅ |
| B | xberg כ־container דרך HTTP | ✅ |
| 2 | שזירה מיקומית של תיאורים | ✅ |
| 3 | ניתוב (עברית → OCR · PDF קשה → Docling) | מתוכנן |

## הערות תכנון

- **הקונפיג ל־xberg הוא dict** (לא אובייקטים typed) — עמידות ל־churn: מפתח לא־מוכר מתעלם במקום לשבור בנייה.
- **מטמון ה־VLM הוא in-process** — שורד בין בקשות, לא בין restart ולא בין עותקים. מטמון משותף (Redis) הוא הרחבה עתידית.
- **captioning של xberg לא בשימוש** — נתיב ה־VLM שלנו מחליף אותו (מקבילי במקום סדרתי), אז ה־image הרשמי הרגיל מספיק.
