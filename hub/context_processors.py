from .modules import MODULES


def menu(request):
    return {"menu_modules": MODULES}
