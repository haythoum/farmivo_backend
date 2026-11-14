# Admin dashboard (/admin)

A web page for Quadralens: every farm (owner, members, animals, barns, last activity), every user and their farms,
the totals, and deleting a farm. It is **off** until a password is set.

## Turn it on (server)

1. In `/home/ubuntu/farmivo/farmivo_backend/.env` add a long password of your choice:

       FARMIVO_ADMIN_PASSWORD=<a long random password>

2. `sudo supervisorctl restart farmivo`

By default the page answers only requests made from the server itself, so the password never travels over the
network in clear (the API runs on plain HTTP).

## Open it (from your Windows PC)

1. In PowerShell: `ssh -L 8000:localhost:8000 ubuntu@51.83.71.157` and keep the window open.
2. In the browser: `http://localhost:8000/admin`, user `admin`, the password above.

`FARMIVO_ADMIN_ALLOW_REMOTE=true` would open it to the network: only do that behind HTTPS.

## Delete a farm

Farms › the farm › "Delete this farm": type the farm's name and confirm. Same deletion as `scripts/delete_farm.py`
and as the owner's "Delete farm" in the app: every record and photo of the farm; its people keep their account.
