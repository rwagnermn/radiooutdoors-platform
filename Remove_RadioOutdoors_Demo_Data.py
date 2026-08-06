import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
django.setup()

from django.contrib.auth.models import User


count, _ = User.objects.filter(username__startswith="demo_").delete()
print(f"Removed demo records. Deleted object count: {count}")
