
from django import forms
from django.shortcuts import render

from posts.models.post import Post
from users.models.user import User


class PostOwnerForm(forms.Form):
    transfer_ownership = forms.CharField(
        label="Передать владение постом другому юзернейму",
        required=True,
    )


def get_owner_action(request, post: Post, **context):
    return render(request, "godmode/action.html", {
        **context,
        "item": post,
        "form": PostOwnerForm(),
    })


def post_owner_action(request, post: Post, **context):
    form = PostOwnerForm(request.POST, request.FILES)
    if form.is_valid():
        data = form.cleaned_data

        # Transfer ownership to the given username
        if data["transfer_ownership"]:
            user = User.objects.filter(slug=data["transfer_ownership"].strip()).first()
            if user:
                post.author = user
                post.save()

        return render(request, "godmode/message.html", {
            **context,
            "title": f"Настройки поста «{post.title}» сохранены",
            "message": "Ура 🎉",
        })
    else:
        return render(request, "godmode/action.html", {
            **context,
            "item": post,
            "form": form,
        })

