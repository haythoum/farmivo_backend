"""Breeds offered in the apps' breed list, per species (local Tunisian and Maghreb breeds first, then the common
international ones, then "Crossbred").

The apps show these in a drop-down and let the farmer type another breed ("Other..."). The animal stores the
breed as text (the English name below for a listed breed), so breeds typed before the list existed stay valid.
GET /v1/breeds returns the list with names in the caller's language; ``label`` turns a stored breed into the
caller's language for display (``breed_label`` on animals).
"""
from __future__ import annotations

# species -> [(stored name = English, French, Arabic)]
BREEDS: dict[str, list[tuple[str, str, str]]] = {
    "cattle": [
        ("Holstein", "Prim'Holstein", "هولشتاين"),
        ("Montbéliarde", "Montbéliarde", "مونبليارد"),
        ("Brown Swiss", "Brune des Alpes", "السويسري البني"),
        ("Tarentaise", "Tarentaise", "تارنتيز"),
        ("Simmental", "Simmental (Fleckvieh)", "سيمنتال"),
        ("Brune de l'Atlas", "Brune de l'Atlas", "بني الأطلس"),
        ("Blonde du Cap Bon", "Blonde du Cap Bon", "شقراء الوطن القبلي"),
        ("Charolais", "Charolaise", "شاروليه"),
        ("Limousin", "Limousine", "ليموزين"),
        ("Blonde d'Aquitaine", "Blonde d'Aquitaine", "شقراء أكيتين"),
        ("Normande", "Normande", "نورماندي"),
        ("Jersey", "Jersiaise", "جيرسي"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "sheep": [
        ("Barbarine", "Barbarine", "البربرين (ذات الذيل العريض)"),
        ("Queue Fine de l'Ouest", "Queue Fine de l'Ouest", "الغربي ذو الذيل الرفيع"),
        ("Noire de Thibar", "Noire de Thibar", "السوداء التيبارية"),
        ("Sicilo-Sarde", "Sicilo-Sarde", "الصقلي السرديني"),
        ("D'man", "D'man", "الدمان"),
        ("Ouled Djellal", "Ouled Djellal", "أولاد جلال"),
        ("Merino", "Mérinos", "المرينو"),
        ("Lacaune", "Lacaune", "لاكون"),
        ("Awassi", "Awassi", "العواسي"),
        ("Assaf", "Assaf", "العساف"),
        ("Texel", "Texel", "تكسل"),
        ("Suffolk", "Suffolk", "سوفولك"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "goat": [
        ("Local", "Locale", "محلية"),
        ("Alpine", "Alpine", "الألبية"),
        ("Saanen", "Saanen", "السانن"),
        ("Damascus (Shami)", "Damascène (Shami)", "الشامي (الدمشقي)"),
        ("Maltese", "Maltaise", "المالطي"),
        ("Murciano-Granadina", "Murciano-Granadina", "المورسيانو"),
        ("Boer", "Boer", "البوير"),
        ("Anglo-Nubian", "Anglo-Nubienne", "الأنجلو نوبي"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "horse": [
        ("Arabian", "Pur-sang arabe", "عربي أصيل"),
        ("Barb", "Barbe", "البربري"),
        ("Arab-Barb", "Arabe-Barbe", "العربي البربري"),
        ("Thoroughbred", "Pur-sang anglais", "إنجليزي أصيل"),
        ("Andalusian", "Andalou", "الأندلسي"),
        ("Percheron", "Percheron", "البيرشرون"),
        ("Pony", "Poney", "قزم (بوني)"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "pig": [
        ("Large White", "Large White", "لارج وايت"),
        ("Landrace", "Landrace", "لاندريس"),
        ("Duroc", "Duroc", "دوروك"),
        ("Piétrain", "Piétrain", "بييترين"),
        ("Hampshire", "Hampshire", "هامبشاير"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "dog": [
        ("Local", "Locale", "محلي"),
        ("Sloughi", "Sloughi", "السلوقي"),
        ("German Shepherd", "Berger allemand", "الراعي الألماني"),
        ("Belgian Malinois", "Malinois", "المالينوا البلجيكي"),
        ("Kangal", "Kangal", "الكانجال"),
        ("Border Collie", "Border Collie", "البوردر كولي"),
        ("Labrador", "Labrador", "اللابرادور"),
        ("Mixed breed", "Croisé", "مختلط"),
    ],
    "cat": [
        ("European", "Européen", "أوروبي"),
        ("Siamese", "Siamois", "السيامي"),
        ("Persian", "Persan", "الفارسي"),
        ("Maine Coon", "Maine Coon", "الماين كون"),
        ("Mixed breed", "Croisé", "مختلط"),
    ],
    "chicken": [
        ("Local (Beldi)", "Locale (Beldi)", "عربي (بلدي)"),
        ("ISA Brown", "ISA Brown", "إيزا براون"),
        ("Lohmann Brown", "Lohmann Brown", "لومان براون"),
        ("Leghorn", "Leghorn", "اللجهورن"),
        ("Rhode Island Red", "Rhode Island Red", "رود آيلاند الأحمر"),
        ("Sussex", "Sussex", "السسكس"),
        ("Ross 308 (broiler)", "Ross 308 (chair)", "روس 308 (لاحم)"),
        ("Cobb 500 (broiler)", "Cobb 500 (chair)", "كوب 500 (لاحم)"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
    "duck": [
        ("Local", "Local", "محلي"),
        ("Pekin", "Pékin", "البكيني"),
        ("Muscovy", "Barbarie", "البربري (المسكوفي)"),
        ("Mulard", "Mulard", "الملار"),
        ("Khaki Campbell", "Khaki Campbell", "خاكي كامبل"),
    ],
    "rabbit": [
        ("Local", "Local", "محلي"),
        ("New Zealand White", "Néo-Zélandais blanc", "النيوزيلندي الأبيض"),
        ("Californian", "Californien", "الكاليفورني"),
        ("Flemish Giant", "Géant des Flandres", "العملاق الفلمنكي"),
        ("Rex", "Rex", "الركس"),
        ("Crossbred", "Croisé", "مهجّن"),
    ],
}

_LANG_INDEX = {"en": 0, "fr": 1, "ar": 2}


def catalog(lang: str = "en") -> dict[str, list[dict]]:
    """Every species' breeds in order: {"name": stored value, "label": name in ``lang``}."""
    i = _LANG_INDEX.get(lang, 0)
    return {species: [{"name": b[0], "label": b[i]} for b in breeds] for species, breeds in BREEDS.items()}


def label(species: str | None, breed: str | None, lang: str = "en") -> str | None:
    """A stored breed in ``lang`` when it is a listed breed of the species; a typed breed is returned as is."""
    if not breed:
        return None
    for b in BREEDS.get(species or "", []):
        if b[0] == breed:
            return b[_LANG_INDEX.get(lang, 0)]
    return breed
