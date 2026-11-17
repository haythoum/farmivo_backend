"""The monthly finance summary (GET /v1/finance/month-report?month=2026-11): one printable A4 page in the
reader's language (English, French or Arabic, right to left) that the apps turn into a PDF to keep or share
(Android: print to PDF; iOS: WKWebView.createPDF).

It shows the month's income, expenses and result next to the month before, the totals by category, the
animals sold and every entry of the month. Money is in the farm's currency.
"""
from __future__ import annotations

from datetime import date
from html import escape

from app import costs
from app.repository import Repository, farm_path

TEXTS = {
    "title": ("Monthly finance summary", "Bilan financier du mois", "الملخص المالي الشهري"),
    "income": ("Income", "Revenus", "الإيرادات"),
    "expenses": ("Expenses", "Dépenses", "المصاريف"),
    "result": ("Result", "Résultat", "النتيجة"),
    "this_month": ("This month", "Ce mois", "هذا الشهر"),
    "previous": ("Previous month", "Mois précédent", "الشهر السابق"),
    "by_category": ("By category", "Par catégorie", "حسب الصنف"),
    "category": ("Category", "Catégorie", "الصنف"),
    "amount": ("Amount", "Montant", "المبلغ"),
    "share": ("Share", "Part", "النسبة"),
    "sales": ("Animals sold", "Animaux vendus", "الحيوانات المباعة"),
    "animals": ("animals", "animaux", "حيوانات"),
    "average": ("average price", "prix moyen", "متوسط السعر"),
    "entries": ("Entries of the month", "Écritures du mois", "عمليات الشهر"),
    "date": ("Date", "Date", "التاريخ"),
    "description": ("Description", "Description", "الوصف"),
    "nothing": ("Nothing was recorded this month.", "Rien n'a été enregistré ce mois-ci.", "لم يُسجَّل شيء هذا الشهر."),
    "made": ("Made on {date} with Farmivo", "Établi le {date} avec Farmivo", "أُعدّ بتاريخ {date} بواسطة Farmivo"),
    "profit": ("Profit", "Bénéfice", "ربح"),
    "loss": ("Loss", "Perte", "خسارة"),
}
CATEGORIES = {
    "animal_sale": ("Animal sale", "Vente d'animaux", "بيع حيوانات"),
    "milk_sale": ("Milk sale", "Vente de lait", "بيع الحليب"),
    "egg_sale": ("Egg sale", "Vente d'œufs", "بيع البيض"),
    "other_income": ("Other income", "Autre revenu", "إيرادات أخرى"),
    "feed": ("Feed", "Alimentation", "الأعلاف"),
    "veterinary": ("Veterinary", "Vétérinaire", "البيطرة"),
    "medication": ("Medication", "Médicaments", "الأدوية"),
    "labor": ("Labor", "Main-d'œuvre", "اليد العاملة"),
    "equipment": ("Equipment", "Équipement", "المعدات"),
    "purchase_animal": ("Animal purchase", "Achat d'animaux", "شراء حيوانات"),
    "utilities": ("Utilities", "Eau et électricité", "الماء والكهرباء"),
    "other_expense": ("Other expense", "Autre dépense", "نفقات أخرى"),
}
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"],
    # Tunisian month names (as used in Tunisia: جانفي ...).
    "ar": ["جانفي", "فيفري", "مارس", "أفريل", "ماي", "جوان", "جويلية", "أوت", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
}
_COL = {"en": 0, "fr": 1, "ar": 2}


def tr(key: str, lang: str, **params) -> str:
    """A text of the report in ``lang``."""
    return TEXTS[key][_COL.get(lang, 0)].format(**params)


def category_label(category: str, lang: str) -> str:
    """A finance category in ``lang`` (a typed category as it is)."""
    names = CATEGORIES.get(category)
    return names[_COL.get(lang, 0)] if names else category


def month_label(month: date, lang: str) -> str:
    """"November 2026" / "novembre 2026" / "نوفمبر 2026"."""
    return f"{MONTHS.get(lang, MONTHS['en'])[month.month - 1]} {month.year}"


