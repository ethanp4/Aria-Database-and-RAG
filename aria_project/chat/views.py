"""Ask Aria chat screen from the Figma prototype, as a UI stub.

The RAG chatbot is not built yet. This page only renders the designed states
(?state=answer|no-source|action-boundary). It has no POST handler and no access
to orders/refunds: CLAUDE.md invariants 5 and 6 (inform only, refuse without a source).
"""
from django.shortcuts import render
from django.views.decorators.http import require_GET

STATES = ('answer', 'no-source', 'action-boundary')


@require_GET
def ask_view(request):
    state = request.GET.get('state', 'answer')
    if state not in STATES:
        state = 'answer'
    return render(request, 'chat/ask.html', {'state': state})
