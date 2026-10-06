from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import get_object_or_404, redirect, render

from .forms import LoginForm, ProfileEditForm, RegisterForm
from .models import Account, Profile

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Account.objects.create(
                username=data['username'],
                password_hash=make_password(data['password']),
            )
            messages.success(request, 'Login created. Please finish your profile.')

            account = Account.objects.get(username=data['username'])
            request.session['account_id'] = account.account_id
            request.session['username'] = account.username

            return redirect('accounts:update_profile')
    else:
        form = RegisterForm()

    return render(request, 'accounts/auth.html', {'form': form, 'page_title': 'Register'})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].lower()
            password = form.cleaned_data['password']

            try:
                account = Account.objects.get(username=username)
            except Account.DoesNotExist:
                account = None

            if account and check_password(password, account.password_hash):
                request.session['account_id'] = account.account_id
                request.session['username'] = account.username
                messages.success(request, f'Welcome back, {account.username}.')
                return redirect('products:browse')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'accounts/auth.html', {'form': form, 'page_title': 'Log in'})

def update_profile(request, account_id=None):
    if account_id is None:
        account_id = request.session.get('account_id')
        if not account_id:
            messages.error(request, 'You must be logged in to update your profile.')
            return redirect('accounts:login')

    try:
        profile = Profile.objects.get(account_id=account_id)
        messages.info(request, 'Updating existing profile')
    except Profile.DoesNotExist:
        profile = Profile.objects.create(account_id=account_id)
        messages.info(request, 'Creating new profile')

    if request.method == 'POST':
        form = ProfileEditForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('products:dashboard')
    else:
        form = ProfileEditForm(instance=profile)

    return render(request, 'accounts/auth.html', {'form': form, 'page_title': "Create profile"})


def logout_view(request):
    request.session.flush()
    messages.success(request, 'You have been logged out.')
    return redirect('accounts:login')
