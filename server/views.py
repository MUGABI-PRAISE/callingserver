# views.py
from django.shortcuts import render

def test_page(request):
    return render(request, "server/test.html")

# Create your views here.
