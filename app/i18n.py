"""Languages: English (default), French and Arabic.

- ``negotiate(header)`` picks the language of a request from its Accept-Language header.
- ``t(key, lang, **params)`` returns a catalog text in that language (English if a translation is missing).
- ``translate_detail(detail, lang)`` translates the English error texts the API raises: the error handler
  calls it, so routers keep raising plain English ``ApiError`` messages.

Pushes and emails use the recipient's language (see ``recipient_lang``), not the caller's.
"""
from __future__ import annotations

import re
from functools import lru_cache

LANGS = ("en", "fr", "ar")
DEFAULT = "en"

# key -> {lang: text}. Placeholders use str.format names: {farm}, {who}, {seconds}...
MESSAGES: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- errors: auth and membership
    "err.missing_token": {"en": "Missing bearer token", "fr": "Jeton d'authentification manquant",
                          "ar": "رمز الدخول مفقود"},
    "err.invalid_token": {"en": "Invalid or expired token", "fr": "Session invalide ou expirée",
                          "ar": "الجلسة غير صالحة أو منتهية"},
    "err.no_farm": {"en": "You are not a member of a farm yet", "fr": "Vous n'êtes encore membre d'aucune ferme",
                    "ar": "لست عضوًا في أي مزرعة بعد"},
    "err.pending": {"en": "Your request to join {farm} is waiting for approval",
                    "fr": "Votre demande pour rejoindre {farm} attend une validation",
                    "ar": "طلبك للانضمام إلى {farm} في انتظار الموافقة"},
    "err.rejected": {"en": "Your request to join {farm} was rejected",
                     "fr": "Votre demande pour rejoindre {farm} a été refusée",
                     "ar": "تم رفض طلبك للانضمام إلى {farm}"},
    "err.role": {"en": "Your role ({role}) does not allow this",
                 "fr": "Votre rôle ({role}) ne permet pas cette action",
                 "ar": "دورك ({role}) لا يسمح بهذا الإجراء"},
    "err.forbidden": {"en": "Forbidden", "fr": "Action interdite", "ar": "غير مسموح"},
    "err.no_code_farm": {"en": "No farm with this code", "fr": "Aucune ferme avec ce code",
                         "ar": "لا توجد مزرعة بهذا الرمز"},
    "err.already_member": {"en": "You already belong to a farm", "fr": "Vous appartenez déjà à une ferme",
                           "ar": "أنت عضو في مزرعة بالفعل"},
    "err.already_member_leave": {"en": "You already belong to a farm. Leave it first",
                                 "fr": "Vous appartenez déjà à une ferme. Quittez-la d'abord",
                                 "ar": "أنت عضو في مزرعة بالفعل. غادرها أولًا"},
    "err.already_asked": {"en": "You already asked to join a farm. Cancel that request first",
                          "fr": "Vous avez déjà demandé à rejoindre une ferme. Annulez d'abord cette demande",
                          "ar": "لقد طلبت الانضمام إلى مزرعة بالفعل. ألغِ ذلك الطلب أولًا"},
    "err.transfer_first": {"en": "Transfer ownership first", "fr": "Transférez d'abord la propriété",
                           "ar": "انقل الملكية أولًا"},
    "err.owner_must_transfer": {"en": "Transfer ownership before deleting your account",
                                "fr": "Transférez la propriété de la ferme avant de supprimer votre compte",
                                "ar": "انقل ملكية المزرعة قبل حذف حسابك"},
    "err.member_not_found": {"en": "Member not found", "fr": "Membre introuvable", "ar": "العضو غير موجود"},
    "err.not_waiting": {"en": "This person is not waiting for approval",
                        "fr": "Cette personne n'attend pas de validation",
                        "ar": "هذا الشخص لا ينتظر الموافقة"},
    "err.approve_first": {"en": "Approve the request first", "fr": "Validez d'abord la demande",
                          "ar": "وافق على الطلب أولًا"},
    "err.owner_not_removed": {"en": "The owner cannot be removed", "fr": "Le propriétaire ne peut pas être retiré",
                              "ar": "لا يمكن إزالة المالك"},
    "err.owner_role": {"en": "The owner's role changes only by transferring ownership",
                       "fr": "Le rôle du propriétaire ne change que par un transfert de propriété",
                       "ar": "لا يتغير دور المالك إلا بنقل الملكية"},
    "err.new_owner_active": {"en": "The new owner must be an active member",
                             "fr": "Le nouveau propriétaire doit être un membre actif",
                             "ar": "يجب أن يكون المالك الجديد عضوًا نشطًا"},
    "err.already_owner": {"en": "You are already the owner", "fr": "Vous êtes déjà le propriétaire",
                          "ar": "أنت المالك بالفعل"},
    # ---------------------------------------------------------------- errors: email code
    "err.verify_first": {"en": "Verify your email first", "fr": "Vérifiez d'abord votre e-mail",
                         "ar": "أكّد بريدك الإلكتروني أولًا"},
    "err.already_verified": {"en": "Your email is already verified", "fr": "Votre e-mail est déjà vérifié",
                             "ar": "بريدك الإلكتروني مؤكَّد بالفعل"},
    "err.no_email": {"en": "Your account has no email address", "fr": "Votre compte n'a pas d'adresse e-mail",
                     "ar": "حسابك لا يحتوي على بريد إلكتروني"},
    "err.wait": {"en": "Please wait {seconds} seconds before asking for a new code",
                 "fr": "Patientez {seconds} secondes avant de demander un nouveau code",
                 "ar": "يرجى الانتظار {seconds} ثانية قبل طلب رمز جديد"},
    "err.too_many_codes": {"en": "Too many codes requested. Try again in an hour",
                           "fr": "Trop de codes demandés. Réessayez dans une heure",
                           "ar": "طلبت رموزًا كثيرة. حاول مرة أخرى بعد ساعة"},
    "err.wrong_code_one": {"en": "Wrong code. 1 attempt left", "fr": "Code incorrect. Il reste 1 essai",
                           "ar": "رمز غير صحيح. تبقّت محاولة واحدة"},
    "err.wrong_code_many": {"en": "Wrong code. {left} attempts left", "fr": "Code incorrect. Il reste {left} essais",
                            "ar": "رمز غير صحيح. تبقّت {left} محاولات"},
    "err.too_many_attempts": {"en": "Too many wrong attempts. Ask for a new code",
                              "fr": "Trop d'essais incorrects. Demandez un nouveau code",
                              "ar": "محاولات خاطئة كثيرة. اطلب رمزًا جديدًا"},
    "err.code_expired": {"en": "The code has expired. Ask for a new one",
                         "fr": "Le code a expiré. Demandez-en un nouveau",
                         "ar": "انتهت صلاحية الرمز. اطلب رمزًا جديدًا"},
    "err.email_failed": {"en": "We could not send the email. Try again later",
                         "fr": "Nous n'avons pas pu envoyer l'e-mail. Réessayez plus tard",
                         "ar": "تعذّر إرسال البريد الإلكتروني. حاول لاحقًا"},
    # ---------------------------------------------------------------- errors: records
    "err.animal_not_found": {"en": "Animal not found", "fr": "Animal introuvable", "ar": "الحيوان غير موجود"},
    "err.record_not_found": {"en": "Record not found", "fr": "Enregistrement introuvable", "ar": "السجل غير موجود"},
    "err.breeding_not_found": {"en": "Breeding record not found", "fr": "Saillie introuvable",
                               "ar": "سجل التزاوج غير موجود"},
    "err.reminder_not_found": {"en": "Reminder not found", "fr": "Rappel introuvable", "ar": "التذكير غير موجود"},
    "err.notification_not_found": {"en": "Notification not found", "fr": "Notification introuvable",
                                   "ar": "الإشعار غير موجود"},
    "err.photo_not_found": {"en": "Photo not found", "fr": "Photo introuvable", "ar": "الصورة غير موجودة"},
    "err.dam_not_found": {"en": "Dam (female) not found", "fr": "Mère (femelle) introuvable",
                          "ar": "الأم (الأنثى) غير موجودة"},
    "err.sire_not_found": {"en": "Sire (male) not found", "fr": "Père (mâle) introuvable",
                           "ar": "الأب (الذكر) غير موجود"},
    "err.dam_female": {"en": "dam_id must reference a female animal", "fr": "La mère doit être une femelle",
                       "ar": "يجب أن تكون الأم أنثى"},
    "err.sire_male": {"en": "sire_id must reference a male animal", "fr": "Le père doit être un mâle",
                      "ar": "يجب أن يكون الأب ذكرًا"},
    "err.parent_not_found": {"en": "{field} animal not found", "fr": "Animal introuvable ({field})",
                             "ar": "الحيوان غير موجود ({field})"},
    "err.parent_self": {"en": "{field} cannot be the animal itself",
                        "fr": "{field} ne peut pas être l'animal lui-même",
                        "ar": "{field} لا يمكن أن يكون الحيوان نفسه"},
    "err.parent_sex": {"en": "{field} must reference a {sex} animal", "fr": "{field} doit être un animal {sex}",
                       "ar": "{field} يجب أن يكون حيوانًا {sex}"},
    "err.ear_tag_used": {"en": "Ear tag '{tag}' is already used on this farm",
                         "fr": "La boucle '{tag}' est déjà utilisée dans cette ferme",
                         "ar": "رقم الأذن '{tag}' مستخدم بالفعل في هذه المزرعة"},
    "err.duplicate_tags": {"en": "Duplicate ear tags in request", "fr": "Numéros de boucle en double",
                           "ar": "أرقام أذن مكررة في الطلب"},
    "err.cannot_be_null": {"en": "{field} cannot be null", "fr": "{field} ne peut pas être vide",
                           "ar": "{field} لا يمكن أن يكون فارغًا"},
    "err.delivered_by_birth": {"en": "Record the birth to mark a pregnancy as delivered",
                               "fr": "Enregistrez la mise bas pour marquer la gestation comme terminée",
                               "ar": "سجّل الولادة لتحديد الحمل كمكتمل"},
    "err.join_too_many": {"en": "Too many wrong codes. Try again in an hour",
                          "fr": "Trop de codes erronés. Réessayez dans une heure",
                          "ar": "رموز خاطئة كثيرة. حاول مرة أخرى بعد ساعة"},
    "err.birth_recorded": {"en": "A birth was already recorded for this breeding",
                           "fr": "Une mise bas est déjà enregistrée pour cette saillie",
                           "ar": "تم تسجيل ولادة لهذا التزاوج بالفعل"},
    "err.birth_before_mating": {"en": "birth_date cannot be before the mating date",
                                "fr": "La date de naissance ne peut pas précéder la saillie",
                                "ar": "لا يمكن أن يكون تاريخ الولادة قبل تاريخ التزاوج"},
    "err.birth_future": {"en": "birth_date cannot be in the future",
                         "fr": "La date de naissance ne peut pas être dans le futur",
                         "ar": "لا يمكن أن يكون تاريخ الولادة في المستقبل"},
    "err.date_range": {"en": "date_from must not be after date_to",
                       "fr": "La date de début doit précéder la date de fin",
                       "ar": "يجب أن يسبق تاريخ البداية تاريخ النهاية"},
    "err.empty_file": {"en": "Empty file", "fr": "Fichier vide", "ar": "الملف فارغ"},
    "err.photo_type": {"en": "Photo must be JPEG, PNG or WebP", "fr": "La photo doit être en JPEG, PNG ou WebP",
                       "ar": "يجب أن تكون الصورة بصيغة JPEG أو PNG أو WebP"},
    "err.photo_size": {"en": "Photo exceeds {mb} MB", "fr": "La photo dépasse {mb} Mo",
                       "ar": "حجم الصورة يتجاوز {mb} ميغابايت"},
    "err.json_object": {"en": "Request body must be a JSON object", "fr": "Le corps de la requête doit être un objet JSON",
                        "ar": "يجب أن يكون محتوى الطلب كائن JSON"},
    # ---------------------------------------------------------------- errors: generic
    "err.not_found": {"en": "Not Found", "fr": "Introuvable", "ar": "غير موجود"},
    "err.method": {"en": "Method Not Allowed", "fr": "Méthode non autorisée", "ar": "الطريقة غير مسموحة"},
    "err.too_large": {"en": "Request Entity Too Large", "fr": "Requête trop volumineuse", "ar": "الطلب كبير جدًا"},
    "err.bad_request": {"en": "Bad Request", "fr": "Requête invalide", "ar": "طلب غير صالح"},
    "err.db": {"en": "Database unavailable", "fr": "Base de données indisponible", "ar": "قاعدة البيانات غير متاحة"},
    "err.internal": {"en": "Internal server error", "fr": "Erreur interne du serveur", "ar": "خطأ داخلي في الخادم"},
    # ---------------------------------------------------------------- validation (pydantic "msg" texts)
    "val.required": {"en": "Field required", "fr": "Champ obligatoire", "ar": "حقل مطلوب"},
    "val.min_len": {"en": "String should have at least {n} characters",
                    "fr": "Au moins {n} caractères", "ar": "على الأقل {n} أحرف"},
    "val.min_len_one": {"en": "String should have at least 1 character", "fr": "Ne doit pas être vide",
                        "ar": "لا يمكن أن يكون فارغًا"},
    "val.max_len": {"en": "String should have at most {n} characters",
                    "fr": "Au plus {n} caractères", "ar": "على الأكثر {n} حرفًا"},
    "val.date": {"en": "Input should be a valid date", "fr": "Date invalide", "ar": "تاريخ غير صالح"},
    "val.number": {"en": "Input should be a valid number", "fr": "Nombre invalide", "ar": "رقم غير صالح"},
    "val.gt": {"en": "Input should be greater than {n}", "fr": "Doit être supérieur à {n}", "ar": "يجب أن يكون أكبر من {n}"},
    "val.ge": {"en": "Input should be greater than or equal to {n}", "fr": "Doit être supérieur ou égal à {n}",
               "ar": "يجب أن يكون أكبر من أو يساوي {n}"},
    "val.extra": {"en": "Extra inputs are not permitted", "fr": "Champ non autorisé", "ar": "حقل غير مسموح"},
    # ---------------------------------------------------------------- pushes and in-app notifications
    "push.join.title": {"en": "{who} wants to join", "fr": "{who} souhaite rejoindre la ferme",
                        "ar": "{who} يريد الانضمام"},
    "push.join.body": {"en": "{who} asked to join {farm}. Open Members to approve or reject.",
                       "fr": "{who} a demandé à rejoindre {farm}. Ouvrez Membres pour accepter ou refuser.",
                       "ar": "طلب {who} الانضمام إلى {farm}. افتح الأعضاء للموافقة أو الرفض."},
    "push.approved.title": {"en": "Welcome to {farm}", "fr": "Bienvenue à {farm}", "ar": "مرحبًا بك في {farm}"},
    "push.approved.body": {"en": "You can now use {farm} in Farmivo.",
                           "fr": "Vous pouvez maintenant utiliser {farm} dans Farmivo.",
                           "ar": "يمكنك الآن استخدام {farm} في Farmivo."},
    "push.rejected.title": {"en": "Request not accepted", "fr": "Demande non acceptée", "ar": "لم يُقبل الطلب"},
    "push.rejected.body": {"en": "Your request to join {farm} was not accepted.",
                           "fr": "Votre demande pour rejoindre {farm} n'a pas été acceptée.",
                           "ar": "لم يُقبل طلبك للانضمام إلى {farm}."},
    "push.reminder.title": {"en": "Farmivo reminder", "fr": "Rappel Farmivo", "ar": "تذكير من Farmivo"},
    "push.reminder.body": {"en": "{title} - {when}", "fr": "{title} - {when}", "ar": "{title} - {when}"},
    "when.in_days": {"en": "due in {days} days", "fr": "dans {days} jours", "ar": "خلال {days} أيام"},
    "when.tomorrow": {"en": "due tomorrow", "fr": "demain", "ar": "غدًا"},
    "when.today": {"en": "due today", "fr": "aujourd'hui", "ar": "اليوم"},
    "when.overdue_one": {"en": "overdue by 1 day", "fr": "en retard d'un jour", "ar": "متأخر يومًا واحدًا"},
    "when.overdue": {"en": "overdue by {days} days", "fr": "en retard de {days} jours", "ar": "متأخر {days} أيام"},
    # ---------------------------------------------------------------- reminder titles
    "reminder.vaccination": {"en": "Vaccination due: {name}", "fr": "Vaccin à faire : {name}",
                             "ar": "موعد التطعيم: {name}"},
    "reminder.vaccination_animal": {"en": "Vaccination due: {name} ({animal})",
                                    "fr": "Vaccin à faire : {name} ({animal})",
                                    "ar": "موعد التطعيم: {name} ({animal})"},
    "reminder.vet": {"en": "Vet follow-up: {reason}", "fr": "Suivi vétérinaire : {reason}",
                     "ar": "متابعة بيطرية: {reason}"},
    "reminder.vet_animal": {"en": "Vet follow-up: {reason} ({animal})",
                            "fr": "Suivi vétérinaire : {reason} ({animal})",
                            "ar": "متابعة بيطرية: {reason} ({animal})"},
    "reminder.birth": {"en": "Expected birth", "fr": "Mise bas prévue", "ar": "ولادة متوقعة"},
    "reminder.birth_animal": {"en": "Expected birth: {animal}", "fr": "Mise bas prévue : {animal}",
                              "ar": "ولادة متوقعة: {animal}"},
    # ---------------------------------------------------------------- verification email
    "email.subject": {"en": "Your Farmivo verification code", "fr": "Votre code de vérification Farmivo",
                      "ar": "رمز التحقق الخاص بك في Farmivo"},
    "email.welcome": {"en": "Welcome to Farmivo!", "fr": "Bienvenue sur Farmivo !", "ar": "مرحبًا بك في Farmivo!"},
    "email.your_code": {"en": "Your verification code", "fr": "Votre code de vérification", "ar": "رمز التحقق"},
    "email.code_is": {"en": "Your Farmivo verification code is: {code}",
                      "fr": "Votre code de vérification Farmivo est : {code}",
                      "ar": "رمز التحقق الخاص بك في Farmivo هو: {code}"},
    "email.enter": {"en": "Enter this code in the Farmivo app to activate your account.",
                    "fr": "Saisissez ce code dans l'application Farmivo pour activer votre compte.",
                    "ar": "أدخل هذا الرمز في تطبيق Farmivo لتفعيل حسابك."},
    "email.expires": {"en": "The code expires in {minutes} minutes.", "fr": "Le code expire dans {minutes} minutes.",
                      "ar": "تنتهي صلاحية الرمز خلال {minutes} دقيقة."},
    "email.ignore": {"en": "If you didn't create a Farmivo account, ignore this email.",
                     "fr": "Si vous n'avez pas créé de compte Farmivo, ignorez cet e-mail.",
                     "ar": "إذا لم تنشئ حسابًا في Farmivo، فتجاهل هذه الرسالة."},
    "email.slogan": {"en": "Smart Farming. Better Living.", "fr": "Smart Farming. Better Living.",
                     "ar": "Smart Farming. Better Living."},
}


