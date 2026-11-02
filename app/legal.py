"""Texts of the public pages: privacy policy, terms of use, support and account deletion (en, fr, ar).

TEMPLATE TEXTS: written for QuadraLens as a starting point. They must be reviewed by the owner (and ideally a
lawyer) before the store release. Change them here; the pages are rendered by app/routers/legal.py.

Each page and language has a ``title``, an ``intro`` and ``sections``; a section has a heading ``h`` and any
of ``ul`` (bullet points, shown first) and ``p`` (paragraphs). ``{email}`` is replaced with the contact address.
"""
from __future__ import annotations

UPDATED = {"en": "Last updated: 2 November 2026", "fr": "Dernière mise à jour : 2 novembre 2026",
           "ar": "آخر تحديث: 2 نوفمبر 2026"}
CONTACT_EMAIL = "contact@quadralens.tn"

NAV = {
    "en": {"privacy": "Privacy", "terms": "Terms", "support": "Support", "delete-account": "Delete account",
           "tagline": "Smart Farming. Better Living.", "footer": "Farmivo is made by QuadraLens, Tunisia."},
    "fr": {"privacy": "Confidentialité", "terms": "Conditions", "support": "Assistance",
           "delete-account": "Supprimer le compte", "tagline": "Smart Farming. Better Living.",
           "footer": "Farmivo est développé par QuadraLens, Tunisie."},
    "ar": {"privacy": "الخصوصية", "terms": "الشروط", "support": "الدعم", "delete-account": "حذف الحساب",
           "tagline": "Smart Farming. Better Living.", "footer": "Farmivo من تطوير QuadraLens، تونس."},
}

