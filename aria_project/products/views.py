from django.shortcuts import render

from .models import Product

def dashboard_view(request):
    return render(request, 'products/dashboard.html')

def browse_view(request):
    products = Product.objects.filter(is_active=True)
    return render(request, 'products/browse.html', {'products': products})