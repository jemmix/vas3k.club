import logging

from django import forms
from django.shortcuts import render

from posts.models.post import Post
from tags.models import Tag, UserTag


class TagJoinForm(forms.Form):
    new_tag = forms.ModelChoiceField(
        label="Тег для объединения (выбранный ниже станет главным, а этот будет удален)",
        queryset=Tag.objects.filter(is_visible=True, group=Tag.GROUP_COLLECTIBLE),
        empty_label="---",
        required=True,
    )


def get_join_tag_action(request, tag: Tag, **context):
    if tag.group != Tag.GROUP_COLLECTIBLE:
        return render(request, "godmode/message.html", {
            **context,
            "title": "😟 Этот тег нельзя объединить",
            "message": "Можно объединять только коллекционные теги, которые созданы юзерами.",
        })

    return render(request, "godmode/action.html", {
        **context,
        "item": tag,
        "form": TagJoinForm(),
    })


def post_join_tag_action(request, tag: Tag, **context):
    form = TagJoinForm(request.POST, request.FILES)
    if form.is_valid():
        tag_to_delete = tag
        new_main_tag = form.cleaned_data["new_tag"]

        # Update post tags
        Post.objects.filter(collectible_tag_code=tag_to_delete.code).update(collectible_tag_code=new_main_tag.code)

        # Update user tags
        for user_tag in UserTag.objects.filter(tag=tag_to_delete):
            try:
                user_tag.tag = new_main_tag
                user_tag.save()
            except Exception as ex:
                logging.warning(f"UserTag '{user_tag.user_id}' is duplicate. Skipped. {ex}")

        Tag.objects.filter(code=tag_to_delete.code).delete()

        return render(request, "godmode/message.html", {
            **context,
            "title": f"Теш «{tag_to_delete.name}» объединен с тегом «{new_main_tag.name}»",
            "message": f"Теперь все посты и пользователи с тегом «{tag_to_delete.name}» "
                       f"будут использовать тег «{new_main_tag.name}».",
        })
    else:
        return render(request, "godmode/action.html", {
            **context,
            "item": tag,
            "form": form,
        })