PAGES: dict[str, dict[str, dict]] = {
    # ------------------------------------------------------------------------------------------ privacy
    "privacy": {
        "en": {
            "title": "Privacy policy",
            "intro": "This policy explains which personal data the Farmivo app and its server use, why, and what "
                     "you can do about it. Farmivo is operated by QuadraLens, Tunisia (\"we\").",
            "sections": [
                {"h": "Data we collect", "ul": [
                    "Account: your email address and, if you give it, your name. Your password is handled by "
                    "Google Firebase Authentication; we never see it.",
                    "Farm data you enter: farm name and address, animals, health, breeding, growth, production, "
                    "feeding and finance records, reminders and notifications.",
                    "Photos of animals that you upload.",
                    "Your phone's push-notification token and the app language, to send you reminders and alerts.",
                    "Technical server logs (time, IP address, request), kept for a short time for security.",
                ]},
                {"h": "Why we use it", "ul": [
                    "To create your account, verify your email with a code and sign you in.",
                    "To store and show your farm data to you and to the members of your farm, according to their role.",
                    "To send reminders (vaccinations, vet visits, expected births) and membership notifications.",
                    "To keep the service secure and working.",
                ], "p": ["We do not sell your data, show advertising or use your data for profiling."]},
                {"h": "Who processes it", "ul": [
                    "Google Firebase (Authentication and Cloud Messaging) for sign-in and push notifications. Google "
                    "may process data outside your country under its standard contractual clauses.",
                    "Mailjet for sending the verification email.",
                    "OVH for hosting our server in the European Union (France); your farm data is stored in our "
                    "MongoDB database on that server.",
                ]},
                {"h": "Sharing within your farm", "p": [
                    "People you approve as members of your farm can see the farm's data according to their role "
                    "(owner, manager, worker, viewer). Finance data is visible only to managers and the owner."]},
                {"h": "How long we keep it", "p": [
                    "We keep your data while your account exists. When you delete your account, it is deleted from "
                    "the database at once; copies in backups disappear within 30 days."]},
                {"h": "Deleting your account", "p": [
                    "In the app: More > Delete account. You can also ask us by email. Details on the "
                    "\"Delete account\" page."]},
                {"h": "Your rights", "p": [
                    "You can ask to access, correct, export or delete your personal data, and object to its use, "
                    "under the EU General Data Protection Regulation (GDPR) and Tunisian Organic Law No. 2004-63 on "
                    "the protection of personal data. Write to {email}. You can also complain to the Tunisian "
                    "authority INPDP or to the data protection authority of your country."]},
                {"h": "Security and children", "p": [
                    "Connections are protected and access to each farm is limited to its members. Farmivo is not "
                    "intended for children under 16."]},
                {"h": "Changes and contact", "p": [
                    "We will update this page if the policy changes. Questions: {email}."]},
            ],
        },
        "fr": {
            "title": "Politique de confidentialité",
            "intro": "Cette politique explique quelles données personnelles l'application Farmivo et son serveur "
                     "utilisent, pourquoi, et ce que vous pouvez faire. Farmivo est exploité par QuadraLens, "
                     "Tunisie (« nous »).",
            "sections": [
                {"h": "Données collectées", "ul": [
                    "Compte : votre adresse e-mail et, si vous l'indiquez, votre nom. Votre mot de passe est géré par "
                    "Google Firebase Authentication ; nous ne le voyons jamais.",
                    "Données de la ferme que vous saisissez : nom et adresse de la ferme, animaux, santé, "
                    "reproduction, croissance, production, alimentation, finances, rappels et notifications.",
                    "Les photos d'animaux que vous envoyez.",
                    "Le jeton de notification de votre téléphone et la langue de l'application, pour vous envoyer "
                    "rappels et alertes.",
                    "Journaux techniques du serveur (heure, adresse IP, requête), conservés peu de temps pour la sécurité.",
                ]},
                {"h": "Pourquoi nous les utilisons", "ul": [
                    "Créer votre compte, vérifier votre e-mail par un code et vous connecter.",
                    "Enregistrer vos données et les montrer à vous et aux membres de votre ferme, selon leur rôle.",
                    "Envoyer des rappels (vaccinations, visites vétérinaires, naissances prévues) et des "
                    "notifications sur les membres.",
                    "Assurer la sécurité et le bon fonctionnement du service.",
                ], "p": ["Nous ne vendons pas vos données, n'affichons pas de publicité et ne faisons pas de profilage."]},
                {"h": "Sous-traitants", "ul": [
                    "Google Firebase (Authentication et Cloud Messaging) pour la connexion et les notifications. "
                    "Google peut traiter des données hors de votre pays selon ses clauses contractuelles types.",
                    "Mailjet pour l'envoi de l'e-mail de vérification.",
                    "OVH pour l'hébergement de notre serveur dans l'Union européenne (France) ; vos données sont "
                    "stockées dans notre base MongoDB sur ce serveur.",
                ]},
                {"h": "Partage au sein de votre ferme", "p": [
                    "Les personnes que vous acceptez comme membres voient les données de la ferme selon leur rôle "
                    "(propriétaire, gestionnaire, ouvrier, lecteur). Les finances ne sont visibles que par les "
                    "gestionnaires et le propriétaire."]},
                {"h": "Durée de conservation", "p": [
                    "Nous conservons vos données tant que votre compte existe. Quand vous supprimez votre compte, "
                    "elles sont effacées de la base immédiatement ; les copies de sauvegarde disparaissent sous 30 jours."]},
                {"h": "Supprimer votre compte", "p": [
                    "Dans l'application : Plus > Supprimer le compte. Vous pouvez aussi nous le demander par e-mail. "
                    "Détails sur la page « Supprimer le compte »."]},
                {"h": "Vos droits", "p": [
                    "Vous pouvez demander l'accès, la rectification, l'export ou la suppression de vos données et "
                    "vous opposer à leur utilisation, selon le Règlement général sur la protection des données (RGPD) "
                    "et la loi organique tunisienne n° 2004-63 sur la protection des données personnelles. Écrivez à "
                    "{email}. Vous pouvez aussi saisir l'INPDP (Tunisie) ou l'autorité de protection des données de "
                    "votre pays."]},
                {"h": "Sécurité et enfants", "p": [
                    "Les connexions sont protégées et l'accès à chaque ferme est réservé à ses membres. Farmivo ne "
                    "s'adresse pas aux enfants de moins de 16 ans."]},
                {"h": "Modifications et contact", "p": [
                    "Nous mettrons cette page à jour si la politique change. Questions : {email}."]},
            ],
        },
        "ar": {
            "title": "سياسة الخصوصية",
            "intro": "توضح هذه السياسة البيانات الشخصية التي يستخدمها تطبيق Farmivo وخادمه، ولماذا، وما يمكنك "
                     "فعله بشأنها. تشغّل Farmivo شركة QuadraLens، تونس (\"نحن\").",
            "sections": [
                {"h": "البيانات التي نجمعها", "ul": [
                    "الحساب: بريدك الإلكتروني واسمك إن أدخلته. تتولى خدمة Google Firebase Authentication إدارة "
                    "كلمة المرور، ولا نطّلع عليها أبدًا.",
                    "بيانات المزرعة التي تدخلها: اسم المزرعة وعنوانها، الحيوانات، الصحة، التكاثر، النمو، الإنتاج، "
                    "التغذية، المالية، التذكيرات والإشعارات.",
                    "صور الحيوانات التي ترفعها.",
                    "رمز الإشعارات الخاص بهاتفك ولغة التطبيق، لإرسال التذكيرات والتنبيهات إليك.",
                    "سجلات تقنية للخادم (الوقت، عنوان IP، الطلب) نحتفظ بها لفترة قصيرة لأغراض الأمان.",
                ]},
                {"h": "لماذا نستخدمها", "ul": [
                    "لإنشاء حسابك والتحقق من بريدك الإلكتروني برمز وتسجيل دخولك.",
                    "لحفظ بيانات مزرعتك وعرضها لك ولأعضاء مزرعتك حسب أدوارهم.",
                    "لإرسال التذكيرات (التطعيمات، زيارات الطبيب البيطري، الولادات المتوقعة) وإشعارات الأعضاء.",
                    "للحفاظ على أمان الخدمة وحسن عملها.",
                ], "p": ["لا نبيع بياناتك ولا نعرض إعلانات ولا نستخدم بياناتك لبناء ملفات تعريفية."]},
                {"h": "من يعالج البيانات", "ul": [
                    "Google Firebase (Authentication وCloud Messaging) لتسجيل الدخول والإشعارات. قد تعالج Google "
                    "البيانات خارج بلدك وفق بنودها التعاقدية القياسية.",
                    "Mailjet لإرسال بريد التحقق.",
                    "OVH لاستضافة خادمنا في الاتحاد الأوروبي (فرنسا)؛ تُحفظ بيانات مزرعتك في قاعدة بيانات MongoDB "
                    "على هذا الخادم.",
                ]},
                {"h": "المشاركة داخل مزرعتك", "p": [
                    "يرى الأشخاص الذين توافق على انضمامهم بيانات المزرعة حسب دورهم (مالك، مدير، عامل، مشاهد). "
                    "البيانات المالية متاحة للمدير والمالك فقط."]},
                {"h": "مدة الاحتفاظ", "p": [
                    "نحتفظ ببياناتك ما دام حسابك موجودًا. عند حذف حسابك تُحذف من قاعدة البيانات فورًا، وتختفي النسخ "
                    "الاحتياطية خلال 30 يومًا."]},
                {"h": "حذف حسابك", "p": [
                    "من التطبيق: المزيد > حذف الحساب. يمكنك أيضًا مراسلتنا بالبريد الإلكتروني. التفاصيل في صفحة "
                    "\"حذف الحساب\"."]},
                {"h": "حقوقك", "p": [
                    "يمكنك طلب الاطلاع على بياناتك الشخصية أو تصحيحها أو تصديرها أو حذفها، والاعتراض على استخدامها، "
                    "وفق اللائحة الأوروبية العامة لحماية البيانات (GDPR) والقانون الأساسي التونسي عدد 63 لسنة 2004 "
                    "المتعلق بحماية المعطيات الشخصية. راسلنا على {email}. يمكنك أيضًا تقديم شكوى إلى الهيئة الوطنية "
                    "لحماية المعطيات الشخصية (INPDP) أو إلى سلطة حماية البيانات في بلدك."]},
                {"h": "الأمان والأطفال", "p": [
                    "الاتصالات محمية والوصول إلى كل مزرعة مقصور على أعضائها. التطبيق غير موجّه للأطفال دون 16 سنة."]},
                {"h": "التغييرات والتواصل", "p": [
                    "سنحدّث هذه الصفحة إذا تغيّرت السياسة. للاستفسار: {email}."]},
            ],
        },
    },
    # ------------------------------------------------------------------------------------------ terms
    "terms": {
        "en": {
            "title": "Terms of use",
            "intro": "By creating a Farmivo account you accept these terms.",
            "sections": [
                {"h": "The service", "p": [
                    "Farmivo helps you manage animals, health, breeding, growth, production and finance records "
                    "of your farm, alone or with your team."]},
                {"h": "Your account", "ul": [
                    "Give a valid email address and keep your password secret.",
                    "You are responsible for what is done with your account and for the people you approve in your farm.",
                ]},
                {"h": "Your data", "p": [
                    "The farm data you enter belongs to you. We only use it to provide the service, as described in "
                    "the privacy policy. You can delete your account at any time."]},
                {"h": "Acceptable use", "p": [
                    "Do not use Farmivo for illegal purposes, to harm others, or to try to access other farms' data "
                    "or disturb the service."]},
                {"h": "Advice and availability", "p": [
                    "Reminders and figures are an aid, not veterinary or financial advice. We work to keep Farmivo "
                    "available but provide it \"as is\", without guarantee of uninterrupted service; to the extent "
                    "allowed by law, our liability is limited."]},
                {"h": "End of use", "p": [
                    "You can stop using Farmivo and delete your account at any time. We may suspend accounts that "
                    "break these terms."]},
                {"h": "Law and contact", "p": [
                    "These terms are governed by Tunisian law. Questions: {email}."]},
            ],
        },
        "fr": {
            "title": "Conditions d'utilisation",
            "intro": "En créant un compte Farmivo, vous acceptez ces conditions.",
            "sections": [
                {"h": "Le service", "p": [
                    "Farmivo vous aide à gérer les animaux, la santé, la reproduction, la croissance, la production "
                    "et les finances de votre ferme, seul ou avec votre équipe."]},
                {"h": "Votre compte", "ul": [
                    "Indiquez une adresse e-mail valide et gardez votre mot de passe secret.",
                    "Vous êtes responsable de l'usage de votre compte et des personnes que vous acceptez dans votre ferme.",
                ]},
                {"h": "Vos données", "p": [
                    "Les données de ferme que vous saisissez vous appartiennent. Nous ne les utilisons que pour "
                    "fournir le service, comme décrit dans la politique de confidentialité. Vous pouvez supprimer "
                    "votre compte à tout moment."]},
                {"h": "Utilisation acceptable", "p": [
                    "N'utilisez pas Farmivo à des fins illégales, pour nuire à autrui, ni pour tenter d'accéder aux "
                    "données d'autres fermes ou de perturber le service."]},
                {"h": "Conseils et disponibilité", "p": [
                    "Les rappels et chiffres sont une aide, pas un avis vétérinaire ou financier. Nous faisons en "
                    "sorte que Farmivo reste disponible mais le fournissons « en l'état », sans garantie de service "
                    "ininterrompu ; dans les limites permises par la loi, notre responsabilité est limitée."]},
                {"h": "Fin d'utilisation", "p": [
                    "Vous pouvez arrêter d'utiliser Farmivo et supprimer votre compte à tout moment. Nous pouvons "
                    "suspendre les comptes qui ne respectent pas ces conditions."]},
                {"h": "Droit applicable et contact", "p": [
                    "Ces conditions sont régies par le droit tunisien. Questions : {email}."]},
            ],
        },
        "ar": {
            "title": "شروط الاستخدام",
            "intro": "بإنشائك حسابًا في Farmivo فإنك توافق على هذه الشروط.",
            "sections": [
                {"h": "الخدمة", "p": [
                    "يساعدك Farmivo على إدارة سجلات الحيوانات والصحة والتكاثر والنمو والإنتاج والمالية في مزرعتك، "
                    "بمفردك أو مع فريقك."]},
                {"h": "حسابك", "ul": [
                    "أدخل بريدًا إلكترونيًا صحيحًا وحافظ على سرية كلمة المرور.",
                    "أنت مسؤول عمّا يتم بحسابك وعن الأشخاص الذين توافق على انضمامهم إلى مزرعتك.",
                ]},
                {"h": "بياناتك", "p": [
                    "بيانات المزرعة التي تدخلها ملك لك. لا نستخدمها إلا لتقديم الخدمة كما هو موضّح في سياسة "
                    "الخصوصية. يمكنك حذف حسابك في أي وقت."]},
                {"h": "الاستخدام المقبول", "p": [
                    "لا تستخدم Farmivo لأغراض غير قانونية أو للإضرار بالآخرين أو لمحاولة الوصول إلى بيانات مزارع "
                    "أخرى أو تعطيل الخدمة."]},
                {"h": "النصائح وتوفّر الخدمة", "p": [
                    "التذكيرات والأرقام وسيلة مساعدة وليست استشارة بيطرية أو مالية. نعمل على إبقاء Farmivo متاحًا "
                    "لكننا نقدّمه \"كما هو\" دون ضمان عدم الانقطاع، وتبقى مسؤوليتنا محدودة في حدود ما يسمح به "
                    "القانون."]},
                {"h": "إنهاء الاستخدام", "p": [
                    "يمكنك التوقف عن استخدام Farmivo وحذف حسابك في أي وقت. ويمكننا تعليق الحسابات المخالفة لهذه "
                    "الشروط."]},
                {"h": "القانون والتواصل", "p": [
                    "تخضع هذه الشروط للقانون التونسي. للاستفسار: {email}."]},
            ],
        },
    },
    # ------------------------------------------------------------------------------------------ support
    "support": {
        "en": {
            "title": "Support",
            "intro": "Need help with Farmivo? Write to {email}. We usually answer within two working days.",
            "sections": [
                {"h": "How do I join my farm?", "p": [
                    "Ask the owner or a manager for the invite code (they find it in More > Members). Create your "
                    "account, confirm your email with the 6-digit code, choose \"Join a farm\" and enter the code. "
                    "You can use the farm once they approve your request."]},
                {"h": "I did not receive the email code", "p": [
                    "Check your spam folder, wait a minute and tap \"Resend code\". Make sure the email address is "
                    "correct; if not, tap \"Use another email\"."]},
                {"h": "I forgot my password", "p": [
                    "On the sign-in screen, enter your email and tap \"Forgot password?\". You will receive an email "
                    "with a link to choose a new password."]},
                {"h": "How do I delete my account?", "p": [
                    "In the app: More > Delete account. See the \"Delete account\" page for what is deleted."]},
                {"h": "Who can see my farm's data?", "p": [
                    "Only the members you approve, according to their role. Finance is visible only to managers and "
                    "the owner."]},
            ],
        },
        "fr": {
            "title": "Assistance",
            "intro": "Besoin d'aide avec Farmivo ? Écrivez à {email}. Nous répondons en général sous deux jours ouvrés.",
            "sections": [
                {"h": "Comment rejoindre ma ferme ?", "p": [
                    "Demandez le code d'invitation au propriétaire ou à un gestionnaire (dans Plus > Membres). Créez "
                    "votre compte, confirmez votre e-mail avec le code à 6 chiffres, choisissez « Rejoindre une "
                    "ferme » et saisissez le code. Vous accédez à la ferme dès qu'ils acceptent votre demande."]},
                {"h": "Je n'ai pas reçu le code par e-mail", "p": [
                    "Vérifiez vos courriers indésirables, attendez une minute et appuyez sur « Renvoyer le code ». "
                    "Vérifiez l'adresse e-mail ; si elle est fausse, appuyez sur « Utiliser une autre adresse »."]},
                {"h": "J'ai oublié mon mot de passe", "p": [
                    "Sur l'écran de connexion, saisissez votre e-mail et appuyez sur « Mot de passe oublié ? ». Vous "
                    "recevrez un e-mail avec un lien pour choisir un nouveau mot de passe."]},
                {"h": "Comment supprimer mon compte ?", "p": [
                    "Dans l'application : Plus > Supprimer le compte. Voir la page « Supprimer le compte » pour ce "
                    "qui est effacé."]},
                {"h": "Qui peut voir les données de ma ferme ?", "p": [
                    "Seulement les membres que vous acceptez, selon leur rôle. Les finances ne sont visibles que par "
                    "les gestionnaires et le propriétaire."]},
            ],
        },
        "ar": {
            "title": "الدعم",
            "intro": "تحتاج مساعدة في Farmivo؟ راسلنا على {email}. نجيب عادةً خلال يومي عمل.",
            "sections": [
                {"h": "كيف أنضم إلى مزرعتي؟", "p": [
                    "اطلب رمز الدعوة من المالك أو أحد المديرين (يجدونه في المزيد > الأعضاء). أنشئ حسابك، وأكّد بريدك "
                    "الإلكتروني بالرمز المكوّن من 6 أرقام، واختر \"الانضمام إلى مزرعة\" وأدخل الرمز. يمكنك استخدام "
                    "المزرعة بعد موافقتهم على طلبك."]},
                {"h": "لم يصلني الرمز بالبريد الإلكتروني", "p": [
                    "تحقّق من مجلد الرسائل غير المرغوب فيها، وانتظر دقيقة ثم اضغط \"إعادة إرسال الرمز\". تأكّد من "
                    "صحة البريد الإلكتروني، وإن كان خاطئًا فاضغط \"استخدام بريد آخر\"."]},
                {"h": "نسيت كلمة المرور", "p": [
                    "في شاشة تسجيل الدخول أدخل بريدك الإلكتروني واضغط \"نسيت كلمة المرور؟\". ستصلك رسالة فيها رابط "
                    "لاختيار كلمة مرور جديدة."]},
                {"h": "كيف أحذف حسابي؟", "p": [
                    "من التطبيق: المزيد > حذف الحساب. راجع صفحة \"حذف الحساب\" لمعرفة ما يُحذف."]},
                {"h": "من يمكنه رؤية بيانات مزرعتي؟", "p": [
                    "الأعضاء الذين توافق عليهم فقط، حسب دورهم. البيانات المالية متاحة للمدير والمالك فقط."]},
            ],
        },
    },
    # ------------------------------------------------------------------------------------------ delete account
    "delete-account": {
        "en": {
            "title": "Delete your Farmivo account",
            "intro": "You can delete your Farmivo account and its data at any time, in the app or by email.",
            "sections": [
                {"h": "In the app", "ul": [
                    "Open Farmivo and sign in.",
                    "Go to More > Delete account.",
                    "Type the confirmation word and tap Delete. Your account is deleted immediately.",
                ]},
                {"h": "By email", "p": [
                    "Send an email to {email} from the address of your Farmivo account, with the subject "
                    "\"Delete my Farmivo account\". We delete the account within 30 days and confirm by email."]},
                {"h": "What is deleted", "ul": [
                    "Your sign-in account (email and password), your devices and notification settings.",
                    "Your membership in your farm. The farm itself stays for its other members.",
                    "If you are the owner and nobody else is an active member: the whole farm with all its records "
                    "(animals, health, breeding, growth, production, feeding, finance, reminders, notifications) and "
                    "its photos.",
                    "If you are the owner and the farm has other members, transfer ownership to one of them first "
                    "(More > Members).",
                ]},
                {"h": "What is kept", "p": [
                    "Nothing in the database. Backup copies are erased within 30 days. Records you created in a farm "
                    "that stays active remain part of that farm's history."]},
            ],
        },
        "fr": {
            "title": "Supprimer votre compte Farmivo",
            "intro": "Vous pouvez supprimer votre compte Farmivo et ses données à tout moment, dans l'application ou par e-mail.",
            "sections": [
                {"h": "Dans l'application", "ul": [
                    "Ouvrez Farmivo et connectez-vous.",
                    "Allez dans Plus > Supprimer le compte.",
                    "Saisissez le mot de confirmation et appuyez sur Supprimer. Votre compte est supprimé immédiatement.",
                ]},
                {"h": "Par e-mail", "p": [
                    "Envoyez un e-mail à {email} depuis l'adresse de votre compte Farmivo, avec l'objet « Supprimer "
                    "mon compte Farmivo ». Nous supprimons le compte sous 30 jours et vous le confirmons par e-mail."]},
                {"h": "Ce qui est supprimé", "ul": [
                    "Votre compte de connexion (e-mail et mot de passe), vos appareils et réglages de notification.",
                    "Votre adhésion à votre ferme. La ferme reste pour ses autres membres.",
                    "Si vous êtes le propriétaire et qu'aucun autre membre n'est actif : toute la ferme avec tous ses "
                    "enregistrements (animaux, santé, reproduction, croissance, production, alimentation, finances, "
                    "rappels, notifications) et ses photos.",
                    "Si vous êtes le propriétaire et que la ferme a d'autres membres, transférez d'abord la propriété "
                    "à l'un d'eux (Plus > Membres).",
                ]},
                {"h": "Ce qui est conservé", "p": [
                    "Rien dans la base de données. Les copies de sauvegarde sont effacées sous 30 jours. Les "
                    "enregistrements que vous avez créés dans une ferme qui reste active font partie de l'historique "
                    "de cette ferme."]},
            ],
        },
        "ar": {
            "title": "حذف حسابك في Farmivo",
            "intro": "يمكنك حذف حسابك في Farmivo وبياناته في أي وقت، من التطبيق أو بالبريد الإلكتروني.",
            "sections": [
                {"h": "من التطبيق", "ul": [
                    "افتح Farmivo وسجّل الدخول.",
                    "انتقل إلى المزيد > حذف الحساب.",
                    "اكتب كلمة التأكيد واضغط حذف. يُحذف حسابك فورًا.",
                ]},
                {"h": "بالبريد الإلكتروني", "p": [
                    "أرسل رسالة إلى {email} من عنوان البريد المسجّل في حسابك، بعنوان \"حذف حسابي في Farmivo\". نحذف "
                    "الحساب خلال 30 يومًا ونؤكد لك ذلك بالبريد."]},
                {"h": "ما الذي يُحذف", "ul": [
                    "حساب تسجيل الدخول (البريد الإلكتروني وكلمة المرور) وأجهزتك وإعدادات الإشعارات.",
                    "عضويتك في المزرعة. تبقى المزرعة لبقية أعضائها.",
                    "إذا كنت المالك ولا يوجد عضو نشط آخر: المزرعة كاملة بجميع سجلاتها (الحيوانات، الصحة، التكاثر، "
                    "النمو، الإنتاج، التغذية، المالية، التذكيرات، الإشعارات) وصورها.",
                    "إذا كنت المالك وفي المزرعة أعضاء آخرون، انقل الملكية إلى أحدهم أولًا (المزيد > الأعضاء).",
                ]},
                {"h": "ما الذي يُحتفظ به", "p": [
                    "لا شيء في قاعدة البيانات. تُمسح النسخ الاحتياطية خلال 30 يومًا. تبقى السجلات التي أنشأتها في "
                    "مزرعة ما زالت نشطة ضمن تاريخ تلك المزرعة."]},
            ],
        },
    },
}
