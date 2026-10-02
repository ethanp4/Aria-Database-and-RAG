from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CustomerEditForm, LoginForm, RegisterForm
from .models import Customer

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Customer.objects.create(
                first_name=data['first_name'] or None,
                last_name=data['last_name'] or None,
                username=data['username'],
                phone=data.get('phone') or None,
                password_hash=make_password(data['password']),
            )
            messages.success(request, 'Account created. You can now log in.')
            return redirect('accounts:login')
    else:
        form = RegisterForm()

    return render(request, 'accounts/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].lower()
            password = form.cleaned_data['password']

            try:
                customer = Customer.objects.get(username=username, is_active=True)
            except Customer.DoesNotExist:
                customer = None

            if customer and check_password(password, customer.password_hash):
                request.session['customer_id'] = customer.customer_id
                messages.success(request, f'Welcome back, {customer.username}.')
                return redirect('accounts:account')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})

def account_view(request):
    customer = get_object_or_404(Customer, customer_id=request.session['customer_id'])
    editing = request.method == 'POST' or request.GET.get('edit') == '1'
 
    if request.method == 'POST':
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('accounts:account')
    elif editing:
        form = CustomerEditForm(instance=customer)
    else:
        form = None

    return render(request, 'accounts/userinfo.html', {
        'customer': customer,
        'form': form,
        'editing': editing,
    })

def logout_view(request):
    request.session.flush()
    messages.success(request, 'You have been logged out.')
    return redirect('accounts:login')
