from django import forms
from django.shortcuts import render

from common.data.hats import HATS
from common.forms import ImageUploadField
from users.models.user import User


class UserHatForm(forms.Form):
    add_hat = forms.BooleanField(label="Выдать новую шапку", required=False)

    new_hat = forms.ChoiceField(
        label="Выбрать из имеющихся",
        choices=[(None, "---")] + [(key, value.get("title")) for key, value in HATS.items()],
        required=False,
    )

    new_hat_name = forms.CharField(
        label="Создать новый титул",
        max_length=48,
        required=False
    )

    new_hat_icon = ImageUploadField(
        label="Иконка",
        required=False,
        resize=(256, 256),
    )

    new_hat_color = forms.CharField(
        label="Цвет",
        initial="#000000",
        max_length=16,
        required=False
    )

    remove_hat = forms.BooleanField(
        label="Удалить текущую шапку",
        required=False
    )


def get_hat_action(request, user: User, **context):
    return render(request, "godmode/action.html", {
        **context,
        "item": user,
        "form": UserHatForm(),
    })


def post_hat_action(request, user: User, **context):
    form = UserHatForm(request.POST, request.FILES)
    if form.is_valid():
        data = form.cleaned_data

        # Hats
        if data["remove_hat"]:
            user.hat = None
            user.save()

            return render(request, "godmode/message.html", {
                **context,
                "title": f"У юзера {user.full_name} отобрали шапку",
                "message": "Штош...",
            })

        if data["add_hat"]:
            if data["new_hat"]:
                hat = HATS.get(data["new_hat"])
                if hat:
                    user.hat = {"code": data["new_hat"], **hat}
                    user.save()
            else:
                user.hat = {
                    "code": "custom",
                    "title": data["new_hat_name"],
                    "icon": data["new_hat_icon"],
                    "color": data["new_hat_color"],
                }
                user.save()

        return render(request, "godmode/message.html", {
            **context,
            "title": f"Юзеру {user.full_name} выдали шапку {user.hat.get('title', 'без названия')}",
            "message": "Ура 🎉",
        })
    else:
        return render(request, "godmode/action.html", {
            **context,
            "item": user,
            "form": form,
        })
