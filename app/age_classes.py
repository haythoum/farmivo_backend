"""Age by teeth: the dental age classes a farmer can pick when the date of birth is unknown.

Each species group has its own list (lower incisors for cattle, sheep and goats, eruption then wear for horses,
milk and adult teeth for dogs and cats). Other species (pig, poultry, rabbit, other) have none: their age comes
from the date of birth only.

GET /v1/age-classes returns the lists with labels and hints in the caller's language; the API stores the key
(``age_class``) on the animal and checks that it belongs to the animal's species.
"""
from __future__ import annotations

# key -> {lang: (label, hint)}
_Text = dict[str, tuple[str, str]]

CATTLE: list[tuple[str, _Text]] = [
    ("milk_teeth", {
        "en": ("Milk teeth (under 2 years)", "All baby incisors, no permanent ones yet"),
        "fr": ("Dents de lait (moins de 2 ans)", "Toutes les incisives de lait, aucune définitive"),
        "ar": ("أسنان لبنية (أقل من سنتين)", "كل القواطع لبنية، لا توجد قواطع دائمة بعد"),
    }),
    ("two_teeth", {
        "en": ("2 teeth (18 to 24 months)", "First pair of permanent central incisors"),
        "fr": ("2 dents (18 à 24 mois)", "Première paire d'incisives définitives (pinces)"),
        "ar": ("سنّان (18 إلى 24 شهرًا)", "ظهور أول زوج من القواطع الدائمة الوسطى"),
    }),
    ("four_teeth", {
        "en": ("4 teeth (24 to 30 months)", "Second pair (middle incisors)"),
        "fr": ("4 dents (24 à 30 mois)", "Deuxième paire (premières mitoyennes)"),
        "ar": ("4 أسنان (24 إلى 30 شهرًا)", "ظهور الزوج الثاني (القواطع الوسطى)"),
    }),
    ("six_teeth", {
        "en": ("6 teeth (about 3 years)", "Third pair"),
        "fr": ("6 dents (environ 3 ans)", "Troisième paire (secondes mitoyennes)"),
        "ar": ("6 أسنان (حوالي 3 سنوات)", "ظهور الزوج الثالث"),
    }),
    ("full_mouth", {
        "en": ("Full mouth (about 4 years)", "Fourth pair (corner incisors), 42 to 48 months"),
        "fr": ("Bouche pleine (environ 4 ans)", "Quatrième paire (coins), 42 à 48 mois"),
        "ar": ("فم كامل (حوالي 4 سنوات)", "ظهور الزوج الرابع (القواطع الطرفية)، 42 إلى 48 شهرًا"),
    }),
    ("worn", {
        "en": ("Worn teeth (5 to 8 years)", "Age judged by progressive wear"),
        "fr": ("Dents usées (5 à 8 ans)", "Âge estimé par l'usure progressive"),
        "ar": ("أسنان متآكلة (5 إلى 8 سنوات)", "يُقدّر العمر حسب التآكل التدريجي"),
    }),
    ("old", {
        "en": ("Old (8 to 10+ years)", "Teeth short, worn flat and spaced apart"),
        "fr": ("Âgé (8 à 10 ans et plus)", "Dents courtes, rasées et écartées"),
        "ar": ("مسنّ (8 إلى 10 سنوات وأكثر)", "أسنان قصيرة ومسطّحة ومتباعدة"),
    }),
]

SMALL_RUMINANTS: list[tuple[str, _Text]] = [
    ("milk_teeth", {
        "en": ("Milk teeth (under 12 months)", "No permanent incisors yet (lamb or kid)"),
        "fr": ("Dents de lait (moins de 12 mois)", "Aucune incisive définitive (agneau ou chevreau)"),
        "ar": ("أسنان لبنية (أقل من 12 شهرًا)", "لا توجد قواطع دائمة بعد (حمل أو جدي)"),
    }),
    ("two_teeth", {
        "en": ("2 teeth (12 to 15 months)", "1 pair of permanent incisors"),
        "fr": ("2 dents (12 à 15 mois)", "1 paire d'incisives définitives"),
        "ar": ("سنّان / ثنيّ (12 إلى 15 شهرًا)", "زوج واحد من القواطع الدائمة"),
    }),
    ("four_teeth", {
        "en": ("4 teeth (21 to 24 months)", "2 pairs of permanent incisors"),
        "fr": ("4 dents (21 à 24 mois)", "2 paires d'incisives définitives"),
        "ar": ("4 أسنان / رباع (21 إلى 24 شهرًا)", "زوجان من القواطع الدائمة"),
    }),
    ("six_teeth", {
        "en": ("6 teeth (about 30 months)", "3 pairs of permanent incisors"),
        "fr": ("6 dents (environ 30 mois)", "3 paires d'incisives définitives"),
        "ar": ("6 أسنان / سداس (حوالي 30 شهرًا)", "3 أزواج من القواطع الدائمة"),
    }),
    ("full_mouth", {
        "en": ("Full mouth (3 years and more)", "4 pairs, 8 permanent incisors"),
        "fr": ("Bouche pleine (3 ans et plus)", "4 paires, 8 incisives définitives"),
        "ar": ("فم كامل / جامع (3 سنوات فأكثر)", "4 أزواج، 8 قواطع دائمة"),
    }),
    ("broken_mouth", {
        "en": ("Broken mouth (6 to 8+ years)", "Heavy wear, teeth spread apart or falling out"),
        "fr": ("Bouche cassée (6 à 8 ans et plus)", "Usure forte, dents écartées ou tombées"),
        "ar": ("فم متكسّر (6 إلى 8 سنوات وأكثر)", "تآكل شديد، أسنان متباعدة أو متساقطة"),
    }),
]

