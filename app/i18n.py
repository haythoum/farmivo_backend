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
                    "ar": "لست عضوًا في أي ضيعة بعد"},
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
                         "ar": "لا توجد ضيعة بهذا الرمز"},
    "err.already_member": {"en": "You already belong to a farm", "fr": "Vous appartenez déjà à une ferme",
                           "ar": "أنت عضو في ضيعة بالفعل"},
    "err.already_member_leave": {"en": "You already belong to a farm. Leave it first",
                                 "fr": "Vous appartenez déjà à une ferme. Quittez-la d'abord",
                                 "ar": "أنت عضو في ضيعة بالفعل. غادرها أولًا"},
    "err.already_asked": {"en": "You already asked to join a farm. Cancel that request first",
                          "fr": "Vous avez déjà demandé à rejoindre une ferme. Annulez d'abord cette demande",
                          "ar": "لقد طلبت الانضمام إلى ضيعة بالفعل. ألغِ ذلك الطلب أولًا"},
    "err.already_member": {"en": "You already belong to this farm", "fr": "Vous faites déjà partie de cette ferme",
                           "ar": "أنت عضو في هذه الضيعة بالفعل"},
    "err.transfer_first": {"en": "Transfer ownership first", "fr": "Transférez d'abord la propriété",
                           "ar": "انقل الملكية أولًا"},
    "err.owner_must_transfer": {"en": "Transfer ownership before deleting your account",
                                "fr": "Transférez la propriété de la ferme avant de supprimer votre compte",
                                "ar": "انقل ملكية الضيعة قبل حذف حسابك"},
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
    "err.photo_not_found": {"en": "Photo not found", "fr": "Photo introuvable", "ar": "الصورة غير موجودة"},
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
    "err.dam_female": {"en": 'The mother of a mating must be a female. Choose a female animal', "fr": "La mère d'un accouplement doit être une femelle. Choisissez une femelle", "ar": 'يجب أن تكون الأم في التزاوج أنثى. اختر أنثى'},
    "err.sire_male": {"en": 'The father of a mating must be a male. Choose a male animal', "fr": "Le père d'un accouplement doit être un mâle. Choisissez un mâle", "ar": 'يجب أن يكون الأب في التزاوج ذكرًا. اختر ذكرًا'},
    "err.parent_not_found": {"en": 'The {parent} was not found on this farm', "fr": 'Le parent ({parent}) est introuvable dans cette ferme', "ar": 'لم يتم العثور على {parent} في هذه الضيعة'},
    "err.parent_self": {"en": 'An animal cannot be its own {parent}', "fr": 'Un animal ne peut pas être son propre parent ({parent})', "ar": 'لا يمكن أن يكون الحيوان {parent} لنفسه'},
    "err.parent_sex": {"en": 'The {parent} must be a {sex} animal. Choose another animal', "fr": 'Le parent ({parent}) doit être un animal {sex}. Choisissez un autre animal', "ar": 'يجب أن يكون {parent} حيوانًا {sex}. اختر حيوانًا آخر'},
    "err.ear_tag_used": {"en": "Ear tag '{tag}' is already used on this farm",
                         "fr": "La boucle '{tag}' est déjà utilisée dans cette ferme",
                         "ar": "رقم الأذن '{tag}' مستخدم بالفعل في هذه الضيعة"},
    "err.duplicate_tags": {"en": "Duplicate ear tags in request", "fr": "Numéros de boucle en double",
                           "ar": "أرقام أذن مكررة في الطلب"},
    "err.cannot_be_null": {"en": '{field} cannot be empty', "fr": '{field} : ce champ ne peut pas être vide', "ar": '{field}: لا يمكن ترك هذا الحقل فارغًا'},
    "err.delivered_by_birth": {"en": "Record the birth to mark a pregnancy as delivered",
                               "fr": "Enregistrez la mise bas pour marquer la gestation comme terminée",
                               "ar": "سجّل الولادة لتحديد الحمل كمكتمل"},
    "err.join_too_many": {"en": "Too many wrong codes. Try again in an hour",
                          "fr": "Trop de codes erronés. Réessayez dans une heure",
                          "ar": "رموز خاطئة كثيرة. حاول مرة أخرى بعد ساعة"},
    "err.birth_recorded": {"en": "A birth was already recorded for this breeding",
                           "fr": "Une mise bas est déjà enregistrée pour cette saillie",
                           "ar": "تم تسجيل ولادة لهذا التزاوج بالفعل"},
    "err.birth_before_mating": {"en": 'The birth date is before the mating date. Check both dates', "fr": "La date de mise bas est avant la date d'accouplement. Vérifiez les deux dates", "ar": 'تاريخ الولادة يسبق تاريخ التزاوج. تحقّق من التاريخين'},
    "err.birth_future": {"en": 'The birth date cannot be in the future. Enter the day the young were born', "fr": 'La date de mise bas ne peut pas être dans le futur. Indiquez le jour de la naissance', "ar": 'لا يمكن أن يكون تاريخ الولادة في المستقبل. أدخل اليوم الذي وُلدت فيه الصغار'},
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
    # ---------------------------------------------------------------- password reset email
    "reset.subject": {"en": "Reset your Farmivo password", "fr": "Réinitialisez votre mot de passe Farmivo",
                      "ar": "إعادة تعيين كلمة مرور Farmivo"},
    "reset.title": {"en": "Choose a new password", "fr": "Choisissez un nouveau mot de passe",
                    "ar": "اختر كلمة مرور جديدة"},
    "reset.intro": {"en": "We received a request to reset the password of your Farmivo account.",
                    "fr": "Nous avons reçu une demande de réinitialisation du mot de passe de votre compte Farmivo.",
                    "ar": "تلقّينا طلبًا لإعادة تعيين كلمة مرور حسابك في Farmivo."},
    "reset.action": {"en": "Open this link to choose a new password:",
                     "fr": "Ouvrez ce lien pour choisir un nouveau mot de passe :",
                     "ar": "افتح هذا الرابط لاختيار كلمة مرور جديدة:"},
    "reset.button": {"en": "Choose a new password", "fr": "Choisir un nouveau mot de passe",
                     "ar": "اختيار كلمة مرور جديدة"},
    "reset.expires": {"en": "The link works once and expires in 1 hour. Then sign in to the app with the new password.",
                      "fr": "Le lien ne fonctionne qu'une fois et expire dans 1 heure. Connectez-vous ensuite à l'application avec le nouveau mot de passe.",
                      "ar": "يعمل الرابط مرة واحدة وتنتهي صلاحيته خلال ساعة. ثم سجّل الدخول إلى التطبيق بكلمة المرور الجديدة."},
    "reset.ignore": {"en": "If you didn't ask for this, ignore this email: your password stays the same.",
                     "fr": "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail : votre mot de passe ne change pas.",
                     "ar": "إذا لم تطلب ذلك، فتجاهل هذه الرسالة: ستبقى كلمة مرورك كما هي."},
    # ---------------------------------------------------------------- barns, ear tags, statuses
    "err.ear_tag_species": {"en": "Ear tag '{tag}' is already used for another {species} on this farm",
                            "fr": "La boucle '{tag}' est déjà utilisée pour un autre animal de cette espèce ({species})",
                            "ar": "رقم الأذن '{tag}' مستخدم بالفعل لحيوان آخر من نفس النوع ({species})"},
    "err.barn_not_found": {"en": "Barn not found", "fr": "Bâtiment introuvable", "ar": "الحظيرة غير موجودة"},
    "err.barn_species": {"en": "Barn '{name}' only takes {barn}, not {species}. Check the species of the animal, edit the barn to allow {species}, or choose or create another barn", "fr": "Le bâtiment '{name}' n'accepte que : {barn}, pas : {species}. Vérifiez l'espèce de l'animal, modifiez le bâtiment pour accepter : {species}, ou choisissez ou créez un autre bâtiment", "ar": "الحظيرة '{name}' مخصّصة لـ {barn} فقط وليست لـ {species}. تحقّق من نوع الحيوان، أو عدّل الحظيرة لتقبل {species}، أو اختر حظيرة أخرى أو أنشئ حظيرة جديدة"},
    "err.move_not_on_farm": {"en": "Only animals on the farm can be moved ({tag})",
                              "fr": "Seuls les animaux présents sur la ferme peuvent être déplacés ({tag})",
                              "ar": "يمكن نقل الحيوانات الموجودة في الضيعة فقط ({tag})"},
    "err.no_longer_on_farm": {"en": "This animal is no longer on the farm",
                               "fr": "Cet animal n'est plus sur la ferme", "ar": "هذا الحيوان لم يعد في الضيعة"},
    "err.mate_species": {"en": "The father must be of the same species as the mother ({species})",
                         "fr": "Le père doit être de la même espèce que la mère ({species})",
                         "ar": "يجب أن يكون الأب من نوع الأم نفسه ({species})"},
    "err.parent_species": {"en": 'The {parent} must be of the same species as the animal ({species})', "fr": "Le parent ({parent}) doit être de la même espèce que l'animal ({species})", "ar": 'يجب أن يكون {parent} من نوع الحيوان نفسه ({species})'},
    "err.mate_not_on_farm": {"en": "Only animals on the farm can be mated ({tag})",
                             "fr": "Seuls les animaux présents sur la ferme peuvent être accouplés ({tag})",
                             "ar": "لا يمكن تسجيل تزاوج إلا لحيوانات موجودة في الضيعة ({tag})"},
    "val.dob_future": {"en": 'Value error, The date of birth cannot be in the future', "fr": 'La date de naissance ne peut pas être dans le futur', "ar": 'لا يمكن أن يكون تاريخ الميلاد في المستقبل'},
    "val.name_empty": {"en": 'Value error, The name cannot be empty', "fr": 'Le nom ne peut pas être vide', "ar": 'لا يمكن أن يكون الاسم فارغًا'},
    "val.next_due": {"en": 'Value error, The next due date cannot be before the date given', "fr": "La prochaine échéance ne peut pas être avant la date d'administration", "ar": 'لا يمكن أن يكون الموعد القادم قبل تاريخ الإعطاء'},
    "val.bool": {"en": 'Input should be a valid boolean', "fr": 'Choisissez oui ou non', "ar": 'اختر نعم أو لا'},
    "val.le": {"en": 'Input should be less than or equal to {n}', "fr": 'Doit être inférieur ou égal à {n}', "ar": 'يجب أن يكون أصغر من أو يساوي {n}'},
    "val.int": {"en": 'Input should be a valid integer', "fr": 'Nombre entier invalide', "ar": 'يجب إدخال عدد صحيح'},
    "val.date_iso": {"en": 'Input should be a valid date (YYYY-MM-DD)', "fr": 'Date invalide (AAAA-MM-JJ)', "ar": 'تاريخ غير صالح (سنة-شهر-يوم)'},
    "val.one_of": {"en": 'Input should be one of: {values}', "fr": 'Valeur attendue parmi : {values}', "ar": 'يجب أن تكون القيمة إحدى: {values}'},
    "val.lt": {"en": 'Input should be less than {n}', "fr": 'Doit être inférieur à {n}', "ar": 'يجب أن يكون أصغر من {n}'},
    "val.enum": {"en": 'Input should be {values}', "fr": 'Valeur attendue : {values}', "ar": 'القيمة المتوقعة: {values}'},
    "msg.barn_over_capacity": {
        "en": "Reminder: the barn “{barn}” now has {count} animals for {capacity} places. The animal was added anyway.",
        "fr": "Rappel : le bâtiment « {barn} » compte maintenant {count} animaux pour {capacity} places. L'animal a bien été ajouté.",
        "ar": "تذكير: الحظيرة «{barn}» فيها الآن {count} حيوانات لـ {capacity} أماكن. تمّت إضافة الحيوان رغم ذلك."},
    "err.feed_not_found": {"en": "Feed not found", "fr": "Aliment introuvable", "ar": "العلف غير موجود"},
    "err.not_enough_feed": {"en": "Not enough in stock: {left} sacks left",
                            "fr": "Stock insuffisant : il reste {left} sacs",
                            "ar": "المخزون غير كافٍ: بقي {left} أكياس"},
    "err.no_animal_to_vaccinate": {"en": "No animal on the farm to vaccinate",
                                   "fr": "Aucun animal présent sur la ferme à vacciner",
                                   "ar": "لا يوجد حيوان في الضيعة لتلقيحه"},
    "val.barn_or_animals": {"en": "Value error, Choose a barn or animals", "fr": "Choisissez un bâtiment ou des animaux",
                            "ar": "اختر حظيرة أو حيوانات"},
    "val.month": {"en": "Input should be a month like 2026-11", "fr": "Mois attendu, par exemple 2026-11",
                  "ar": "يجب إدخال شهر مثل 2026-11"},
    "msg.feed_low": {"en": "Stock running low: {feed}, {left} sacks left. Time to buy more.",
                     "fr": "Stock bas : {feed}, il reste {left} sacs. Pensez à en racheter.",
                     "ar": "المخزون ينفد: {feed}، بقي {left} أكياس. حان وقت شراء المزيد."},
    "push.feed_low_title": {"en": "Feed running low", "fr": "Stock d'aliment bas", "ar": "العلف على وشك النفاد"},
    "push.feed_low_body": {"en": "{feed}: {left} sacks left in stock.", "fr": "{feed} : il reste {left} sacs en stock.",
                           "ar": "{feed}: بقي {left} أكياس في المخزون."},
    "msg.field_problem": {"en": '{field}: {problem}', "fr": '{field} : {problem}', "ar": '{field}: {problem}'},
    "err.birds_no_mating": {"en": '{species} lay eggs: they are not mated in Farmivo. Record their eggs in Production', "fr": "Les {species} pondent des œufs : pas d'accouplement dans Farmivo. Enregistrez leurs œufs dans Production", "ar": '{species} تبيض ولا يُسجَّل لها تزاوج في Farmivo. سجّل بيضها في قسم الإنتاج'},
    "err.mating_future": {"en": 'The mating date cannot be in the future', "fr": "La date d'accouplement ne peut pas être dans le futur", "ar": 'لا يمكن أن يكون تاريخ التزاوج في المستقبل'},
    "err.mating_before_birth": {"en": 'The mating date is before {tag} was born ({dob}). Check both dates', "fr": "La date d'accouplement est avant la naissance de {tag} ({dob}). Vérifiez les deux dates", "ar": 'تاريخ التزاوج يسبق ميلاد {tag} ({dob}). تحقّق من التاريخين'},
    "err.too_young_female": {"en": '{tag} is too young to be mated: a female ({species}) can be mated from {age}, and she was {real} old on the mating date. Check her date of birth or the mating date', "fr": "{tag} est trop jeune pour être accouplée : une femelle ({species}) peut l'être à partir de {age}, elle avait {real} à la date d'accouplement. Vérifiez sa date de naissance ou la date d'accouplement", "ar": '{tag} صغيرة جدًا على التزاوج: يمكن تزويج الأنثى ({species}) ابتداءً من عمر {age}، وكان عمرها {real} في تاريخ التزاوج. تحقّق من تاريخ ميلادها أو من تاريخ التزاوج'},
    "err.too_young_male": {"en": '{tag} is too young to be a father: a male ({species}) can mate from {age}, and he was {real} old on the mating date. Check his date of birth or choose another male', "fr": "{tag} est trop jeune pour être père : un mâle ({species}) peut saillir à partir de {age}, il avait {real} à la date d'accouplement. Vérifiez sa date de naissance ou choisissez un autre mâle", "ar": '{tag} صغير جدًا ليكون فحلًا: يمكن للذكر ({species}) التزاوج ابتداءً من عمر {age}، وكان عمره {real} في تاريخ التزاوج. تحقّق من تاريخ ميلاده أو اختر ذكرًا آخر'},
    "err.already_pregnant": {"en": "{tag} already has a mating of {date} that is not closed. Record its birth, a miscarriage or 'not pregnant' on it first", "fr": "{tag} a déjà un accouplement du {date} non clôturé. Enregistrez d'abord sa mise bas, un avortement ou « non gestante »", "ar": 'لدى {tag} تزاوج بتاريخ {date} لم يُغلق بعد. سجّل أولًا الولادة أو الإجهاض أو «غير حامل» لذلك التزاوج'},
    "err.pregnant_then": {"en": '{tag} was pregnant on that date (mating of {date}, ended {end}). Check the mating date', "fr": "{tag} était gestante à cette date (accouplement du {date}, terminé le {end}). Vérifiez la date d'accouplement", "ar": 'كانت {tag} حاملًا في ذلك التاريخ (تزاوج {date}، انتهى في {end}). تحقّق من تاريخ التزاوج'},
    "err.later_pregnancy": {"en": '{tag} has a later mating ({date}): an open mating cannot be dated before it. Check the mating date', "fr": '{tag} a un accouplement plus récent ({date}) : un accouplement en cours ne peut pas être daté avant. Vérifiez la date', "ar": 'لدى {tag} تزاوج لاحق ({date})، فلا يمكن أن يكون تزاوج قائم بتاريخ أسبق منه. تحقّق من تاريخ التزاوج'},
    "err.expected_window": {"en": 'For a mating on {date}, the expected birth date must be between {start} and {end} ({species}: pregnancy of {max} at most)', "fr": 'Pour un accouplement le {date}, la mise bas prévue doit être entre le {start} et le {end} ({species} : gestation de {max} au plus)', "ar": 'لتزاوج بتاريخ {date} يجب أن يكون تاريخ الولادة المتوقع بين {start} و{end} ({species}: مدة الحمل {max} على الأكثر)'},
    "err.confirmed_date": {"en": 'The pregnancy cannot be confirmed before the mating date or in the future', "fr": "La gestation ne peut pas être confirmée avant l'accouplement ni dans le futur", "ar": 'لا يمكن تأكيد الحمل قبل تاريخ التزاوج أو في المستقبل'},
    "err.miscarriage_needs": {"en": 'Enter the date of the miscarriage and why it happened', "fr": "Indiquez la date de l'avortement et sa cause", "ar": 'أدخل تاريخ الإجهاض وسببه'},
    "err.miscarriage_window": {"en": 'The miscarriage date must be today or up to 14 days ago ({start} to {end}), and not before the mating', "fr": "La date de l'avortement doit être aujourd'hui ou au plus 14 jours avant ({start} au {end}), et pas avant l'accouplement", "ar": 'يجب أن يكون تاريخ الإجهاض اليوم أو خلال 14 يومًا الماضية (من {start} إلى {end})، وليس قبل تاريخ التزاوج'},
    "err.birth_window": {"en": 'Please check the dates: a birth on {birth} is {days} days after the mating of {date}, but a pregnancy of {species} lasts from {min} to {max} at most. Check the mating date and the birth date, or record a miscarriage', "fr": "Vérifiez les dates : une mise bas le {birth} tombe {days} jours après l'accouplement du {date}, or une gestation ({species}) dure de {min} à {max} au plus. Vérifiez la date d'accouplement et la date de mise bas, ou enregistrez un avortement", "ar": 'يرجى التحقّق من التواريخ: ولادة في {birth} تأتي بعد {days} يومًا من تزاوج {date}، بينما يدوم حمل {species} من {min} إلى {max} على الأكثر. تحقّق من تاريخ التزاوج وتاريخ الولادة، أو سجّل إجهاضًا'},
    "err.litter_max": {"en": '{species} have at most {n} young at once. Check the number of young', "fr": '{species} : au plus {n} petits par mise bas. Vérifiez le nombre de petits', "ar": '{species}: لا يتجاوز عدد الصغار {n} في الولادة الواحدة. تحقّق من عدد الصغار'},
    "err.birth_not_pregnant": {"en": "This mating is marked 'not pregnant'. Change its status before recording a birth", "fr": "Cet accouplement est marqué « non gestante ». Changez son statut avant d'enregistrer une mise bas", "ar": 'هذا التزاوج مسجّل «غير حامل». غيّر حالته قبل تسجيل الولادة'},
    "err.birth_miscarried": {"en": 'This mating ended with a miscarriage. A birth cannot be recorded on it', "fr": "Cet accouplement s'est terminé par un avortement. Aucune mise bas ne peut y être enregistrée", "ar": 'انتهى هذا التزاوج بإجهاض، فلا يمكن تسجيل ولادة عليه'},
    "err.choose_other_barn": {"en": "Choose another barn", "fr": "Choisissez un autre bâtiment",
                               "ar": "اختر حظيرة أخرى"},
    "err.choose_barn": {"en": "Choose the barn", "fr": "Choisissez le bâtiment", "ar": "اختر الحظيرة"},
    "err.recent_login": {"en": "Enter your password again to confirm",
                         "fr": "Saisissez à nouveau votre mot de passe pour confirmer",
                         "ar": "أدخل كلمة المرور مرة أخرى للتأكيد"},
    "err.not_your_farm": {"en": "You are not an active member of this farm",
                          "fr": "Vous n'êtes pas membre actif de cette ferme", "ar": "لست عضوًا نشطًا في هذه الضيعة"},
    "err.barn_name": {"en": "A barn named '{name}' already exists", "fr": "Un bâtiment nommé '{name}' existe déjà",
                      "ar": "توجد حظيرة باسم '{name}' بالفعل"},
    "tx.purchase": {"en": "Purchase of {animal}", "fr": "Achat de {animal}", "ar": "شراء {animal}"},
    "tx.sale": {"en": "Sale of {animal}", "fr": "Vente de {animal}", "ar": "بيع {animal}"},
    "tx.sale_to": {"en": "Sale of {animal} to {buyer}", "fr": "Vente de {animal} à {buyer}",
                   "ar": "بيع {animal} إلى {buyer}"},
    "tx.vaccination": {"en": "Vaccination: {name} ({animal})", "fr": "Vaccination : {name} ({animal})",
                       "ar": "تلقيح: {name} ({animal})"},
    "tx.vaccination_many": {"en": "Vaccination: {name} ({n} animals)", "fr": "Vaccination : {name} ({n} animaux)",
                            "ar": "تلقيح: {name} ({n} حيوانات)"},
    "tx.treatment": {"en": "Treatment: {name} ({animal})", "fr": "Traitement : {name} ({animal})",
                     "ar": "علاج: {name} ({animal})"},
    "tx.vet_visit": {"en": "Vet visit: {name} ({animal})", "fr": "Visite vétérinaire : {name} ({animal})",
                     "ar": "زيارة بيطرية: {name} ({animal})"},
    "tx.feed": {"en": "Feed bought: {feed}, {sacks} sacks", "fr": "Aliment acheté : {feed}, {sacks} sacs",
                "ar": "شراء علف: {feed}، {sacks} أكياس"},
    "tx.feed_from": {"en": "Feed bought: {feed}, {sacks} sacks ({supplier})",
                     "fr": "Aliment acheté : {feed}, {sacks} sacs ({supplier})",
                     "ar": "شراء علف: {feed}، {sacks} أكياس ({supplier})"},
    "val.amount_positive": {"en": "Value error, The amount must be more than 0", "fr": "Le montant doit être supérieur à 0",
                            "ar": "يجب أن يكون المبلغ أكبر من 0"},
    "err.cash_out_forbidden": {"en": "Only the owner and managers can take money out of the cash box",
                               "fr": "Seuls le propriétaire et les gérants peuvent retirer de l'argent de la caisse",
                               "ar": "المالك والمسيّرون فقط يمكنهم سحب المال من الصندوق"},
    "err.no_hand_purchase": {
        "en": "Animals bought are added in Animals, with Add animal and their purchase price: they then appear in the herd and their purchase is booked here by itself",
        "fr": "Les animaux achetés s'ajoutent dans Animaux, avec Ajouter un animal et leur prix d'achat : ils apparaissent alors dans le troupeau et leur achat est inscrit ici tout seul",
        "ar": "تُضاف الحيوانات المشتراة من قسم الحيوانات، عبر إضافة حيوان مع سعر شرائها: فتظهر في القطيع ويُسجَّل شراؤها هنا تلقائيًا"},
    "err.sold_with_others": {
        "en": "This animal was sold together with other animals in one sale: change the price or the date in Finance, in that sale's entry",
        "fr": "Cet animal a été vendu avec d'autres en une seule vente : changez le prix ou la date dans Finances, dans l'écriture de cette vente",
        "ar": "بيع هذا الحيوان مع حيوانات أخرى في عملية بيع واحدة: غيّر السعر أو التاريخ من المالية، في عملية البيع هذه"},
    "err.cannot_sell": {"en": "{animal} is no longer on the farm: it cannot be sold. Take it out of this sale",
                        "fr": "{animal} n'est plus à la ferme : il ne peut pas être vendu. Retirez-le de cette vente",
                        "ar": "{animal} لم يعد في الضيعة: لا يمكن بيعه. احذفه من هذا البيع"},
    "err.barn_mixed": {"en": "{n} animals of another species are in this barn",
                       "fr": "{n} animaux d'une autre espèce sont dans ce bâtiment",
                       "ar": "يوجد {n} من حيوانات نوع آخر في هذه الحظيرة"},
    "err.too_many_resets": {"en": "Too many requests. Try again in an hour",
                            "fr": "Trop de demandes. Réessayez dans une heure",
                            "ar": "طلبات كثيرة. حاول مرة أخرى بعد ساعة"},
    "err.wait_seconds": {"en": "Please wait {seconds} seconds before asking again",
                         "fr": "Patientez {seconds} secondes avant de redemander",
                         "ar": "يرجى الانتظار {seconds} ثانية قبل الطلب مرة أخرى"},
    "err.email_invalid": {"en": "Enter a valid email address", "fr": "Saisissez une adresse e-mail valide",
                          "ar": "أدخل بريدًا إلكترونيًا صالحًا"},
    "val.age_class": {"en": "Value error, age_class '{age_class}' does not exist for {species}",
                      "fr": "Classe d'âge '{age_class}' inconnue pour : {species}",
                      "ar": "فئة العمر '{age_class}' غير موجودة لهذا النوع: {species}"},
    "val.date_future": {"en": "Value error, date cannot be in the future", "fr": "La date ne peut pas être dans le futur",
                        "ar": "لا يمكن أن يكون التاريخ في المستقبل"},
    "reminder.pregnancy_check": {"en": "Pregnancy check", "fr": "Contrôle de gestation", "ar": "فحص الحمل"},
    "reminder.pregnancy_check_animal": {"en": "Pregnancy check: {animal}", "fr": "Contrôle de gestation : {animal}",
                                        "ar": "فحص الحمل: {animal}"},
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
        seen: set[str] = set()
        regex = ""
        for i, part in enumerate(parts):
            if i % 2 == 0:
                regex += re.escape(part)
            elif part in seen:
                regex += f"(?P={part})"  # the same placeholder twice: the same words
            else:
                seen.add(part)
                regex += f"(?P<{part}>.+?)"
        out.append((re.compile(f"^{regex}$"), key))
    return out


