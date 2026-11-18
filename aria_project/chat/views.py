"""Ask Aria page: the chat UI for the RAG chatbot (chatbot:stream).

This view only renders the page. Questions are posted from the browser to
chatbot:stream, which requires a signed-in account, scopes sources by role and
refuses when no source matches (CLAUDE.md invariants 5 and 6). Nothing here reads
or changes orders or refunds; guests are asked to sign in.
"""
from django.shortcuts import render
from django.views.decorators.http import require_GET

from chatbot.views import MAX_QUESTION_LENGTH


@require_GET
def ask_view(request):
    return render(request, 'chat/ask.html', {
        'max_question_length': MAX_QUESTION_LENGTH,
    })
