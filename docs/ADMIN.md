# Admin dashboard (/admin)

A web page for Quadralens to follow the apps and help the farmers. It is **off** until a password is set.

| Page | What it shows / does |
|---|---|
| Overview | What needs a look (problems of the week, new accounts, people seen in the apps), the totals, animals by species, newest farms. |
| Activity | Week by week: new accounts, new farms, **farms in use** (someone recorded or changed something that week). Farms that **stopped** (used on 2+ days, nothing for 3 weeks: worth a call) and farms created but never used. |
| Apps | Android / iPhone split, the **app versions in use**, the people still on an **older version** (ask them to update), phone models, people not seen for 30 days. Filled as people open the updated apps (they send their version with every request). |
| Problems | **Server errors** (a bug: the app said "Something went wrong"; with the request and the traceback), **emails not sent** (Mailjet refused or unreachable: verification codes, password resets) and **pushes not sent** (Firebase). Kept 90 days. |
| Farms | Every farm; one farm: members, counts, and its **data** (animals, barns, the last 40 money entries, feed stock) to answer a support question; delete the farm. |
| Users | Every account with its farms, app version, phone and last visit. **Resend code** (a new verification code; the usual limits: 60 s between codes, 5 an hour) and **Mark checked** (count the email as verified when the code email never arrives and you know the person). |
| Breed photos | Per species: which breed has its **own photo**, shows the **species' photo** or has **none**; **upload** your own photo for any breed (JPEG, PNG or WebP, resized to 960 px when Pillow is installed on the server, else JPEG only) or remove it. |
| Announcements | Write a message in English, French and/or Arabic and send it to everyone (or Android / iPhone only): a **push** to every phone, and a **dialog** shown once in the app for 30 days (also on phones that missed the push). Each person reads it in their language. "Stop showing it" removes it from the apps. |

Every form that changes something carries a token made from the admin password, so another web page cannot post
it for you.

## Turn it on (server)

1. In `/home/ubuntu/farmivo/farmivo_backend/.env` add a long password of your choice:

       FARMIVO_ADMIN_PASSWORD=<a long random password>

2. `sudo supervisorctl restart farmivo`

## Open it from your PC by the server's address

In `.env` add (the password must have at least 12 characters):

    FARMIVO_ADMIN_ALLOW_REMOTE=true

then `sudo supervisorctl restart farmivo`, and open `http://51.83.71.157:8000/admin` (user `admin`).

Protection: an address that types 8 wrong passwords within 15 minutes is refused for 15 minutes. The API still
runs on plain HTTP, so the password travels readable on the network: use a password used nowhere else, and move
to HTTPS (deploy/nginx) as planned; nothing else changes then.

Without `FARMIVO_ADMIN_ALLOW_REMOTE` the page answers only requests made from the server itself; then open it
through an SSH tunnel: `ssh -L 8000:localhost:8000 ubuntu@51.83.71.157` (keep it open), and
`http://localhost:8000/admin`.

## Delete a farm

Farms › the farm › "Delete this farm": type the farm's name and confirm. Same deletion as `scripts/delete_farm.py`
and as the owner's "Delete farm" in the app: every record and photo of the farm; its people keep their account.