# Species names inside error texts ("Barn 'Fold' is for sheep, not cattle"), so no English word is left.
SPECIES_NAMES = {
    "cattle": ("cattle", "bovins", "أبقار"), "sheep": ("sheep", "ovins", "أغنام"), "goat": ("goats", "caprins", "ماعز"),
    "pig": ("pigs", "porcs", "خنازير"), "horse": ("horses", "chevaux", "خيول"), "chicken": ("chickens", "poules", "دجاج"),
    "duck": ("ducks", "canards", "بط"), "rabbit": ("rabbits", "lapins", "أرانب"), "dog": ("dogs", "chiens", "كلاب"),
    "cat": ("cats", "chats", "قطط"), "other": ("other", "autres", "أخرى"),
}


# Other words that appear inside error texts: parents, sexes and the fields of the forms.
WORDS = {
    "mother": ("mother", "la mère", "الأم"), "father": ("father", "le père", "الأب"),
    "female": ("female", "femelle", "أنثى"), "male": ("male", "mâle", "ذكر"),
}
# Field names (the "loc" of a validation error) as the forms show them.
FIELD_NAMES = {
    "ear_tag": ("Ear tag", "Boucle", "رقم الأذن"), "name": ("Name", "Nom", "الاسم"),
    "species": ("Species", "Espèce", "النوع"), "sex": ("Sex", "Sexe", "الجنس"), "breed": ("Breed", "Race", "السلالة"),
    "color": ("Colour", "Couleur", "اللون"),
    "date_of_birth": ("Date of birth", "Date de naissance", "تاريخ الميلاد"),
    "date_added": ("Arrival date", "Date d'arrivée", "تاريخ الوصول"), "date": ("Date", "Date", "التاريخ"),
    "amount": ("Amount", "Montant", "المبلغ"), "category": ("Category", "Catégorie", "الفئة"),
    "purchase_price": ("Purchase price", "Prix d'achat", "سعر الشراء"), "sale_price": ("Sale price", "Prix de vente", "سعر البيع"),
    "mating_date": ("Mating date", "Date d'accouplement", "تاريخ التزاوج"),
    "birth_date": ("Birth date", "Date de mise bas", "تاريخ الولادة"),
    "expected_birth_date": ("Expected birth date", "Mise bas prévue", "تاريخ الولادة المتوقع"),
    "pregnancy_confirmed_date": ("Pregnancy confirmed on", "Gestation confirmée le", "تأكيد الحمل في"),
    "miscarriage_date": ("Miscarriage date", "Date de l'avortement", "تاريخ الإجهاض"),
    "miscarriage_reason": ("Reason for the miscarriage", "Cause de l'avortement", "سبب الإجهاض"),
    "weight_kg": ("Weight (kg)", "Poids (kg)", "الوزن (كغ)"), "quantity_kg": ("Quantity (kg)", "Quantité (kg)", "الكمية (كغ)"),
    "quantity": ("Quantity", "Quantité", "الكمية"), "address": ("Address", "Adresse", "العنوان"),
    "next_due_date": ("Next due date", "Prochaine échéance", "الموعد القادم"),
    "date_given": ("Date given", "Date d'administration", "تاريخ الإعطاء"),
    "offspring": ("Young", "Petits", "الصغار"), "birth_weight_kg": ("Birth weight (kg)", "Poids à la naissance (kg)", "الوزن عند الولادة (كغ)"),
    "description": ("Description", "Description", "الوصف"), "notes": ("Notes", "Notes", "ملاحظات"),
}