def month_bounds(month: date) -> tuple[date, date]:
    """First and last day of ``month``."""
    first = month.replace(day=1)
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, date.fromordinal(following.toordinal() - 1)


def previous_month(month: date) -> date:
    """The first day of the month before."""
    first = month.replace(day=1)
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def money(value: float, currency: str) -> str:
    """1 234,50 TND (no decimals when there are none)."""
    rounded = round(float(value), 2)
    text = f"{rounded:,.2f}".replace(",", " ").replace(".", ",")
    if text.endswith(",00"):
        text = text[:-3]
    return f"{text} {escape(currency)}"


def totals(rows: list[dict]) -> dict:
    """{"income", "expenses", "result", "income_by", "expenses_by"} of a list of transactions."""
    income_by: dict[str, float] = {}
    expenses_by: dict[str, float] = {}
    for r in rows:
        bucket = income_by if r.get("type") == "income" else expenses_by
        bucket[r["category"]] = bucket.get(r["category"], 0.0) + float(r["amount"])
    income, expenses = sum(income_by.values()), sum(expenses_by.values())
    return {"income": income, "expenses": expenses, "result": income - expenses,
            "income_by": income_by, "expenses_by": expenses_by}


def data(repo: Repository, farm_id: str, month: date) -> dict:
    """What the page shows: the month's entries, its totals and the month before's totals."""
    def entries(first: date, last: date) -> list[dict]:
        return repo.list(farm_path(farm_id, "transactions"),
                         [("date", ">=", first.isoformat()), ("date", "<=", last.isoformat())])

    first, last = month_bounds(month)
    rows = sorted(entries(first, last), key=lambda r: (r.get("date") or "", r.get("created_at") or ""))
    before = entries(*month_bounds(previous_month(month)))
    sold = [r for r in rows if r.get("type") == "income" and r.get("category") == costs.SALE_CATEGORY]
    return {"first": first, "last": last, "rows": rows, "now": totals(rows), "before": totals(before),
            "sales": {"entries": len(sold), "animals": sum(len(costs.tx_animals(r)) or 1 for r in sold),
                      "amount": sum(float(r["amount"]) for r in sold)}}


