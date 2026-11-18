"""Ask Aria chat screen from the Figma prototype, as a UI stub.

The RAG chatbot is not built yet. This page only renders the designed states
(?state=answer|no-source|action-boundary) with fixed sample content from the
template. It has no POST handler, writes nothing, and never reads orders or
refunds: CLAUDE.md invariants 5 and 6 (inform only, refuse without a source).
"""
from django.shortcuts import render
from django.views.decorators.http import require_GET

# state key -> label for the sample-conversation switcher
STATES = {
    'answer': 'Policy answer',
    'no-source': 'No source found',
    'action-boundary': 'Asked to take an action',
}
DEFAULT_STATE = 'answer'


@require_GET
def ask_view(request):
    state = request.GET.get('state', DEFAULT_STATE)
    if state not in STATES:
        state = DEFAULT_STATE
    return render(request, 'chat/ask.html', {
        'state': state,
        'states': STATES.items(),
    })