_UNIT = re.compile(r"(\d+) (months?|years?|days?)")
_UNITS = {"month": ("month", "months", "mois", "mois"), "year": ("year", "years", "an", "ans"),
          "day": ("day", "days", "jour", "jours")}
_AR_UNITS = {"month": ("شهر", "شهران", "أشهر", "شهرًا"), "year": ("سنة", "سنتان", "سنوات", "سنة"),
             "day": ("يوم", "يومان", "أيام", "يومًا")}


def _durations(value: str, lang: str) -> str | None:
    """"5 months 10 days" in ``lang`` ("5 أشهر و10 أيام"); None when ``value`` is not only durations."""
    found = _UNIT.findall(value)
    if not found or _UNIT.sub("", value).strip():
        return None
    out = []
    for n, unit in found:
        k, num = unit.rstrip("s"), int(n)
        if lang == "fr":
            out.append(f"{num} {_UNITS[k][2] if num == 1 else _UNITS[k][3]}")
        elif lang == "ar":
            one, two, few, many = _AR_UNITS[k]
            out.append(one if num == 1 else two if num == 2 else f"{num} {few}" if num <= 10 else f"{num} {many}")
        else:
            out.append(f"{num} {_UNITS[k][0] if num == 1 else _UNITS[k][1]}")
    return (" و" if lang == "ar" else " ").join(out)


