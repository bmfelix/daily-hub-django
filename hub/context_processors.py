from django.conf import settings

from .modules import visible_modules


def menu(request):
    return {
        "menu_modules": [module for module in visible_modules(request.user) if module.in_menu],
        "can_edit": request.user.is_staff or not settings.REQUIRE_LOGIN,
        "require_login": settings.REQUIRE_LOGIN,
    }