HORSE: list[tuple[str, _Text]] = [
    ("foal", {
        "en": ("Milk teeth (under 2.5 years)", "Only baby incisors"),
        "fr": ("Dents de lait (moins de 2 ans et demi)", "Seulement des incisives de lait"),
        "ar": ("أسنان لبنية (أقل من سنتين ونصف)", "قواطع لبنية فقط"),
    }),
    ("centrals", {
        "en": ("Central incisors (about 2.5 years)", "Permanent central incisors erupted"),
        "fr": ("Pinces (environ 2 ans et demi)", "Pinces définitives sorties"),
        "ar": ("القواطع الوسطى (حوالي سنتين ونصف)", "ظهرت القواطع الوسطى الدائمة"),
    }),
    ("middles", {
        "en": ("Middle incisors (about 3.5 years)", "Permanent middle incisors erupted"),
        "fr": ("Mitoyennes (environ 3 ans et demi)", "Mitoyennes définitives sorties"),
        "ar": ("القواطع المتوسطة (حوالي 3 سنوات ونصف)", "ظهرت القواطع المتوسطة الدائمة"),
    }),
    ("corners", {
        "en": ("Corner incisors (4.5 to 5 years)", "All permanent incisors, full mouth"),
        "fr": ("Coins (4 ans et demi à 5 ans)", "Toutes les incisives définitives"),
        "ar": ("القواطع الطرفية (4 سنوات ونصف إلى 5)", "كل القواطع الدائمة، فم كامل"),
    }),
    ("cups", {
        "en": ("Cups wearing (5 to 12 years)", "Dark cups disappear from the lower incisors"),
        "fr": ("Cornets en usure (5 à 12 ans)", "Les cornets disparaissent des incisives inférieures"),
        "ar": ("تآكل الأكواب (5 إلى 12 سنة)", "تختفي التجاويف الداكنة من القواطع السفلية"),
    }),
    ("aged", {
        "en": ("Aged (12 to 15+ years)", "Triangular incisors, dental star, teeth slanting forward"),
        "fr": ("Âgé (12 à 15 ans et plus)", "Incisives triangulaires, étoile dentaire, dents inclinées"),
        "ar": ("مسنّ (12 إلى 15 سنة وأكثر)", "قواطع مثلثة، النجمة السنية، أسنان مائلة للأمام"),
    }),
]

DOG_CAT: list[tuple[str, _Text]] = [
    ("baby_teeth", {
        "en": ("Baby teeth (0 to 4 months)", "Milk teeth erupt in the first 8 weeks"),
        "fr": ("Dents de lait (0 à 4 mois)", "Les dents de lait sortent pendant les 8 premières semaines"),
        "ar": ("أسنان لبنية (0 إلى 4 أشهر)", "تظهر الأسنان اللبنية في الأسابيع الثمانية الأولى"),
    }),
    ("changing", {
        "en": ("Changing teeth (4 to 7 months)", "Baby teeth replaced by adult teeth"),
        "fr": ("Changement de dents (4 à 7 mois)", "Les dents de lait sont remplacées"),
        "ar": ("تبديل الأسنان (4 إلى 7 أشهر)", "استبدال الأسنان اللبنية بالدائمة"),
    }),
    ("young_adult", {
        "en": ("Young adult (7 months to 2 years)", "All adult teeth, white and sharp"),
        "fr": ("Jeune adulte (7 mois à 2 ans)", "Toutes les dents adultes, blanches et pointues"),
        "ar": ("بالغ صغير (7 أشهر إلى سنتين)", "كل الأسنان الدائمة، بيضاء وحادة"),
    }),
    ("adult", {
        "en": ("Adult (2 to 7 years)", "Some yellowing and tartar"),
        "fr": ("Adulte (2 à 7 ans)", "Dents un peu jaunies, tartre"),
        "ar": ("بالغ (2 إلى 7 سنوات)", "اصفرار خفيف وجير"),
    }),
    ("senior", {
        "en": ("Senior (7+ years)", "Heavy tartar, blunted incisor tips"),
        "fr": ("Senior (7 ans et plus)", "Beaucoup de tartre, incisives émoussées"),
        "ar": ("كبير السن (7 سنوات فأكثر)", "جير كثيف وأطراف قواطع متآكلة"),
    }),
]

BY_SPECIES: dict[str, list[tuple[str, _Text]]] = {
    "cattle": CATTLE,
    "sheep": SMALL_RUMINANTS,
    "goat": SMALL_RUMINANTS,
    "horse": HORSE,
    "dog": DOG_CAT,
    "cat": DOG_CAT,
}


def keys_for(species: str | None) -> list[str]:
    """The age-class keys allowed for a species (empty: age by date of birth only)."""
    return [key for key, _ in BY_SPECIES.get(species or "", [])]


def label(species: str | None, key: str | None, lang: str = "en") -> str | None:
    """The label of an age class in ``lang`` (English when missing), or None if unknown for the species."""
    for k, texts in BY_SPECIES.get(species or "", []):
        if k == key:
            return (texts.get(lang) or texts["en"])[0]
    return None


def catalog(lang: str = "en") -> dict[str, list[dict]]:
    """Every species' classes, in order, with label and hint in ``lang``."""
    return {
        species: [{"key": k, "label": (t.get(lang) or t["en"])[0], "hint": (t.get(lang) or t["en"])[1]}
                  for k, t in classes]
        for species, classes in BY_SPECIES.items()
    }