def field_name(field: str, lang: str) -> str:
    """A form field's name in ``lang`` ("date_of_birth" -> "تاريخ الميلاد"); unknown fields as written."""
    names = FIELD_NAMES.get(field)
    if not names:
        return field.replace("_", " ").capitalize()
    return names[LANGS.index(lang) if lang in LANGS else 0]


def _species_words(value: str, lang: str) -> str:
    """"sheep, goat" -> "أغنام، ماعز" when every part is a species code; parents, sexes and field names in
    ``lang`` too; other values unchanged."""
    i = LANGS.index(lang) if lang in LANGS else 0
    durations = _durations(value, lang)
    if durations is not None:
        return durations
    if value in WORDS:
        return WORDS[value][i]
    if value in FIELD_NAMES:
        return FIELD_NAMES[value][i]
    parts = [p.strip() for p in value.split(",")]
    if not all(p in SPECIES_NAMES for p in parts):
        return value
    i = LANGS.index(lang) if lang in LANGS else 0
    return ("، " if lang == "ar" else ", ").join(SPECIES_NAMES[p][i] for p in parts)


def translate_text(text: str, lang: str) -> str:
    """Translate one English error text the API produces; unknown texts are returned unchanged. pydantic's
    "Value error, " prefix never reaches the reader."""
    if not isinstance(text, str):
        return text
    if lang != DEFAULT:
        for candidate in (text, "Value error, " + text.removeprefix("Value error, ")):
            for pattern, key in _patterns():
                match = pattern.match(candidate)
                if match:
                    return t(key, lang, **{k: _species_words(v, lang) for k, v in match.groupdict().items()})
    return text.removeprefix("Value error, ")


def readable_message(detail, lang: str) -> str:
    """One sentence for the apps to show: the text itself, or for a list of field errors the first one as
    "<field as the form names it>: <problem>" ("تاريخ الميلاد: لا يمكن أن يكون تاريخ الميلاد في المستقبل")."""
    if isinstance(detail, str):
        return translate_text(detail, lang)
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        problem = translate_text(str(first.get("msg", "")), lang)
        loc = [str(x) for x in first.get("loc") or [] if not isinstance(x, int) and x not in ("body", "query")]
        if not loc:
            return problem
        return t("msg.field_problem", lang, field=field_name(loc[-1], lang), problem=problem)
    return t("err.bad_request", lang)


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
