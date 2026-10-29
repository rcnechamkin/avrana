# Media Home identity bindings seed (RC1 finding S1). Owner-run, read-only: it changes nothing in Authentik.
#
#   ssh avrana 'docker exec -i authentik-server ak shell' < scripts/identity-bindings-seed.py \
#       | grep '^AVRANA-SEED ' | cut -c13- > identity_seed.json
#
# Prints ONE line, "AVRANA-SEED " + JSON {"format", "version", "users": {username: sha256(sub)}}, for every Authentik
# user (active or not: an inactive user still owns its name). `sub` is what the Home proxy providers put in the token
# with sub_mode hashed_user_id: `User.uid` (authentik/providers/oauth2/id_token.py). Only its sha256 leaves Authentik,
# the same digest Home stores (services/avrana-home/avrana_home/identity_bindings.py). Refuses, printing no seed, if a
# Home provider uses another sub_mode, since its digests would then never match.
# Feed it to: python3 -m avrana_home.identity_bindings init --seed <file> --reserve-upstream
import hashlib
import json

from authentik.core.models import User
from authentik.providers.oauth2.models import SubModes
from authentik.providers.proxy.models import ProxyProvider

home = [p for p in ProxyProvider.objects.all() if "home" in p.name.lower()]
bad = [p.name for p in home if p.sub_mode != SubModes.HASHED_USER_ID]
if not home or bad:
    print("AVRANA-SEED-REFUSED no Home proxy provider found" if not home
          else "AVRANA-SEED-REFUSED sub_mode is not hashed_user_id on: " + ", ".join(sorted(bad)))
else:
    users = {u.username: hashlib.sha256(u.uid.encode("utf-8")).hexdigest() for u in User.objects.all()}
    print("AVRANA-SEED " + json.dumps({"format": "avrana-identity-seed", "version": 1, "users": users},
                                      sort_keys=True))
