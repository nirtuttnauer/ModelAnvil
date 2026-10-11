"""Identity signal registrations.

Kept minimal for increment A: no cross-app signals yet. The module exists
so ``ready()`` has a stable import target and so later increments can hook
membership/tenant lifecycle events here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("modelanvil.identity")


def _on_membership_created(sender: type, instance: object, created: bool, **_kwargs: object) -> None:
    if created:
        logger.debug("membership created: %s", instance)


from django.db import models as _models
from modelanvil.identity.models import Membership as _Membership

_models.signals.post_save.connect(
    _on_membership_created, sender=_Membership, dispatch_uid="identity.membership_created"
)
