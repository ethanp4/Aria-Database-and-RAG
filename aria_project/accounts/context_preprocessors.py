from .models import Profile

# this gets the profile info from the session and makes it available in templates
def current_profile(request):
    profile_id = Profile.objects.filter(account_id=request.session.get('account_id')).values_list('profile_id', flat=True).first()
    profile = (
        Profile.objects.filter(profile_id=profile_id).first()
        if profile_id
        else None
    )
    return {"profile": profile}

def account_info(request):
    account_id = request.session.get('account_id')
    username = request.session.get('username')
    return {"account_id": account_id, "username": username}