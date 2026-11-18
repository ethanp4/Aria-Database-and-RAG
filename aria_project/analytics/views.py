"""Admin analytics screens from the Figma prototype (read-only)."""
from django.shortcuts import render
from django.views.decorators.http import require_GET

from accounts.models import ROLE_ADMIN
from accounts.permissions import role_required


@role_required(ROLE_ADMIN)
@require_GET
def dashboard_view(request):
    return render(request, 'analytics/dashboard.html')


# the same figures as an accessible table (Figma: "Accessible analytics data")
@role_required(ROLE_ADMIN)
@require_GET
def data_view(request):
    return render(request, 'analytics/data.html')
