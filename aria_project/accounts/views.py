from django.template import loader
from django.http import HttpResponse


def login(request):
    template = loader.get_template('authpage.html')
    return HttpResponse(template.render())

def register(request):
    template = loader.get_template('authpage.html')
    return HttpResponse(template.render())
