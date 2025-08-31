# views.py
from django.shortcuts import render

def test_page(request):
    return render(request, "server/test.html")


def test_chat_server(request):
    return render(request, "server/test_chat_server.html")

# Create your views here.
