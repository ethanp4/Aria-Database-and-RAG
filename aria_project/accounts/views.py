from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AddressForm, LoginForm, ProfileEditForm, RegisterForm
from .models import Account, Address, Profile
from .permissions import current_account, login_required

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
            request.session.cycle_key()  # new session id on login (prevents session fixation)
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
                request.session.cycle_key()  # new session id on login (prevents session fixation)
                request.session['account_id'] = account.account_id
                request.session['username'] = account.username
                messages.success(request, f'Welcome back, {account.username}.')
                return redirect('products:browse')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'accounts/auth.html', {'form': form, 'page_title': 'Log in'})

#profile row is only created on the first valid submit (email is unique, so no blank rows)
@login_required
def update_profile(request):
    account = current_account(request)
    profile = Profile.objects.filter(account=account).first()

    if request.method == 'POST':
        form = ProfileEditForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.account = account
            profile.save()
            messages.success(request, 'Profile updated.')
            return redirect('products:browse')
    else:
        form = ProfileEditForm(instance=profile)

    return render(request, 'accounts/auth.html', {'form': form, 'page_title': "Create profile"})


@require_POST
def logout_view(request):
    request.session.flush()
    messages.success(request, 'You have been logged out.')
    return redirect('accounts:login')


#saves an address for the account; a new default replaces the old default of the same type
def save_address(account, form):
    with transaction.atomic():
        # lock the owner so concurrent saves for one account run one at a time
        Account.objects.select_for_update().get(pk=account.pk)
        address = form.save(commit=False)
        address.account = account
        if address.is_default:
            Address.objects.filter(
                account=account,
                address_type=address.address_type,
                is_default=True,
            ).exclude(pk=address.pk).update(is_default=False)
        address.save()
    return address


@login_required
def address_list(request):
    addresses = Address.objects.filter(account=current_account(request)).order_by('address_type', '-is_default', 'address_id')
    return render(request, 'accounts/address_list.html', {'addresses': addresses})


@login_required
def address_create(request):
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            save_address(current_account(request), form)
            messages.success(request, 'Address added.')
            return redirect('accounts:address_list')
    else:
        form = AddressForm()

    return render(request, 'accounts/address_form.html', {'form': form, 'page_title': 'Add address'})


@login_required
def address_edit(request, address_id):
    address = get_object_or_404(Address, address_id=address_id, account=current_account(request))
    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            save_address(current_account(request), form)
            messages.success(request, 'Address updated.')
            return redirect('accounts:address_list')
    else:
        form = AddressForm(instance=address)

    return render(request, 'accounts/address_form.html', {'form': form, 'page_title': 'Edit address'})


@login_required
@require_POST
def address_delete(request, address_id):
    address = get_object_or_404(Address, address_id=address_id, account=current_account(request))
    address.delete()
    messages.success(request, 'Address removed.')
    return redirect('accounts:address_list')