def normalize(lang: str | None) -> str | None:
    """"fr-FR" -> "fr"; None for unsupported or empty values."""
    if not lang:
        return None
    primary = lang.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in LANGS else None


def negotiate(header: str | None) -> str:
    """Language of an Accept-Language header: the supported language with the highest q (default English)."""
    best, best_q = DEFAULT, -1.0
    for position, part in enumerate((header or "").split(",")):
        piece, _, params = part.partition(";")
        lang = normalize(piece)
        if not lang:
            continue
        q = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", params)
        if match:
            try:
                q = float(match.group(1))
            except ValueError:
                q = 0.0
        q -= position * 1e-6  # keep header order among equal q values
        if q > best_q:
            best, best_q = lang, q
    return best


def t(key: str, lang: str | None = None, **params) -> str:
    """Catalog text ``key`` in ``lang`` (English if missing), formatted with ``params``."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(lang or DEFAULT) or entry[DEFAULT]
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        return text


def ref(key: str, **params) -> dict:
    """A translatable value to put inside the params of another text, rendered in the reader's language.
    Stored as plain JSON, e.g. {"$t": "when.tomorrow", "params": {}}."""
    return {"$t": key, "params": params}


def render(key: str, lang: str | None, params: dict | None = None) -> str:
    """``t`` for stored texts: params may contain ``ref(...)`` values, translated too."""
    resolved = {}
    for name, value in (params or {}).items():
        if isinstance(value, dict) and "$t" in value:
            value = render(value["$t"], lang, value.get("params"))
        resolved[name] = value
    return t(key, lang, **resolved)


@lru_cache
def _patterns() -> list[tuple[re.Pattern, str]]:
    """Regexes that recognise each English err./val. text, with named groups for its placeholders."""
    out = []
    for key, entry in MESSAGES.items():
        if not key.startswith(("err.", "val.")):
            continue
        parts = re.split(r"\{(\w+)\}", entry["en"])
        regex = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>.+?)" for i, p in enumerate(parts))
        out.append((re.compile(f"^{regex}$"), key))
    return out


def translate_text(text: str, lang: str) -> str:
    """Translate one English error text the API produces; unknown texts are returned unchanged."""
    if lang == DEFAULT or not isinstance(text, str):
        return text
    for pattern, key in _patterns():
        match = pattern.match(text)
        if match:
            return t(key, lang, **match.groupdict())
    return text


def translate_detail(detail, lang: str):
    """Translate an error ``detail``: a string, or a list of validation errors (their "msg" is translated)."""
    if lang == DEFAULT:
        return detail
    if isinstance(detail, str):
        return translate_text(detail, lang)
    if isinstance(detail, list):
        out = []
        for item in detail:
            if isinstance(item, dict) and isinstance(item.get("msg"), str):
                item = {**item, "msg": translate_text(item["msg"], lang)}
            out.append(item)
        return out
    return detail


def request_lang() -> str:
    """Language of the current request (``g.lang``), English outside a request."""
    try:
        from flask import g, has_request_context

        if has_request_context():
            return g.get("lang") or DEFAULT
    except ImportError:  # pragma: no cover
        pass
    return DEFAULT


def request_lang_given() -> bool:
    """True if the current request sent an Accept-Language header with a supported language."""
    try:
        from flask import g, has_request_context

        return has_request_context() and bool(g.get("lang_given"))
    except ImportError:  # pragma: no cover
        return False


def recipient_lang(device: dict | None = None, user: dict | None = None) -> str:
    """Language for a push or email to someone: their phone's language, else their last request's, else English."""
    return normalize((device or {}).get("language")) or normalize((user or {}).get("lang")) or DEFAULT