def render_html(farm: dict, month: date, lang: str, made_on: date, info: dict,
                label: callable = lambda tx, lang: tx.get("description")) -> str:  # type: ignore[valid-type]
    """The printable page. ``label(tx, lang)`` gives an entry's description in ``lang``."""
    currency = farm.get("currency") or "TND"
    rtl = lang == "ar"
    now, before = info["now"], info["before"]

    def row_cells(*cells: str, cls: str = "") -> str:
        return "<tr>" + "".join(f'<td class="{cls}">{c}</td>' if i else f"<td>{c}</td>"
                                for i, c in enumerate(cells)) + "</tr>"

    def summary_row(key: str, a: float, b: float, strong: bool = False) -> str:
        style = ' class="strong"' if strong else ""
        return f'<tr{style}><td>{tr(key, lang)}</td><td class="num">{money(a, currency)}</td>' \
               f'<td class="num muted">{money(b, currency)}</td></tr>'

    def category_table(title_key: str, values: dict[str, float], total: float) -> str:
        if not values:
            return ""
        lines = "".join(
            row_cells(escape(category_label(cat, lang)), money(amount, currency),
                      f"{round(100 * amount / total) if total else 0}%", cls="num")
            for cat, amount in sorted(values.items(), key=lambda kv: -kv[1]))
        return f"""<h3>{tr(title_key, lang)}</h3><table><tr><th>{tr('category', lang)}</th>
<th class="num">{tr('amount', lang)}</th><th class="num">{tr('share', lang)}</th></tr>{lines}</table>"""

    result_word = tr("profit", lang) if now["result"] >= 0 else tr("loss", lang)
    sales = info["sales"]
    sales_html = ""
    if sales["entries"]:
        average = sales["amount"] / sales["animals"] if sales["animals"] else 0
        sales_html = f"""<h2>{tr('sales', lang)}</h2><p class="big">{sales['animals']} {tr('animals', lang)} ·
{money(sales['amount'], currency)} <span class="muted">({tr('average', lang)} {money(average, currency)})</span></p>"""
    if info["rows"]:
        lines = "".join(
            f'<tr><td class="nowrap">{escape(r["date"])}</td><td>{escape(category_label(r["category"], lang))}</td>'
            f'<td>{escape(label(r, lang) or "")}</td><td class="num {"plus" if r["type"] == "income" else "minus"}">'
            f'{"+" if r["type"] == "income" else "−"}{money(float(r["amount"]), currency)}</td></tr>'
            for r in info["rows"])
        entries_html = f"""<h2>{tr('entries', lang)}</h2><table><tr><th>{tr('date', lang)}</th><th>{tr('category', lang)}</th>
<th>{tr('description', lang)}</th><th class="num">{tr('amount', lang)}</th></tr>{lines}</table>"""
    else:
        entries_html = f'<p class="muted">{tr("nothing", lang)}</p>'

    return f"""<!doctype html>
<html lang="{lang}" dir="{'rtl' if rtl else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(farm.get('name') or 'Farmivo')} · {month_label(month, lang)}</title>
<style>
@page {{ size: A4; margin: 14mm 12mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font: 12.5px/1.45 -apple-system, "Segoe UI", Roboto, "Noto Sans", "Noto Naskh Arabic", Arial, sans-serif;
       color: #1E2A29; background: #fff; }}
.head {{ background: #1F6F6B; color: #fff; border-radius: 14px; padding: 16px 18px; display: flex;
        justify-content: space-between; align-items: flex-end; gap: 12px; }}
.head .brand {{ font-size: 13px; opacity: .9; }} .head h1 {{ margin: 2px 0 0; font-size: 21px; }}
.head .farm {{ font-size: 15px; font-weight: 700; text-align: end; }}
h2 {{ font-size: 15px; margin: 18px 0 8px; color: #134A47; }} h3 {{ font-size: 13px; margin: 14px 0 6px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 6px 8px; border-bottom: 1px solid #E1E8E6; text-align: start; vertical-align: top; }}
th {{ background: #F2F5F4; font-size: 11.5px; color: #5B6B69; }}
.num {{ text-align: end; white-space: nowrap; }} .nowrap {{ white-space: nowrap; }}
.muted {{ color: #5B6B69; }} .plus {{ color: #2E7D32; }} .minus {{ color: #B3261E; }}
tr.strong td {{ font-weight: 800; font-size: 14px; }}
.result {{ margin-top: 12px; padding: 12px 14px; border-radius: 12px; font-size: 16px; font-weight: 800;
          background: {'#E7F4E3' if now['result'] >= 0 else '#FDECEA'}; color: {'#2E7D32' if now['result'] >= 0 else '#B3261E'}; }}
.big {{ font-size: 15px; font-weight: 700; margin: 0; }}
.cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 560px) {{ .cols {{ grid-template-columns: 1fr; }} }}
.foot {{ margin-top: 22px; padding-top: 8px; border-top: 1px solid #E1E8E6; font-size: 11px; color: #5B6B69;
        display: flex; justify-content: space-between; }}
tr {{ page-break-inside: avoid; }}
</style></head><body>
<div class="head"><div><div class="brand">Farmivo</div><h1>{tr('title', lang)}</h1>
<div>{month_label(month, lang)}</div></div><div class="farm">{escape(farm.get('name') or '')}</div></div>
<table style="margin-top:14px"><tr><th></th><th class="num">{tr('this_month', lang)}</th>
<th class="num">{tr('previous', lang)}</th></tr>
{summary_row('income', now['income'], before['income'])}
{summary_row('expenses', now['expenses'], before['expenses'])}
{summary_row('result', now['result'], before['result'], strong=True)}</table>
<div class="result">{result_word}: {money(abs(now['result']), currency)}</div>
{sales_html}
<h2>{tr('by_category', lang)}</h2><div class="cols"><div>{category_table('income', now['income_by'], now['income'])}</div>
<div>{category_table('expenses', now['expenses_by'], now['expenses'])}</div></div>
{entries_html}
<div class="foot"><span>{tr('made', lang, date=made_on.isoformat())}</span><span>Powered by Quadralens</span></div>
</body></html>"""
